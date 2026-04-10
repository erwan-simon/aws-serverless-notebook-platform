import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import boto3

LABEL_REGEX = re.compile(r"^[a-z\u00e0-\u00f6\u00f8-\u00ff0-9\-]+$")

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


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {"statusCode": 403, "headers": HEADERS, "body": json.dumps({"error": "Forbidden"})}

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    created_by = claims.get("email", "")

    body = json.loads(event.get("body", "{}"))
    logger.info("Adding configuration: name=%s, image=%s, role=%s", body.get("name"), body.get("ecr_image_uri"), body.get("iam_role_arn"))
    name = body.get("name", "").strip()
    ecr_image_uri = body.get("ecr_image_uri", "").strip()
    iam_role_arn = body.get("iam_role_arn", "").strip()
    description = body.get("description", "").strip()
    vcpu = body.get("vcpu")
    memory = body.get("memory")

    if not name:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "name is required"})}
    if not ecr_image_uri:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "ecr_image_uri is required"})}
    if not iam_role_arn:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "iam_role_arn is required"})}
    if not vcpu or not memory:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "vcpu and memory are required"})}
    vcpu = int(vcpu)
    memory = int(memory)

    lambda_client = boto3.client("lambda")
    run_fn = os.environ["RUN_NOTEBOOK_FUNCTION_NAME"]
    technical_owner = os.environ["TECHNICAL_OWNER_ID"]
    base_payload = {
        "source": "scheduler",
        "iam_role_arn": iam_role_arn,
        "ecr_image_uri": ecr_image_uri,
        "owner_id": technical_owner,
        "owner_email": technical_owner,
        "vcpu": vcpu,
        "memory": memory,
    }

    def invoke_validation(extra):
        payload = {**base_payload, **extra}
        resp = lambda_client.invoke(
            FunctionName=run_fn,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )
        result = json.loads(resp["Payload"].read())
        result_body = json.loads(result.get("body", "{}"))
        return result_body.get("execution_id")

    # Validation 1: run hello_world notebook with papermill
    notebook_exec_id = invoke_validation({"notebook_id": os.environ["VALIDATION_NOTEBOOK_ID"]})
    if not notebook_exec_id:
        return {"statusCode": 500, "headers": HEADERS, "body": json.dumps({"error": "Notebook validation launch failed"})}

    # Validation 2: start Jupyter and check health endpoint
    session_command = (
        "jupyter lab --ip=0.0.0.0 --port=8888 --allow-root --no-browser --ServerApp.token='' & "
        "for i in $(seq 1 30); do sleep 2; curl -sf http://localhost:8888/api && exit 0; done; exit 1"
    )
    session_exec_id = invoke_validation({"command": session_command})
    if not session_exec_id:
        return {"statusCode": 500, "headers": HEADERS, "body": json.dumps({"error": "Session validation launch failed"})}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["CONFIGURATIONS_TABLE"])

    labels = body.get("labels", [])
    if labels:
        for label in labels:
            if not isinstance(label, str) or not LABEL_REGEX.match(label):
                return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": f"Invalid label: {label}"})}
        labels = list(set(labels))

    item = {
        "id": str(uuid.uuid4()),
        "name": name,
        "ecr_image_uri": ecr_image_uri,
        "iam_role_arn": iam_role_arn,
        "vcpu": vcpu,
        "memory": memory,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
        "validation_notebook_execution_id": notebook_exec_id,
        "validation_session_execution_id": session_exec_id,
    }
    if description:
        item["description"] = description
    if labels:
        item["labels"] = labels

    table.put_item(Item=item)
    logger.info("Configuration created: id=%s, name=%s, labels=%s, notebook_validation=%s, session_validation=%s",
                item["id"], name, labels or [], notebook_exec_id, session_exec_id)

    if labels:
        labels_table = dynamodb.Table(os.environ["LABELS_TABLE"])
        for label in labels:
            labels_table.put_item(Item={"name": label})

    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps(item)}
