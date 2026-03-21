import json
import os
import uuid
from datetime import datetime, timezone

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

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    created_by = claims.get("email", "")

    body = json.loads(event.get("body", "{}"))
    iam_role_arn = body.get("iam_role_arn", "").strip()
    name = body.get("name", "").strip()
    description = body.get("description", "").strip()

    if not iam_role_arn:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "iam_role_arn is required"})}
    if not name:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "name is required"})}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["ROLES_TABLE"])

    item = {
        "id": str(uuid.uuid4()),
        "iam_role_arn": iam_role_arn,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
    }
    if description:
        item["description"] = description

    table.put_item(Item=item)

    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps(item)}
