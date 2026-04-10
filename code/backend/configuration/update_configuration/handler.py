import json
import logging
import os
import re

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

LABEL_REGEX = re.compile(os.environ["LABEL_REGEX"])
SECURITY_TAG_KEY = os.environ["SECURITY_TAG_KEY"]
SECURITY_TAG_VALUE = os.environ["SECURITY_TAG_VALUE"]

ECR_IMAGE_URI_REGEX = re.compile(
    r"^(?P<account>\d+)\.dkr\.ecr\.(?P<region>[a-z0-9-]+)\.amazonaws\.com/(?P<repo>[^:@]+)(?:[:@].+)?$"
)
IAM_ROLE_ARN_REGEX = re.compile(r"^arn:aws:iam::\d+:role/(?P<name>.+)$")

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


class TagValidationError(Exception):
    pass


def _validate_role_tag(iam_role_arn: str) -> None:
    match = IAM_ROLE_ARN_REGEX.match(iam_role_arn)
    if not match:
        raise TagValidationError(f"Invalid IAM role ARN: {iam_role_arn}")
    role_name = match.group("name")
    iam = boto3.client("iam")
    try:
        resp = iam.get_role(RoleName=role_name)
    except iam.exceptions.NoSuchEntityException:
        raise TagValidationError(f"IAM role {role_name} does not exist")
    tags = {t["Key"]: t["Value"] for t in resp["Role"].get("Tags", [])}
    if tags.get(SECURITY_TAG_KEY) != SECURITY_TAG_VALUE:
        raise TagValidationError(
            f"IAM role {role_name} is not tagged with {SECURITY_TAG_KEY}={SECURITY_TAG_VALUE}"
        )


def _validate_image_tag(ecr_image_uri: str) -> None:
    match = ECR_IMAGE_URI_REGEX.match(ecr_image_uri)
    if not match:
        raise TagValidationError(f"Invalid ECR image URI: {ecr_image_uri}")
    account = match.group("account")
    region = match.group("region")
    repo = match.group("repo")
    ecr = boto3.client("ecr", region_name=region)
    repo_arn = f"arn:aws:ecr:{region}:{account}:repository/{repo}"
    try:
        resp = ecr.list_tags_for_resource(resourceArn=repo_arn)
    except ecr.exceptions.RepositoryNotFoundException:
        raise TagValidationError(f"ECR repository {repo} does not exist")
    tags = {t["Key"]: t["Value"] for t in resp.get("tags", [])}
    if tags.get(SECURITY_TAG_KEY) != SECURITY_TAG_VALUE:
        raise TagValidationError(
            f"ECR repository {repo} is not tagged with {SECURITY_TAG_KEY}={SECURITY_TAG_VALUE}"
        )


_ssm = boto3.client("ssm")
_origin_secret = _ssm.get_parameter(
    Name=os.environ["ORIGIN_VERIFY_SECRET_SSM_NAME"], WithDecryption=True
)["Parameter"]["Value"]
assert _origin_secret, "Failed to retrieve origin verify secret from SSM"

ALLOWED_FIELDS = {
    "name",
    "ecr_image_uri",
    "iam_role_arn",
    "vcpu",
    "memory",
    "description",
    "labels",
}


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {
            "statusCode": 403,
            "headers": HEADERS,
            "body": json.dumps({"error": "Forbidden"}),
        }

    config_id = event.get("pathParameters", {}).get("id", "")
    if not config_id:
        return {
            "statusCode": 400,
            "headers": HEADERS,
            "body": json.dumps({"error": "Missing configuration id"}),
        }

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["CONFIGURATIONS_TABLE"])

    item = table.get_item(Key={"id": config_id}).get("Item")
    if not item:
        return {
            "statusCode": 404,
            "headers": HEADERS,
            "body": json.dumps({"error": "Configuration not found"}),
        }

    if item.get("managed_by") == "terraform":
        return {
            "statusCode": 403,
            "headers": HEADERS,
            "body": json.dumps(
                {"error": "Cannot update Terraform-managed configuration"}
            ),
        }

    body = json.loads(event.get("body", "{}") or "{}")
    logger.info(
        "Updating configuration: id=%s, body keys=%s", config_id, list(body.keys())
    )
    updates = {}
    for field in ALLOWED_FIELDS:
        if field in body:
            val = body[field]
            if field in ("vcpu", "memory"):
                val = int(val)
            elif field == "labels":
                if not isinstance(val, list):
                    return {
                        "statusCode": 400,
                        "headers": HEADERS,
                        "body": json.dumps({"error": "labels must be a list"}),
                    }
                for label in val:
                    if not isinstance(label, str) or not LABEL_REGEX.match(label):
                        return {
                            "statusCode": 400,
                            "headers": HEADERS,
                            "body": json.dumps({"error": f"Invalid label: {label}"}),
                        }
                val = list(set(val))
            updates[field] = val

    logger.info("Fields to update: %s", list(updates.keys()))

    try:
        if "iam_role_arn" in updates:
            _validate_role_tag(updates["iam_role_arn"])
        if "ecr_image_uri" in updates:
            _validate_image_tag(updates["ecr_image_uri"])
    except TagValidationError as e:
        logger.warning("Tag validation failed: %s", e)
        return {
            "statusCode": 400,
            "headers": HEADERS,
            "body": json.dumps({"error": str(e)}),
        }

    # Clear validation IDs only if infra-related fields actually changed
    infra_changed = any(
        updates.get(f) is not None and updates[f] != item.get(f)
        for f in {"ecr_image_uri", "iam_role_arn", "vcpu", "memory"}
    )
    if infra_changed:
        logger.info("Infra fields changed, clearing validation IDs for re-validation")
        updates["validation_notebook_execution_id"] = None
        updates["validation_session_execution_id"] = None
    else:
        logger.info("No infra fields changed, keeping existing validations")

    expr_set = []
    expr_remove = []
    attr_names = {}
    attr_values = {}
    for k, v in updates.items():
        attr_names[f"#{k}"] = k
        if v is None:
            expr_remove.append(f"#{k}")
        else:
            expr_set.append(f"#{k} = :{k}")
            attr_values[f":{k}"] = v

    expression = ""
    if expr_set:
        expression += "SET " + ", ".join(expr_set)
    if expr_remove:
        expression += " REMOVE " + ", ".join(expr_remove)

    table.update_item(
        Key={"id": config_id},
        UpdateExpression=expression,
        ExpressionAttributeNames=attr_names,
        **({"ExpressionAttributeValues": attr_values} if attr_values else {}),
    )

    logger.info("Configuration updated: id=%s", config_id)

    # Sync new labels to centralized labels table
    if "labels" in updates and updates["labels"]:
        dynamodb_res = boto3.resource("dynamodb")
        labels_table = dynamodb_res.Table(os.environ["LABELS_TABLE"])
        for label in updates["labels"]:
            labels_table.put_item(Item={"name": label})

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"message": "Configuration updated"}),
    }
