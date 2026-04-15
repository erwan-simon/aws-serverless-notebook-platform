import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {
            "statusCode": 403,
            "headers": HEADERS,
            "body": json.dumps({"error": "Forbidden"}),
        }

    dynamodb = boto3.resource("dynamodb")
    notebooks_table = dynamodb.Table(os.environ["NOTEBOOKS_TABLE"])
    executions_table = dynamodb.Table(os.environ["EXECUTIONS_TABLE"])

    notebooks = []
    response = notebooks_table.scan()
    notebooks.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = notebooks_table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        notebooks.extend(response.get("Items", []))

    # Scan all executions and group latest by notebook_id
    executions = []
    response = executions_table.scan()
    executions.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = executions_table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        executions.extend(response.get("Items", []))

    latest_exec = {}
    for ex in executions:
        nb_id = ex.get("notebook_id", "")
        started = ex.get("started_at", "")
        if nb_id not in latest_exec or started > latest_exec[nb_id].get(
            "started_at", ""
        ):
            latest_exec[nb_id] = ex

    notebooks.sort(key=lambda n: n.get("uploaded_at", ""), reverse=True)

    technical_owner_id = os.environ.get("TECHNICAL_OWNER_ID", "")
    if technical_owner_id:
        notebooks = [nb for nb in notebooks if nb.get("owner_id") != technical_owner_id]

    result = []
    for nb in notebooks:
        missing = [f for f in ("name", "s3_key") if f not in nb]
        if missing:
            logger.warning(
                "Deleting malformed notebook row (missing %s): %s",
                missing,
                json.dumps(nb, default=str),
            )
            notebooks_table.delete_item(Key={"id": nb["id"]})
            continue
        entry = {
            "id": nb["id"],
            "name": nb["name"],
            "uploaded_at": nb.get("uploaded_at", ""),
            "owner": nb.get("owner_email", ""),
            "schedule_cron": nb.get("schedule_cron", ""),
            "schedule_timezone": nb.get("schedule_timezone", ""),
            "default_iam_role_arn": nb.get("default_iam_role_arn", ""),
            "default_ecr_image_uri": nb.get("default_ecr_image_uri", ""),
            "default_vcpu": int(nb.get("default_vcpu", 0)),
            "default_memory": int(nb.get("default_memory", 0)),
            "labels": nb.get("labels", []),
            "last_execution_date": "",
            "last_execution_status": "",
            "last_execution_id": "",
            "last_execution_task_arn": "",
        }
        ex = latest_exec.get(nb["id"])
        if ex:
            entry["last_execution_date"] = ex.get("started_at", "")
            entry["last_execution_status"] = ex.get("status", "")
            entry["last_execution_id"] = ex.get("id", "")
            entry["last_execution_task_arn"] = ex.get("task_arn", "")
        result.append(entry)

    logger.info("Returning %d notebooks", len(result))
    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps(result)}
