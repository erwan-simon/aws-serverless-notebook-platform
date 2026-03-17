import json
import os

import boto3

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

STARTING_RESPONSE = {
    "statusCode": 200,
    "headers": HEADERS,
    "body": json.dumps({"status": "starting"}),
}

# CloudFront origin verify secret — read once at cold start from SSM.
# See: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html
_ssm = boto3.client("ssm")
_origin_secret = _ssm.get_parameter(
    Name=os.environ["ORIGIN_VERIFY_SECRET_SSM_NAME"], WithDecryption=True
)["Parameter"]["Value"]
assert _origin_secret, "Failed to retrieve origin verify secret from SSM"


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {"statusCode": 403, "headers": HEADERS, "body": json.dumps({"error": "Forbidden"})}

    service_name = event["pathParameters"]["service_name"]
    cluster_name = os.environ["ECS_CLUSTER_NAME"]
    environment_name = os.environ["ENVIRONMENT_NAME"]

    if not service_name.startswith(f"{environment_name}_"):
        return {
            "statusCode": 403,
            "headers": HEADERS,
            "body": json.dumps({"error": "Invalid service name"}),
        }

    ecs = boto3.client("ecs")
    ec2 = boto3.client("ec2")

    tasks = ecs.list_tasks(
        cluster=cluster_name, serviceName=service_name, desiredStatus="RUNNING"
    )

    if not tasks["taskArns"]:
        return STARTING_RESPONSE

    task_details = ecs.describe_tasks(cluster=cluster_name, tasks=tasks["taskArns"])
    task = task_details["tasks"][0]

    if task["lastStatus"] != "RUNNING":
        return STARTING_RESPONSE

    if task.get("healthStatus") != "HEALTHY":
        return STARTING_RESPONSE

    eni_id = None
    for attachment in task.get("attachments", []):
        for detail in attachment.get("details", []):
            if detail["name"] == "networkInterfaceId":
                eni_id = detail["value"]
                break

    if not eni_id:
        return STARTING_RESPONSE

    eni = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    public_ip = eni["NetworkInterfaces"][0]["Association"]["PublicIp"]

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"status": "running", "url": f"http://{public_ip}:8888"}),
    }
