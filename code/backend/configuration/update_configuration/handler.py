import json
import logging
import os
import re

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

LABEL_REGEX = re.compile(r"^[a-z\u00e0-\u00f6\u00f8-\u00ff0-9\-]+$")

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

_ssm = boto3.client("ssm")
_origin_secret = _ssm.get_parameter(
    Name=os.environ["ORIGIN_VERIFY_SECRET_SSM_NAME"], WithDecryption=True
)["Parameter"]["Value"]
assert _origin_secret, "Failed to retrieve origin verify secret from SSM"

ALLOWED_FIELDS = {"name", "ecr_image_uri", "iam_role_arn", "vcpu", "memory", "description", "labels"}


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {"statusCode": 403, "headers": HEADERS, "body": json.dumps({"error": "Forbidden"})}

    config_id = event.get("pathParameters", {}).get("id", "")
    if not config_id:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Missing configuration id"})}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["CONFIGURATIONS_TABLE"])

    item = table.get_item(Key={"id": config_id}).get("Item")
    if not item:
        return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Configuration not found"})}

    if item.get("managed_by") == "terraform":
        return {"statusCode": 403, "headers": HEADERS, "body": json.dumps({"error": "Cannot update Terraform-managed configuration"})}

    body = json.loads(event.get("body", "{}") or "{}")
    logger.info("Updating configuration: id=%s, body keys=%s", config_id, list(body.keys()))
    updates = {}
    for field in ALLOWED_FIELDS:
        if field in body:
            val = body[field]
            if field in ("vcpu", "memory"):
                val = int(val)
            elif field == "labels":
                if not isinstance(val, list):
                    return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "labels must be a list"})}
                for label in val:
                    if not isinstance(label, str) or not LABEL_REGEX.match(label):
                        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": f"Invalid label: {label}"})}
                val = list(set(val))
            updates[field] = val

    logger.info("Fields to update: %s", list(updates.keys()))

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

    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps({"message": "Configuration updated"})}
