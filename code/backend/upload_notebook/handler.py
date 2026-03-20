import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
import nbformat
from nbconvert import HTMLExporter

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
    owner_id = claims.get("sub", "")
    owner_email = claims.get("email", "")
    if not owner_id:
        return {"statusCode": 401, "headers": HEADERS, "body": json.dumps({"error": "Missing user identity"})}

    body = json.loads(event["body"])
    filename = body.get("filename", "")
    content_b64 = body.get("content", "")

    if not filename or not filename.endswith(".ipynb"):
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "File must be a .ipynb notebook"})}

    if ".." in filename:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Invalid filename"})}

    try:
        raw = base64.b64decode(content_b64)
    except Exception:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Invalid base64 content"})}

    # Validate notebook by parsing and converting to HTML
    try:
        nb = nbformat.reads(raw.decode("utf-8"), as_version=4)
        exporter = HTMLExporter()
        exporter.from_notebook_node(nb)
    except Exception as e:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": f"Invalid notebook: {e}"})}

    bucket = os.environ["NOTEBOOKS_BUCKET"]
    prefix = os.environ["NOTEBOOKS_S3_PREFIX"]
    table_name = os.environ["NOTEBOOKS_TABLE"]

    notebook_id = str(uuid.uuid4())
    s3_key = f"{prefix}{notebook_id}.ipynb"

    s3 = boto3.client("s3")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # Step 1: Upload to S3
    s3.put_object(Bucket=bucket, Key=s3_key, Body=raw, ContentType="application/x-ipynb+json")

    # Step 2: Write to DynamoDB — rollback S3 on failure
    item = {
        "id": notebook_id,
        "s3_key": s3_key,
        "name": filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "owner_id": owner_id,
        "owner_email": owner_email,
    }
    for key in ("default_iam_role_arn", "default_ecr_image_uri", "default_vcpu", "default_memory"):
        val = body.get(key)
        if val:
            item[key] = int(val) if key in ("default_vcpu", "default_memory") else val

    try:
        table.put_item(Item=item)
    except Exception as e:
        logger.error("DynamoDB write failed, rolling back S3 object %s: %s", s3_key, e)
        try:
            s3.delete_object(Bucket=bucket, Key=s3_key)
        except Exception as rollback_err:
            logger.error("S3 rollback also failed for %s: %s", s3_key, rollback_err)
        return {"statusCode": 500, "headers": HEADERS, "body": json.dumps({"error": "Failed to register notebook"})}

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"id": notebook_id, "message": "Notebook uploaded successfully"}),
    }
