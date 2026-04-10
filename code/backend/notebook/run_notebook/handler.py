import json
import logging
import os
import uuid
from datetime import datetime, timezone

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
    # Dual invocation: EventBridge Scheduler or API Gateway
    default_vcpu = int(os.environ["TASK_DEFAULT_VCPU"])
    default_memory = int(os.environ["TASK_DEFAULT_MEMORY"])
    max_vcpu = int(os.environ["TASK_MAX_VCPU"])
    max_memory = int(os.environ["TASK_MAX_MEMORY"])

    custom_command = None

    if event.get("source") == "scheduler":
        notebook_id = event.get("notebook_id", "")
        iam_role_arn = event["iam_role_arn"]
        ecr_image_uri = event["ecr_image_uri"]
        owner_id = event["owner_id"]
        owner_email = event["owner_email"]
        vcpu = int(event.get("vcpu", default_vcpu))
        memory = int(event.get("memory", default_memory))
        trigger_type = "scheduled"
        custom_command = event.get("command")
    else:
        if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
            return {"statusCode": 403, "headers": HEADERS, "body": json.dumps({"error": "Forbidden"})}

        claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
        owner_id = claims.get("sub", "")
        owner_email = claims.get("email", "")
        if not owner_id:
            return {"statusCode": 401, "headers": HEADERS, "body": json.dumps({"error": "Missing user identity"})}

        body = json.loads(event["body"])
        notebook_id = body.get("notebook_id", "")
        iam_role_arn = body["iam_role_arn"]
        ecr_image_uri = body["ecr_image_uri"]
        vcpu = int(body.get("vcpu", default_vcpu))
        memory = int(body.get("memory", default_memory))
        trigger_type = "manual"

    if vcpu > max_vcpu or memory > max_memory or vcpu < 256 or memory < 512:
        return {
            "statusCode": 400,
            "headers": HEADERS,
            "body": json.dumps({"error": f"Invalid vcpu/memory. vcpu: 256-{max_vcpu}, memory: 512-{max_memory}"}),
        }

    if not notebook_id and not custom_command:
        return {"statusCode": 400, "headers": HEADERS, "body": json.dumps({"error": "Missing notebook_id or command"})}

    dynamodb = boto3.resource("dynamodb")
    notebook = None
    notebook_name = ""
    if notebook_id:
        notebooks_table = dynamodb.Table(os.environ["NOTEBOOKS_TABLE"])
        notebook = notebooks_table.get_item(Key={"id": notebook_id}).get("Item")
        if not notebook:
            return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Notebook not found"})}
        notebook_name = notebook.get("name", "")

    environment_name = os.environ["ENVIRONMENT_NAME"]
    cluster_name = os.environ["ECS_CLUSTER_NAME"]
    security_group_id = os.environ["SECURITY_GROUP_ID"]
    execution_role_arn = os.environ["ECS_EXECUTION_ROLE_ARN"]
    bucket = os.environ["NOTEBOOKS_BUCKET"]
    subnet_ids = os.environ["SUBNET_IDS"].split(",")
    resource_tags = json.loads(os.environ["RESOURCE_TAGS"])

    execution_id = str(uuid.uuid4())
    task_family = f"{environment_name}_exec_{execution_id[:8]}"
    logger.info("Running notebook: execution_id=%s, notebook_id=%s, image=%s, trigger=%s, vcpu=%d, memory=%d",
                execution_id, notebook_id or "N/A", ecr_image_uri, trigger_type, vcpu, memory)

    if custom_command:
        container_command = [custom_command]
        output_s3_key = ""
    else:
        input_s3_key = notebook["s3_key"]
        output_s3_key = f"notebook_executions/{notebook_id}/{execution_id}.ipynb"
        container_command = [
            f"aws s3 cp s3://{bucket}/{input_s3_key} /tmp/input.ipynb && "
            f"papermill /tmp/input.ipynb /tmp/output.ipynb --no-progress-bar && "
            f"aws s3 cp /tmp/output.ipynb s3://{bucket}/{output_s3_key}"
        ]

    tags = [{"key": k, "value": v} for k, v in resource_tags.items()]
    tags.append({"key": "execution_id", "value": execution_id})
    if notebook_id:
        tags.append({"key": "notebook_id", "value": notebook_id})

    ecs = boto3.client("ecs")

    task_def = ecs.register_task_definition(
        family=task_family,
        networkMode="awsvpc",
        requiresCompatibilities=["FARGATE"],
        cpu=str(vcpu),
        memory=str(memory),
        executionRoleArn=execution_role_arn,
        taskRoleArn=iam_role_arn,
        runtimePlatform={
            "operatingSystemFamily": "LINUX",
            "cpuArchitecture": "X86_64",
        },
        containerDefinitions=[
            {
                "name": task_family,
                "image": ecr_image_uri,
                "essential": True,
                "entryPoint": ["/bin/bash", "-c"],
                "command": container_command,
                "environment": [
                    {"name": "AWS_REGION", "value": os.environ.get("AWS_REGION", "eu-west-1")},
                ],
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": f"/ecs/{task_family}",
                        "awslogs-region": os.environ.get("AWS_REGION", "eu-west-1"),
                        "awslogs-stream-prefix": "ecs",
                        "awslogs-create-group": "true",
                    },
                },
            }
        ],
        tags=tags,
    )

    run_result = ecs.run_task(
        cluster=cluster_name,
        taskDefinition=task_def["taskDefinition"]["taskDefinitionArn"],
        launchType="FARGATE",
        enableECSManagedTags=True,
        propagateTags="TASK_DEFINITION",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnet_ids,
                "securityGroups": [security_group_id],
                "assignPublicIp": "ENABLED",
            }
        },
        tags=tags,
    )

    task_arn = run_result["tasks"][0]["taskArn"]
    logger.info("ECS task started: execution_id=%s, task_arn=%s", execution_id, task_arn)

    executions_table = dynamodb.Table(os.environ["EXECUTIONS_TABLE"])
    item = {
        "id": execution_id,
        "status": "PENDING",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "task_arn": task_arn,
        "owner_id": owner_id,
        "owner_email": owner_email,
        "trigger_type": trigger_type,
    }
    if notebook_id:
        item["notebook_id"] = notebook_id
        item["notebook_name"] = notebook_name
    if output_s3_key:
        item["output_s3_key"] = output_s3_key
    executions_table.put_item(Item=item)

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"execution_id": execution_id, "status": "PENDING"}),
    }
