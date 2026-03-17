import json
import os
from datetime import datetime, timezone

import boto3

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "STOPPED"}

# CloudFront origin verify secret — read once at cold start from SSM.
# See: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html
_ssm = boto3.client("ssm")
_origin_secret = _ssm.get_parameter(
    Name=os.environ["ORIGIN_VERIFY_SECRET_SSM_NAME"], WithDecryption=True
)["Parameter"]["Value"]
assert _origin_secret, "Failed to retrieve origin verify secret from SSM"


def _map_ecs_status(task):
    last_status = task.get("lastStatus", "")
    if last_status in ("PROVISIONING", "PENDING", "ACTIVATING"):
        return "PENDING"
    if last_status == "RUNNING":
        return "RUNNING"
    if last_status in ("DEPROVISIONING", "STOPPING", "STOPPED"):
        containers = task.get("containers", [])
        if containers and containers[0].get("exitCode") == 0:
            return "SUCCEEDED"
        return "FAILED"
    return "PENDING"


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {"statusCode": 403, "headers": HEADERS, "body": json.dumps({"error": "Forbidden"})}

    execution_id = event.get("pathParameters", {}).get("execution_id", "")
    if not execution_id:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Missing execution_id"})}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["EXECUTIONS_TABLE"])

    item = table.get_item(Key={"id": execution_id}).get("Item")
    if not item:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Execution not found"})}

    current_status = item.get("status", "PENDING")

    base_fields = {
        "owner_email": item.get("owner_email", ""),
        "trigger_type": item.get("trigger_type", ""),
        "notebook_name": item.get("notebook_name", ""),
        "notebook_id": item.get("notebook_id", ""),
    }

    # If already terminal, return directly
    if current_status in TERMINAL_STATUSES:
        return {
            "statusCode": 200,
            "headers": HEADERS,
            "body": json.dumps({
                **base_fields,
                "status": current_status,
                "output_s3_key": item.get("output_s3_key", ""),
                "started_at": item.get("started_at", ""),
                "finished_at": item.get("finished_at", ""),
            }),
        }

    # Check ECS task status
    ecs = boto3.client("ecs")
    cluster_name = os.environ["ECS_CLUSTER_NAME"]
    task_arn = item.get("task_arn", "")

    try:
        result = ecs.describe_tasks(cluster=cluster_name, tasks=[task_arn])
        tasks = result.get("tasks", [])
        if not tasks:
            new_status = "FAILED"
        else:
            new_status = _map_ecs_status(tasks[0])
    except Exception:
        new_status = "FAILED"

    # Update DynamoDB if status changed
    if new_status != current_status:
        update_expr = "SET #s = :s"
        expr_values = {":s": new_status}
        expr_names = {"#s": "status"}

        if new_status in TERMINAL_STATUSES:
            update_expr += ", finished_at = :f"
            expr_values[":f"] = datetime.now(timezone.utc).isoformat()

        table.update_item(
            Key={"id": execution_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names,
        )

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({
            **base_fields,
            "status": new_status,
            "output_s3_key": item.get("output_s3_key", ""),
            "started_at": item.get("started_at", ""),
            "finished_at": item.get("finished_at", "") if new_status not in TERMINAL_STATUSES else datetime.now(timezone.utc).isoformat(),
        }),
    }
