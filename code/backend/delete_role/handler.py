import json
import os

import boto3

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

    role_id = event.get("pathParameters", {}).get("id", "")
    if not role_id:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Missing role id"})}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["ROLES_TABLE"])

    item = table.get_item(Key={"id": role_id}).get("Item")
    if not item:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Role not found"})}

    table.delete_item(Key={"id": role_id})

    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps({"message": "Role deleted"})}
