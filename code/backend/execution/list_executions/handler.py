import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Attr

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
        return {"statusCode": 403, "headers": HEADERS, "body": json.dumps({"error": "Forbidden"})}

    notebook_id = event.get("pathParameters", {}).get("notebook_id", "")
    if not notebook_id:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Missing notebook_id"})}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["EXECUTIONS_TABLE"])

    executions = []
    response = table.scan(FilterExpression=Attr("notebook_id").eq(notebook_id))
    executions.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(
            FilterExpression=Attr("notebook_id").eq(notebook_id),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        executions.extend(response.get("Items", []))

    executions.sort(key=lambda e: e.get("started_at", ""), reverse=True)

    result = [
        {
            "id": ex["id"],
            "status": ex.get("status", "PENDING"),
            "started_at": ex.get("started_at", ""),
            "finished_at": ex.get("finished_at", ""),
            "owner_email": ex.get("owner_email", ""),
            "output_s3_key": ex.get("output_s3_key", ""),
            "trigger_type": ex.get("trigger_type", "manual"),
        }
        for ex in executions
    ]

    logger.info("Returning %d executions for notebook %s", len(result), notebook_id)
    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps(result)}
