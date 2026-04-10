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

_ssm = boto3.client("ssm")
_origin_secret = _ssm.get_parameter(
    Name=os.environ["ORIGIN_VERIFY_SECRET_SSM_NAME"], WithDecryption=True
)["Parameter"]["Value"]
assert _origin_secret, "Failed to retrieve origin verify secret from SSM"


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {"statusCode": 403, "headers": HEADERS, "body": json.dumps({"error": "Forbidden"})}

    config_id = event.get("pathParameters", {}).get("id", "")
    if not config_id:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Missing configuration id"})}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["CONFIGURATIONS_TABLE"])

    item = table.get_item(Key={"id": config_id}).get("Item")
    if not item:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Configuration not found"})}

    logger.info("Deleting configuration: id=%s, name=%s", config_id, item.get("name"))
    table.delete_item(Key={"id": config_id})

    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps({"message": "Configuration deleted"})}
