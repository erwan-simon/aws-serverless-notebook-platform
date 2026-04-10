import json
import logging
import os

import boto3

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

    service_name = event["pathParameters"]["service_name"]
    cluster_name = os.environ["ECS_CLUSTER_NAME"]
    environment_name = os.environ["ENVIRONMENT_NAME"]

    logger.info("Stopping session: service=%s", service_name)

    if not service_name.startswith(f"{environment_name}_"):
        return {
            "statusCode": 403,
            "headers": HEADERS,
            "body": json.dumps({"error": "Invalid service name"}),
        }

    alb_listener_arn = os.environ["ALB_LISTENER_ARN"]

    ecs = boto3.client("ecs")
    elbv2 = boto3.client("elbv2")

    ecs.update_service(
        cluster=cluster_name, service=service_name, desiredCount=0
    )
    ecs.delete_service(
        cluster=cluster_name, service=service_name, force=True
    )

    # Cleanup ALB listener rule and target group for this session
    _cleanup_alb_resources(elbv2, alb_listener_arn, service_name)

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"status": "stopped"}),
    }


def _cleanup_alb_resources(elbv2, listener_arn, service_name):
    # Find and delete the listener rule matching this session
    rules = elbv2.describe_rules(ListenerArn=listener_arn)["Rules"]
    for rule in rules:
        if rule.get("IsDefault"):
            continue
        for condition in rule.get("Conditions", []):
            if condition.get("Field") == "path-pattern":
                values = condition.get("Values", [])
                if any(f"/s/{service_name}" in v for v in values):
                    elbv2.delete_rule(RuleArn=rule["RuleArn"])
                    break

    # Find and delete the target group for this session
    tg_name = service_name.replace("_", "-")[:32]
    try:
        tgs = elbv2.describe_target_groups(Names=[tg_name])["TargetGroups"]
        for tg in tgs:
            elbv2.delete_target_group(TargetGroupArn=tg["TargetGroupArn"])
    except elbv2.exceptions.TargetGroupNotFoundException:
        pass
