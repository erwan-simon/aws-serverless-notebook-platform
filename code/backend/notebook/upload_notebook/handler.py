import base64
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
import nbformat
from nbconvert import HTMLExporter

LABEL_REGEX = re.compile(r"^[a-z\u00e0-\u00f6\u00f8-\u00ff0-9\-]+$")

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

    labels = body.get("labels", [])
    if labels:
        for label in labels:
            if not isinstance(label, str) or not LABEL_REGEX.match(label):
                return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": f"Invalid label: {label}"})}
        item["labels"] = list(set(labels))

    try:
        table.put_item(Item=item)
    except Exception as e:
        logger.error("DynamoDB write failed, rolling back S3 object %s: %s", s3_key, e)
        try:
            s3.delete_object(Bucket=bucket, Key=s3_key)
        except Exception as rollback_err:
            logger.error("S3 rollback also failed for %s: %s", s3_key, rollback_err)
        return {"statusCode": 500, "headers": HEADERS, "body": json.dumps({"error": "Failed to register notebook"})}

    # Sync new labels to centralized labels table
    if labels:
        labels_table = dynamodb.Table(os.environ["LABELS_TABLE"])
        for label in item["labels"]:
            labels_table.put_item(Item={"name": label})

    # Create schedule if cron expression provided
    schedule_cron = body.get("schedule_cron", "")
    if schedule_cron:
        schedule_iam = body.get("schedule_iam_role_arn", "")
        schedule_image = body.get("schedule_ecr_image_uri", "")
        schedule_vcpu = body.get("schedule_vcpu")
        schedule_memory = body.get("schedule_memory")

        if schedule_iam and schedule_image:
            environment_name = os.environ["ENVIRONMENT_NAME"]
            scheduler_role_arn = os.environ["SCHEDULER_ROLE_ARN"]
            run_notebook_lambda_arn = os.environ["RUN_NOTEBOOK_LAMBDA_ARN"]
            schedule_name = f"{environment_name}_nb_{notebook_id[:8]}"

            scheduler = boto3.client("scheduler")
            try:
                scheduler.create_schedule(
                    Name=schedule_name,
                    ScheduleExpression=schedule_cron,
                    ScheduleExpressionTimezone="UTC",
                    FlexibleTimeWindow={"Mode": "OFF"},
                    Target={
                        "Arn": run_notebook_lambda_arn,
                        "RoleArn": scheduler_role_arn,
                        "Input": json.dumps({
                            k: v for k, v in {
                                "source": "scheduler",
                                "notebook_id": notebook_id,
                                "iam_role_arn": schedule_iam,
                                "ecr_image_uri": schedule_image,
                                "owner_id": owner_id,
                                "owner_email": owner_email,
                                "vcpu": schedule_vcpu,
                                "memory": schedule_memory,
                            }.items() if v is not None
                        }),
                    },
                    ActionAfterCompletion="NONE",
                )
                table.update_item(
                    Key={"id": notebook_id},
                    UpdateExpression="SET schedule_cron = :cron, schedule_role_arn = :role, schedule_image_uri = :image, schedule_name = :name, schedule_vcpu = :vcpu, schedule_memory = :memory",
                    ExpressionAttributeValues={
                        ":cron": schedule_cron,
                        ":role": schedule_iam,
                        ":image": schedule_image,
                        ":name": schedule_name,
                        ":vcpu": schedule_vcpu if schedule_vcpu is not None else 0,
                        ":memory": schedule_memory if schedule_memory is not None else 0,
                    },
                )
            except ClientError as e:
                logger.error("Failed to create schedule for notebook %s: %s", notebook_id, e)

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"id": notebook_id, "message": "Notebook uploaded successfully"}),
    }
