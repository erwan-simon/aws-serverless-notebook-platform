import json
import logging
import os

import boto3
import nbformat
from nbconvert import HTMLExporter

logger = logging.getLogger()
logger.setLevel(logging.INFO)

HEADERS = {
    "Access-Control-Allow-Origin": "*",
}

# CloudFront origin verify secret — read once at cold start from SSM.
# See: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html
_ssm = boto3.client("ssm")
_origin_secret = _ssm.get_parameter(
    Name=os.environ["ORIGIN_VERIFY_SECRET_SSM_NAME"], WithDecryption=True
)["Parameter"]["Value"]
assert _origin_secret, "Failed to retrieve origin verify secret from SSM"

RENDERED_PREFIX = os.environ["RENDERED_NOTEBOOKS_S3_PREFIX"]


def _error(status, msg):
    return {
        "statusCode": status,
        "headers": {**HEADERS, "Content-Type": "application/json"},
        "body": json.dumps({"error": msg}),
    }


def _html_response(html):
    return {
        "statusCode": 200,
        "headers": {**HEADERS, "Content-Type": "text/html"},
        "body": html,
    }


def _render_and_cache(s3, bucket, source_s3_key, rendered_s3_key):
    obj = s3.get_object(Bucket=bucket, Key=source_s3_key)
    nb = nbformat.reads(obj["Body"].read().decode(), as_version=4)
    exporter = HTMLExporter()
    html, _ = exporter.from_notebook_node(nb)
    s3.put_object(
        Bucket=bucket, Key=rendered_s3_key, Body=html.encode(), ContentType="text/html"
    )
    return html


def _get_cached_html(s3, bucket, rendered_s3_key):
    obj = s3.get_object(Bucket=bucket, Key=rendered_s3_key)
    return obj["Body"].read().decode()


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return _error(403, "Forbidden")

    params = event.get("queryStringParameters", {}) or {}
    notebook_id = params.get("id", "")
    s3_key = params.get("s3_key", "")
    execution_id = params.get("execution_id", "")

    s3 = boto3.client("s3")
    dynamodb = boto3.resource("dynamodb")
    bucket = os.environ["NOTEBOOKS_BUCKET"]

    logger.info(
        "Rendering: notebook_id=%s, execution_id=%s",
        notebook_id or "N/A",
        execution_id or "N/A",
    )

    if notebook_id:
        table = dynamodb.Table(os.environ["NOTEBOOKS_TABLE"])
        item = table.get_item(Key={"id": notebook_id}).get("Item")
        if not item:
            return _error(404, "Notebook not found")

        rendered_s3_key = item.get("rendered_s3_key", "")
        if rendered_s3_key:
            return _html_response(_get_cached_html(s3, bucket, rendered_s3_key))

        rendered_s3_key = f"{RENDERED_PREFIX}{notebook_id}.html"
        html = _render_and_cache(s3, bucket, item["s3_key"], rendered_s3_key)
        table.update_item(
            Key={"id": notebook_id},
            UpdateExpression="SET rendered_s3_key = :k",
            ExpressionAttributeValues={":k": rendered_s3_key},
        )
        return _html_response(html)

    elif execution_id:
        table = dynamodb.Table(os.environ["EXECUTIONS_TABLE"])
        item = table.get_item(Key={"id": execution_id}).get("Item")
        if not item:
            return _error(404, "Execution not found")

        rendered_s3_key = item.get("rendered_s3_key", "")
        if rendered_s3_key:
            return _html_response(_get_cached_html(s3, bucket, rendered_s3_key))

        source_key = item.get("output_s3_key", "")
        if not source_key:
            return _error(400, "No output available for this execution")

        rendered_s3_key = f"{RENDERED_PREFIX}exec_{execution_id}.html"
        html = _render_and_cache(s3, bucket, source_key, rendered_s3_key)
        table.update_item(
            Key={"id": execution_id},
            UpdateExpression="SET rendered_s3_key = :k",
            ExpressionAttributeValues={":k": rendered_s3_key},
        )
        return _html_response(html)

    else:
        return _error(400, "Missing id or execution_id")
