import os
from datetime import datetime, timezone

import boto3

TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "STOPPED"}


def _map_ecs_status(detail):
    last_status = detail.get("lastStatus", "")
    if last_status in ("PROVISIONING", "PENDING", "ACTIVATING"):
        return "PENDING"
    if last_status == "RUNNING":
        return "RUNNING"
    if last_status in ("DEPROVISIONING", "STOPPING", "STOPPED"):
        containers = detail.get("containers", [])
        if containers and containers[0].get("exitCode") == 0:
            return "SUCCEEDED"
        return "FAILED"
    return "PENDING"


def handler(event, context):
    detail = event.get("detail", {})
    task_arn = detail.get("taskArn", "")
    if not task_arn:
        raise ValueError(f"Event has no taskArn in detail: {detail}")

    # Get execution_id from task tags via describe_tasks (works on stopped tasks)
    ecs = boto3.client("ecs")
    cluster_name = os.environ["ECS_CLUSTER_NAME"]
    result = ecs.describe_tasks(cluster=cluster_name, tasks=[task_arn], include=["TAGS"])
    tasks = result.get("tasks", [])
    if not tasks:
        raise RuntimeError(f"Task not found in ECS: {task_arn}")

    tags = {t["key"]: t["value"] for t in tasks[0].get("tags", [])}
    execution_id = tags.get("execution_id")
    if not execution_id:
        return

    new_status = _map_ecs_status(detail)

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["EXECUTIONS_TABLE"])

    item = table.get_item(Key={"id": execution_id}).get("Item")
    if not item:
        raise RuntimeError(f"Execution not found in DynamoDB: {execution_id}")

    current_status = item.get("status", "PENDING")
    if current_status in TERMINAL_STATUSES:
        return

    if new_status == current_status:
        return

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
