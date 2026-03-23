import json
import logging
import os

import boto3

logger = logging.getLogger()

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
    table = dynamodb.Table(os.environ["NOTEBOOKS_TABLE"])
    bucket = os.environ["NOTEBOOKS_BUCKET"]
    s3 = boto3.client("s3")

    # Get item first to know the S3 key
    item = table.get_item(Key={"id": notebook_id}).get("Item")
    if not item:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Notebook not found"})}

    s3_key = item["s3_key"]

    # Step 1: Delete from DynamoDB
    table.delete_item(Key={"id": notebook_id})

    # Step 2: Delete from S3 — rollback DynamoDB on failure
    try:
        s3.delete_object(Bucket=bucket, Key=s3_key)
    except Exception as e:
        logger.error("S3 delete failed, rolling back DynamoDB item %s: %s", notebook_id, e)
        try:
            table.put_item(Item=item)
        except Exception as rollback_err:
            logger.error("DynamoDB rollback also failed for %s: %s", notebook_id, rollback_err)
        return {"statusCode": 500, "headers": HEADERS, "body": json.dumps({"error": "Failed to delete notebook"})}

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"message": "Notebook deleted"}),
    }
