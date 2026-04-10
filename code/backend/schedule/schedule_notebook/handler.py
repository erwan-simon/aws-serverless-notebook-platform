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

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    owner_id = claims.get("sub", "")
    owner_email = claims.get("email", "")
    if not owner_id:
        return {"statusCode": 401, "headers": HEADERS, "body": json.dumps({"error": "Missing user identity"})}

    notebook_id = event.get("pathParameters", {}).get("id", "")
    if not notebook_id:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Missing notebook id"})}

    body = json.loads(event["body"])
    cron_expression = body.get("cron_expression", "")
    iam_role_arn = body.get("iam_role_arn", "")
    ecr_image_uri = body.get("ecr_image_uri", "")
    vcpu = body.get("vcpu")
    memory = body.get("memory")

    if not cron_expression or not iam_role_arn or not ecr_image_uri:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Missing cron_expression, iam_role_arn, or ecr_image_uri"})}

    # Verify notebook exists
    dynamodb = boto3.resource("dynamodb")
    notebooks_table = dynamodb.Table(os.environ["NOTEBOOKS_TABLE"])
    notebook = notebooks_table.get_item(Key={"id": notebook_id}).get("Item")
    if not notebook:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Notebook not found"})}

    environment_name = os.environ["ENVIRONMENT_NAME"]
    scheduler_role_arn = os.environ["SCHEDULER_ROLE_ARN"]
    run_notebook_lambda_arn = os.environ["RUN_NOTEBOOK_LAMBDA_ARN"]

    schedule_name = f"{environment_name}_nb_{notebook_id[:8]}"
    logger.info("Scheduling notebook: id=%s, cron=%s, image=%s", notebook_id, cron_expression, ecr_image_uri)

    scheduler = boto3.client("scheduler")
    try:
        scheduler.create_schedule(
            Name=schedule_name,
            ScheduleExpression=cron_expression,
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            Target={
                "Arn": run_notebook_lambda_arn,
                "RoleArn": scheduler_role_arn,
                "Input": json.dumps({
                    k: v for k, v in {
                        "source": "scheduler",
                        "notebook_id": notebook_id,
                        "iam_role_arn": iam_role_arn,
                        "ecr_image_uri": ecr_image_uri,
                        "owner_id": owner_id,
                        "owner_email": owner_email,
                        "vcpu": vcpu,
                        "memory": memory,
                    }.items() if v is not None
                }),
            },
            ActionAfterCompletion="NONE",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ValidationException":
            return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": e.response["Error"]["Message"]})}
        raise

    notebooks_table.update_item(
        Key={"id": notebook_id},
        UpdateExpression="SET schedule_cron = :cron, schedule_role_arn = :role, schedule_image_uri = :image, schedule_name = :name, schedule_vcpu = :vcpu, schedule_memory = :memory",
        ExpressionAttributeValues={
            ":cron": cron_expression,
            ":role": iam_role_arn,
            ":image": ecr_image_uri,
            ":name": schedule_name,
            ":vcpu": vcpu if vcpu is not None else 0,
            ":memory": memory if memory is not None else 0,
        },
    )

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"message": "Schedule created", "schedule_name": schedule_name}),
    }
