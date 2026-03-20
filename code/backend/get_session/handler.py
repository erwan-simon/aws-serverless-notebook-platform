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


def _response(status, service_name, message=None, url=None, **extra):
    body = {"status": status, "service_name": service_name}
    if message:
        body["message"] = message
    if url:
        body["url"] = url
    body.update(extra)
    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps(body)}


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
        if svc["status"] == "DRAINING":
            return _response("draining", service_name, message="Previous session is shutting down, please wait...")

    if not active_service:
        return _response("stopped", service_name)

    alb_dns_name = os.environ["ALB_DNS_NAME"]

    # Check for running tasks
    tasks = ecs.list_tasks(cluster=cluster_name, serviceName=service_name, desiredStatus="RUNNING")

    if not tasks["taskArns"]:
        # No running tasks — check stopped tasks for failure info
        stopped = ecs.list_tasks(cluster=cluster_name, serviceName=service_name, desiredStatus="STOPPED")
        if stopped["taskArns"]:
            stopped_details = ecs.describe_tasks(cluster=cluster_name, tasks=stopped["taskArns"])
            task = sorted(stopped_details["tasks"], key=lambda t: t.get("stoppingAt", ""), reverse=True)[0]
            reason = task.get("stoppedReason", "")
            container = task.get("containers", [{}])[0]
            container_reason = container.get("reason", "")
            exit_code = container.get("exitCode")

            if "OutOfMemory" in reason or "OutOfMemory" in container_reason:
                return _response("error", service_name, message="Container stopped: out of memory. Stop the session and start a new one with more memory.")
            if "CannotPullContainerError" in reason:
                return _response("error", service_name, message="Failed to pull the Docker image. Check the image URI.")
            if exit_code is not None and exit_code != 0:
                return _response("error", service_name, message=f"Container exited with code {exit_code}. {container_reason}")
            if reason:
                return _response("error", service_name, message=reason)

        return _response("starting", service_name, message="Provisioning task...")

    task_details = ecs.describe_tasks(cluster=cluster_name, tasks=tasks["taskArns"])
    task = task_details["tasks"][0]

    # Extract task definition details
    task_def = ecs.describe_task_definition(taskDefinition=task["taskDefinitionArn"])
    td = task_def["taskDefinition"]
    container_def = td["containerDefinitions"][0]

    extra = {
        "vcpu": td.get("cpu", ""),
        "memory": td.get("memory", ""),
        "image": container_def.get("image", ""),
        "iam_role": td.get("taskRoleArn", ""),
        "started_at": task.get("startedAt", task.get("createdAt", "")),
    }
    if hasattr(extra["started_at"], "isoformat"):
        extra["started_at"] = extra["started_at"].isoformat()

    last_status = task["lastStatus"]
    if last_status != "RUNNING":
        return _response("starting", service_name, message=f"Task is {last_status.lower()}...", **extra)

    if task.get("healthStatus") != "HEALTHY":
        return _response("starting", service_name, message="Container is running, waiting for health check...", **extra)

    jupyter_token = ""
    for env_var in container_def.get("environment", []):
        if env_var["name"] == "JUPYTER_TOKEN":
            jupyter_token = env_var["value"]
            break

    url = f"http://{alb_dns_name}/s/{service_name}/"
    if jupyter_token:
        url += f"?token={jupyter_token}"

    return _response("running", service_name, url=url, **extra)
