import json
import os
import re

import boto3

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

# CloudFront origin verify secret — read once at cold start from SSM.
# See: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html
_ssm = boto3.client("ssm")
_origin_secret = _ssm.get_parameter(
    Name=os.environ["ORIGIN_VERIFY_SECRET_SSM_NAME"], WithDecryption=True
)["Parameter"]["Value"]
assert _origin_secret, "Failed to retrieve origin verify secret from SSM"


def _make_service_name(environment_name, user_identity):
    slug = re.sub(r"[^a-zA-Z0-9-]", "-", user_identity)[:50]
    return f"{environment_name}_{slug}"


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {"statusCode": 403, "headers": HEADERS, "body": json.dumps({"error": "Forbidden"})}

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    user_sub = claims.get("sub", "")
    if not user_sub:
        return {"statusCode": 401, "headers": HEADERS, "body": json.dumps({"error": "Missing user identity"})}

    environment_name = os.environ["ENVIRONMENT_NAME"]
    cluster_name = os.environ["ECS_CLUSTER_NAME"]
    service_name = _make_service_name(environment_name, user_sub)

    ecs = boto3.client("ecs")

    # Check if service exists and is ACTIVE
    existing = ecs.describe_services(cluster=cluster_name, services=[service_name])
    active_service = None
    for svc in existing.get("services", []):
        if svc["status"] == "ACTIVE":
            active_service = svc
            break

    if not active_service:
        return {
            "statusCode": 200,
            "headers": HEADERS,
            "body": json.dumps({"status": "stopped"}),
        }

    # Check task status
    tasks = ecs.list_tasks(cluster=cluster_name, serviceName=service_name, desiredStatus="RUNNING")
    if not tasks["taskArns"]:
        return {
            "statusCode": 200,
            "headers": HEADERS,
            "body": json.dumps({"status": "pending", "service_name": service_name}),
        }

    task_details = ecs.describe_tasks(cluster=cluster_name, tasks=tasks["taskArns"])
    task = task_details["tasks"][0]

    # Extract task definition details for cpu/memory/image/role
    task_def = ecs.describe_task_definition(taskDefinition=task["taskDefinitionArn"])
    td = task_def["taskDefinition"]
    container_def = td["containerDefinitions"][0]

    task_info = {
        "service_name": service_name,
        "vcpu": td.get("cpu", ""),
        "memory": td.get("memory", ""),
        "image": container_def.get("image", ""),
        "iam_role": td.get("taskRoleArn", ""),
        "started_at": task.get("startedAt", task.get("createdAt", "")),
    }

    # Convert datetime to ISO string if needed
    started = task_info["started_at"]
    if hasattr(started, "isoformat"):
        task_info["started_at"] = started.isoformat()

    if task["lastStatus"] != "RUNNING" or task.get("healthStatus") != "HEALTHY":
        return {
            "statusCode": 200,
            "headers": HEADERS,
            "body": json.dumps({"status": "pending", **task_info}),
        }

    # Get public IP
    eni_id = None
    for attachment in task.get("attachments", []):
        for detail in attachment.get("details", []):
            if detail["name"] == "networkInterfaceId":
                eni_id = detail["value"]
                break

    if not eni_id:
        return {
            "statusCode": 200,
            "headers": HEADERS,
            "body": json.dumps({"status": "pending", **task_info}),
        }

    ec2 = boto3.client("ec2")
    eni = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    public_ip = eni["NetworkInterfaces"][0]["Association"]["PublicIp"]

    jupyter_token = ""
    for env_var in container_def.get("environment", []):
        if env_var["name"] == "JUPYTER_TOKEN":
            jupyter_token = env_var["value"]
            break

    url = f"http://{public_ip}:8888"
    if jupyter_token:
        url += f"?token={jupyter_token}"

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"status": "running", "url": url, **task_info}),
    }
