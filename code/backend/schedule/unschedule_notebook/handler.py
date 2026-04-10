import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

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

    notebook_id = event.get("pathParameters", {}).get("id", "")
    if not notebook_id:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Missing notebook id"})}

    dynamodb = boto3.resource("dynamodb")
    notebooks_table = dynamodb.Table(os.environ["NOTEBOOKS_TABLE"])
    notebook = notebooks_table.get_item(Key={"id": notebook_id}).get("Item")
    if not notebook:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Notebook not found"})}

    schedule_name = notebook.get("schedule_name")
    logger.info("Unscheduling notebook: id=%s, schedule_name=%s", notebook_id, schedule_name)
    if not schedule_name:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Notebook is not scheduled"})}

    scheduler = boto3.client("scheduler")
    try:
        scheduler.delete_schedule(Name=schedule_name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    notebooks_table.update_item(
        Key={"id": notebook_id},
        UpdateExpression="REMOVE schedule_cron, schedule_role_arn, schedule_image_uri, schedule_name",
    )

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"message": "Schedule removed"}),
    }
