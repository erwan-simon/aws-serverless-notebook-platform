import json
import os

import boto3

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

    service_name = event["pathParameters"]["service_name"]
    cluster_name = os.environ["ECS_CLUSTER_NAME"]
    environment_name = os.environ["ENVIRONMENT_NAME"]

    if not service_name.startswith(f"{environment_name}_"):
        return {
            "statusCode": 403,
            "headers": HEADERS,
            "body": json.dumps({"error": "Invalid service name"}),
        }

    ecs = boto3.client("ecs")

    ecs.update_service(
        cluster=cluster_name, service=service_name, desiredCount=0
    )
    ecs.delete_service(
        cluster=cluster_name, service=service_name, force=True
    )

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"status": "stopped"}),
    }
