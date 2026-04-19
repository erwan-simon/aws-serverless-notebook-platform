import json
import logging
import os
from decimal import Decimal

import boto3

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

JUPYTER_SESSION_VALIDATION_COMMAND = (
    "jupyter lab --ip=0.0.0.0 --port=8888 --allow-root --no-browser --ServerApp.token='' & "
    "for i in $(seq 1 30); do sleep 2; curl -sf http://localhost:8888/api && exit 0; done; exit 1"
)
CODESERVER_SESSION_VALIDATION_COMMAND = (
    "code-server --auth none --bind-addr 0.0.0.0:8888 --disable-telemetry "
    "--disable-update-check & "
    "for i in $(seq 1 30); do sleep 2; curl -sf http://localhost:8888/healthz && exit 0; done; exit 1"
)

SESSION_VALIDATION_FIELDS = {
    "validation_jupyter_session_execution_id": JUPYTER_SESSION_VALIDATION_COMMAND,
    "validation_codeserver_session_execution_id": CODESERVER_SESSION_VALIDATION_COMMAND,
}


def _invoke_validation(lambda_client, run_fn, item, extra):
    technical_owner = os.environ["TECHNICAL_OWNER_ID"]
    payload = {
        "source": "scheduler",
        "iam_role_arn": item.get("iam_role_arn", ""),
        "ecr_image_uri": item.get("ecr_image_uri", ""),
        "owner_id": technical_owner,
        "owner_email": technical_owner,
        "vcpu": int(item.get("vcpu", 512)),
        "memory": int(item.get("memory", 1024)),
        **extra,
    }
    resp = lambda_client.invoke(
        FunctionName=run_fn,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )
    result = json.loads(resp["Payload"].read())
    result_body = json.loads(result.get("body", "{}"))
    return result_body.get("execution_id")


def _seed_managed_configurations(table):
    managed_configs = json.loads(os.environ.get("MANAGED_CONFIGURATIONS", "[]"))
    for cfg in managed_configs:
        existing = table.get_item(Key={"id": cfg["id"]}).get("Item")
        if not existing:
            table.put_item(
                Item={
                    "id": cfg["id"],
                    "name": cfg["name"],
                    "ecr_image_uri": cfg["ecr_image_uri"],
                    "iam_role_arn": cfg["iam_role_arn"],
                    "vcpu": cfg["vcpu"],
                    "memory": cfg["memory"],
                    "managed_by": "terraform",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "created_by": "terraform",
                }
            )
        else:
            table.update_item(
                Key={"id": cfg["id"]},
                UpdateExpression="SET #name = :name, #ecr = :ecr, #role = :role, #vcpu = :vcpu, #mem = :mem",
                ExpressionAttributeNames={
                    "#name": "name",
                    "#ecr": "ecr_image_uri",
                    "#role": "iam_role_arn",
                    "#vcpu": "vcpu",
                    "#mem": "memory",
                },
                ExpressionAttributeValues={
                    ":name": cfg["name"],
                    ":ecr": cfg["ecr_image_uri"],
                    ":role": cfg["iam_role_arn"],
                    ":vcpu": cfg["vcpu"],
                    ":mem": cfg["memory"],
                },
            )


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {
            "statusCode": 403,
            "headers": HEADERS,
            "body": json.dumps({"error": "Forbidden"}),
        }

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["CONFIGURATIONS_TABLE"])
    executions_table = dynamodb.Table(os.environ["EXECUTIONS_TABLE"])

    _seed_managed_configurations(table)

    items = []
    response = table.scan()
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    # Resilience: drop rows missing indispensable fields, salvage rows missing default vcpu/memory
    REQUIRED_FIELDS = ("name", "ecr_image_uri", "iam_role_arn")
    SALVAGE_DEFAULTS = {"vcpu": 512, "memory": 1024}
    cleaned = []
    for item in items:
        missing = [f for f in REQUIRED_FIELDS if not item.get(f)]
        if missing:
            logger.warning(
                "Deleting malformed configuration row (missing %s): %s",
                missing,
                json.dumps(item, default=str),
            )
            table.delete_item(Key={"id": item["id"]})
            continue
        for field, default in SALVAGE_DEFAULTS.items():
            if not item.get(field):
                logger.warning(
                    "Salvaging configuration row %s with default %s=%s: %s",
                    item["id"],
                    field,
                    default,
                    json.dumps(item, default=str),
                )
                item[field] = default
        cleaned.append(item)
    items = cleaned

    # Launch missing validations
    lambda_client = boto3.client("lambda")
    run_fn = os.environ["RUN_NOTEBOOK_FUNCTION_NAME"]
    validation_notebook_id = os.environ["VALIDATION_NOTEBOOK_ID"]

    for item in items:
        updates = {}
        if not item.get("validation_notebook_execution_id"):
            try:
                eid = _invoke_validation(
                    lambda_client, run_fn, item, {"notebook_id": validation_notebook_id}
                )
                if eid:
                    item["validation_notebook_execution_id"] = eid
                    updates["validation_notebook_execution_id"] = eid
            except Exception as e:
                logger.warning(
                    "Failed to launch notebook validation for %s: %s", item.get("id"), e
                )

        for field, command in SESSION_VALIDATION_FIELDS.items():
            if not item.get(field):
                try:
                    eid = _invoke_validation(
                        lambda_client, run_fn, item, {"command": command}
                    )
                    if eid:
                        item[field] = eid
                        updates[field] = eid
                except Exception as e:
                    logger.warning(
                        "Failed to launch %s for %s: %s", field, item.get("id"), e
                    )

        if updates:
            table.update_item(
                Key={"id": item["id"]},
                UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in updates),
                ExpressionAttributeNames={f"#{k}": k for k in updates},
                ExpressionAttributeValues={f":{k}": v for k, v in updates.items()},
            )

    # Resolve validation statuses from executions table
    status_fields = (
        "validation_notebook_execution_id",
        *SESSION_VALIDATION_FIELDS.keys(),
    )
    exec_ids = set()
    for item in items:
        for key in status_fields:
            eid = item.get(key)
            if eid:
                exec_ids.add(eid)

    exec_statuses = {}
    if exec_ids:
        keys = [{"id": eid} for eid in exec_ids]
        resp = dynamodb.batch_get_item(
            RequestItems={
                executions_table.name: {
                    "Keys": keys,
                    "ProjectionExpression": "id, #s",
                    "ExpressionAttributeNames": {"#s": "status"},
                }
            }
        )
        for ex in resp.get("Responses", {}).get(executions_table.name, []):
            exec_statuses[ex["id"]] = ex.get("status", "PENDING")

    for item in items:
        for key in status_fields:
            eid = item.get(key)
            if eid:
                status_key = key.replace("_execution_id", "_status")
                item[status_key] = exec_statuses.get(eid, "PENDING")

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    logger.info("Returning %d configurations", len(items))
    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps(
            items, default=lambda o: int(o) if isinstance(o, Decimal) else str(o)
        ),
    }
