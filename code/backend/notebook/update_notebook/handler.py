import base64
import json
import logging
import os
import re
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
import nbformat
from nbconvert import HTMLExporter

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

LABEL_REGEX = re.compile(os.environ["LABEL_REGEX"])


def _validate_labels(labels):
    if not isinstance(labels, list):
        return "labels must be a list"
    for label in labels:
        if not isinstance(label, str) or not LABEL_REGEX.match(label):
            return f"Invalid label: {label}"
    return None


def _sync_labels(labels, labels_table):
    for label in labels:
        labels_table.put_item(Item={"name": label})


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {
            "statusCode": 403,
            "headers": HEADERS,
            "body": json.dumps({"error": "Forbidden"}),
        }

    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    owner_id = claims.get("sub", "")
    owner_email = claims.get("email", "")
    if not owner_id:
        return {
            "statusCode": 401,
            "headers": HEADERS,
            "body": json.dumps({"error": "Missing user identity"}),
        }

    notebook_id = event.get("pathParameters", {}).get("id", "")
    if not notebook_id:
        return {
            "statusCode": 400,
            "headers": HEADERS,
            "body": json.dumps({"error": "Missing notebook id"}),
        }

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["NOTEBOOKS_TABLE"])

    notebook = table.get_item(Key={"id": notebook_id}).get("Item")
    if not notebook:
        return {
            "statusCode": 404,
            "headers": HEADERS,
            "body": json.dumps({"error": "Notebook not found"}),
        }

    body = json.loads(event.get("body", "{}") or "{}")
    logger.info(
        "Updating notebook: id=%s, body keys=%s", notebook_id, list(body.keys())
    )

    expr_set = []
    expr_remove = []
    attr_names = {}
    attr_values = {}

    # Notebook file content
    if "content" in body:
        try:
            raw = base64.b64decode(body["content"])
        except Exception:
            return {
                "statusCode": 400,
                "headers": HEADERS,
                "body": json.dumps({"error": "Invalid base64 content"}),
            }
        try:
            nb = nbformat.reads(raw.decode("utf-8"), as_version=4)
            HTMLExporter().from_notebook_node(nb)
        except Exception as e:
            return {
                "statusCode": 400,
                "headers": HEADERS,
                "body": json.dumps({"error": f"Invalid notebook: {e}"}),
            }
        for cell in nb.cells:
            if cell.get("cell_type") == "code":
                cell["outputs"] = []
                cell["execution_count"] = None
        raw = nbformat.writes(nb).encode("utf-8")
        s3 = boto3.client("s3")
        bucket = os.environ["NOTEBOOKS_BUCKET"]
        s3.put_object(
            Bucket=bucket,
            Key=notebook["s3_key"],
            Body=raw,
            ContentType="application/x-ipynb+json",
        )
        rendered_s3_key = notebook.get("rendered_s3_key")
        if rendered_s3_key:
            s3.delete_object(Bucket=bucket, Key=rendered_s3_key)
            attr_names["#rendered_s3_key"] = "rendered_s3_key"
            expr_remove.append("#rendered_s3_key")
        attr_names["#uploaded_at"] = "uploaded_at"
        expr_set.append("#uploaded_at = :uploaded_at")
        attr_values[":uploaded_at"] = datetime.now(timezone.utc).isoformat()

    # Labels
    if "labels" in body:
        labels = list(set(body["labels"]))
        err = _validate_labels(labels)
        if err:
            return {
                "statusCode": 400,
                "headers": HEADERS,
                "body": json.dumps({"error": err}),
            }
        attr_names["#labels"] = "labels"
        expr_set.append("#labels = :labels")
        attr_values[":labels"] = labels

    # Schedule
    if body.get("unschedule"):
        schedule_name = notebook.get("schedule_name")
        if schedule_name:
            scheduler = boto3.client("scheduler")
            try:
                scheduler.delete_schedule(Name=schedule_name)
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
        for field in (
            "schedule_cron",
            "schedule_timezone",
            "schedule_role_arn",
            "schedule_image_uri",
            "schedule_name",
            "schedule_vcpu",
            "schedule_memory",
        ):
            attr_names[f"#{field}"] = field
            expr_remove.append(f"#{field}")

    elif "schedule_cron" in body:
        cron_expression = body["schedule_cron"]
        iam_role_arn = body.get("schedule_iam_role_arn", "")
        ecr_image_uri = body.get("schedule_ecr_image_uri", "")
        vcpu = body.get("schedule_vcpu")
        memory = body.get("schedule_memory")
        schedule_timezone = body.get("schedule_timezone") or "UTC"

        if not cron_expression or not iam_role_arn or not ecr_image_uri:
            return {
                "statusCode": 400,
                "headers": HEADERS,
                "body": json.dumps(
                    {
                        "error": "schedule_cron, schedule_iam_role_arn, and schedule_ecr_image_uri are required"
                    }
                ),
            }

        environment_name = os.environ["ENVIRONMENT_NAME"]
        scheduler_role_arn = os.environ["SCHEDULER_ROLE_ARN"]
        run_notebook_lambda_arn = os.environ["RUN_NOTEBOOK_LAMBDA_ARN"]
        schedule_name = f"{environment_name}_nb_{notebook_id[:8]}"

        scheduler = boto3.client("scheduler")
        schedule_kwargs = dict(
            Name=schedule_name,
            ScheduleExpression=cron_expression,
            ScheduleExpressionTimezone=schedule_timezone,
            FlexibleTimeWindow={"Mode": "OFF"},
            Target={
                "Arn": run_notebook_lambda_arn,
                "RoleArn": scheduler_role_arn,
                "Input": json.dumps(
                    {
                        k: v
                        for k, v in {
                            "source": "scheduler",
                            "notebook_id": notebook_id,
                            "iam_role_arn": iam_role_arn,
                            "ecr_image_uri": ecr_image_uri,
                            "owner_id": owner_id,
                            "owner_email": owner_email,
                            "vcpu": vcpu,
                            "memory": memory,
                        }.items()
                        if v is not None
                    }
                ),
            },
            ActionAfterCompletion="NONE",
        )
        try:
            scheduler.create_schedule(**schedule_kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConflictException":
                scheduler.update_schedule(**schedule_kwargs)
            elif e.response["Error"]["Code"] == "ValidationException":
                return {
                    "statusCode": 400,
                    "headers": HEADERS,
                    "body": json.dumps({"error": e.response["Error"]["Message"]}),
                }
            else:
                raise

        schedule_fields = {
            "schedule_cron": cron_expression,
            "schedule_timezone": schedule_timezone,
            "schedule_role_arn": iam_role_arn,
            "schedule_image_uri": ecr_image_uri,
            "schedule_name": schedule_name,
            "schedule_vcpu": vcpu if vcpu is not None else 0,
            "schedule_memory": memory if memory is not None else 0,
        }
        for field, value in schedule_fields.items():
            attr_names[f"#{field}"] = field
            expr_set.append(f"#{field} = :{field}")
            attr_values[f":{field}"] = value

    if not expr_set and not expr_remove:
        return {
            "statusCode": 400,
            "headers": HEADERS,
            "body": json.dumps({"error": "No fields to update"}),
        }

    expression = ""
    if expr_set:
        expression += "SET " + ", ".join(expr_set)
    if expr_remove:
        expression += " REMOVE " + ", ".join(expr_remove)

    table.update_item(
        Key={"id": notebook_id},
        UpdateExpression=expression,
        ExpressionAttributeNames=attr_names,
        **({"ExpressionAttributeValues": attr_values} if attr_values else {}),
    )

    # Sync new labels to centralized labels table
    if "labels" in body and body["labels"]:
        labels_table = dynamodb.Table(os.environ["LABELS_TABLE"])
        _sync_labels(body["labels"], labels_table)

    logger.info(
        "Notebook updated: id=%s, labels=%s, schedule=%s",
        notebook_id,
        body.get("labels"),
        body.get("schedule_cron", "none"),
    )
    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"message": "Notebook updated"}),
    }
