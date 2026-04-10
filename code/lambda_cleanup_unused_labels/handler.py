import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _scan_all(table, **kwargs):
    items = []
    response = table.scan(**kwargs)
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"], **kwargs)
        items.extend(response.get("Items", []))
    return items


def handler(event, context):
    dynamodb = boto3.resource("dynamodb")
    notebooks_table = dynamodb.Table(os.environ["NOTEBOOKS_TABLE"])
    configurations_table = dynamodb.Table(os.environ["CONFIGURATIONS_TABLE"])
    labels_table = dynamodb.Table(os.environ["LABELS_TABLE"])

    used = set()
    for item in _scan_all(notebooks_table, ProjectionExpression="#l", ExpressionAttributeNames={"#l": "labels"}):
        used.update(item.get("labels", []) or [])
    for item in _scan_all(configurations_table, ProjectionExpression="#l", ExpressionAttributeNames={"#l": "labels"}):
        used.update(item.get("labels", []) or [])

    existing = [item["name"] for item in _scan_all(labels_table)]
    unused = [name for name in existing if name not in used]

    logger.info("Labels: %d used, %d existing, %d unused", len(used), len(existing), len(unused))

    for name in unused:
        labels_table.delete_item(Key={"name": name})
        logger.info("Deleted unused label: %s", name)

    return {"deleted": len(unused), "remaining": len(existing) - len(unused)}
