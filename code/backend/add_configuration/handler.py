import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()

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
    name = body.get("name", "").strip()
    ecr_image_uri = body.get("ecr_image_uri", "").strip()
    iam_role_arn = body.get("iam_role_arn", "").strip()
    description = body.get("description", "").strip()
    vcpu = body.get("vcpu")
    memory = body.get("memory")

    if not name:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "name is required"})}
    if not ecr_image_uri:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "ecr_image_uri is required"})}
    if not iam_role_arn:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "iam_role_arn is required"})}
    if not vcpu or not memory:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "vcpu and memory are required"})}
    vcpu = int(vcpu)
    memory = int(memory)

    # Run validation notebook with this image + role pair
    lambda_client = boto3.client("lambda")
    payload = {
        "source": "scheduler",
        "notebook_id": os.environ["VALIDATION_NOTEBOOK_ID"],
        "iam_role_arn": iam_role_arn,
        "ecr_image_uri": ecr_image_uri,
        "owner_id": os.environ["TECHNICAL_OWNER_ID"],
        "owner_email": os.environ["TECHNICAL_OWNER_ID"],
        "vcpu": vcpu,
        "memory": memory,
    }
    resp = lambda_client.invoke(
        FunctionName=os.environ["RUN_NOTEBOOK_FUNCTION_NAME"],
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )
    result = json.loads(resp["Payload"].read())
    result_body = json.loads(result.get("body", "{}"))
    execution_id = result_body.get("execution_id")
    if not execution_id:
        error = result_body.get("error", "Unknown error")
        return {"statusCode": 500, "headers": HEADERS, "body": json.dumps({"error": f"Validation launch failed: {error}"})}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["CONFIGURATIONS_TABLE"])

    item = {
        "id": str(uuid.uuid4()),
        "name": name,
        "ecr_image_uri": ecr_image_uri,
        "iam_role_arn": iam_role_arn,
        "vcpu": vcpu,
        "memory": memory,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
        "validation_execution_id": execution_id,
    }
    if description:
        item["description"] = description

    table.put_item(Item=item)

    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps(item)}
