import json
import logging
import os
import re
import secrets


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


def _make_service_name(environment_name, user_identity):
    slug = re.sub(r"[^a-zA-Z0-9-]", "-", user_identity)[:50]
    return f"{environment_name}_{slug}"


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


def handler(event, context):
    if event.get("headers", {}).get("x-origin-verify") != _origin_secret:
        return {"statusCode": 403, "headers": HEADERS, "body": json.dumps({"error": "Forbidden"})}

    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    user_sub = claims.get("sub", "")
    if not user_sub:
        return {"statusCode": 401, "headers": HEADERS, "body": json.dumps({"error": "Missing user identity"})}

    body = json.loads(event["body"])
    iam_role_arn = body["iam_role_arn"]
    ecr_image_uri = body["ecr_image_uri"]

    environment_name = os.environ["ENVIRONMENT_NAME"]
    cluster_name = os.environ["ECS_CLUSTER_NAME"]
    security_group_id = os.environ["SECURITY_GROUP_ID"]
    execution_role_arn = os.environ["ECS_EXECUTION_ROLE_ARN"]
    subnet_ids = os.environ["SUBNET_IDS"].split(",")
    efs_file_system_id = os.environ["EFS_FILE_SYSTEM_ID"]
    efs_shared_access_point_id = os.environ["EFS_SHARED_ACCESS_POINT_ID"]
    resource_tags = json.loads(os.environ["RESOURCE_TAGS"])
    idle_timeout_seconds = int(os.environ["SESSION_IDLE_TIMEOUT_MINUTES"]) * 60

    default_vcpu = int(os.environ["TASK_DEFAULT_VCPU"])
    default_memory = int(os.environ["TASK_DEFAULT_MEMORY"])
    max_vcpu = int(os.environ["TASK_MAX_VCPU"])
    max_memory = int(os.environ["TASK_MAX_MEMORY"])

    vcpu = int(body.get("vcpu", default_vcpu))
    memory = int(body.get("memory", default_memory))
    if vcpu > max_vcpu or memory > max_memory or vcpu < 256 or memory < 512:
        return {
            "statusCode": 400,
            "headers": HEADERS,
            "body": json.dumps({"error": f"Invalid vcpu/memory. vcpu: 256-{max_vcpu}, memory: 512-{max_memory}"}),
        }

    alb_listener_arn = os.environ["ALB_LISTENER_ARN"]
    alb_dns_name = os.environ["ALB_DNS_NAME"]
    vpc_id = os.environ["VPC_ID"]

    jupyter_token = secrets.token_hex(32)
    service_name = _make_service_name(environment_name, user_sub)
    base_url = f"/s/{service_name}/"

    # Find or create per-user EFS access point
    efs_client = boto3.client("efs")
    access_point_id = None
    paginator = efs_client.get_paginator("describe_access_points")
    for page in paginator.paginate(FileSystemId=efs_file_system_id):
        for ap in page["AccessPoints"]:
            ap_tags = {t["Key"]: t["Value"] for t in ap.get("Tags", [])}
            if ap_tags.get("UserSub") == user_sub:
                access_point_id = ap["AccessPointId"]
                break
        if access_point_id:
            break

    if not access_point_id:
        ap_resp = efs_client.create_access_point(
            FileSystemId=efs_file_system_id,
            PosixUser={"Uid": 0, "Gid": 0},
            RootDirectory={
                "Path": f"/{user_sub}",
                "CreationInfo": {"OwnerUid": 0, "OwnerGid": 0, "Permissions": "700"},
            },
            Tags=[
                {"Key": "UserSub", "Value": user_sub},
                {"Key": "Name", "Value": f"{environment_name}_{user_sub[:8]}"},
            ],
        )
        access_point_id = ap_resp["AccessPointId"]

    ecs = boto3.client("ecs")
    elbv2 = boto3.client("elbv2")

    existing = ecs.describe_services(cluster=cluster_name, services=[service_name])
    for svc in existing.get("services", []):
        if svc["status"] == "ACTIVE":
            return {
                "statusCode": 200,
                "headers": HEADERS,
                "body": json.dumps({"service_name": service_name}),
            }
        if svc["status"] == "DRAINING":
            logger.info("Service %s is DRAINING, waiting for it to become inactive", service_name)
            waiter = ecs.get_waiter("services_inactive")
            try:
                waiter.wait(
                    cluster=cluster_name,
                    services=[service_name],
                    WaiterConfig={"Delay": 5, "MaxAttempts": 6},
                )
            except Exception:
                return {
                    "statusCode": 409,
                    "headers": HEADERS,
                    "body": json.dumps({"error": "Your previous session is still shutting down. Please try again in a few seconds."}),
                }
            # Clean up orphaned ALB resources from the previous service
            _cleanup_alb_resources(elbv2, alb_listener_arn, service_name)

    tags = [{"key": k, "value": v} for k, v in resource_tags.items()]

    task_def = ecs.register_task_definition(
        family=service_name,
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
                "name": service_name,
                "image": ecr_image_uri,
                "essential": True,
                "entryPoint": ["/bin/bash", "-c"],
                "command": [
                    f"exec jupyter lab --ip=0.0.0.0 --port=8888 --allow-root"
                    f" --ServerApp.token=\"${{JUPYTER_TOKEN}}\" --ServerApp.password=''"
                    f" --ServerApp.notebook_dir=/home/jupyter"
                    f" --ServerApp.base_url={base_url}"
                    f" --MappingKernelManager.cull_idle_timeout={idle_timeout_seconds}"
                    f" --MappingKernelManager.cull_connected=True"
                    f" --ServerApp.shutdown_no_activity_timeout={idle_timeout_seconds}"
                ],
                "portMappings": [
                    {
                        "containerPort": 8888,
                        "hostPort": 8888,
                        "protocol": "tcp",
                    }
                ],
                "mountPoints": [
                    {
                        "containerPath": "/home/jupyter",
                        "sourceVolume": "efs-user",
                    },
                    {
                        "containerPath": "/shared",
                        "sourceVolume": "efs-shared",
                    },
                ],
                "environment": [
                    {
                        "name": "AWS_REGION",
                        "value": os.environ.get("AWS_REGION", "eu-west-1"),
                    },
                    {
                        "name": "JUPYTER_TOKEN",
                        "value": jupyter_token,
                    },
                    {
                        "name": "HOME",
                        "value": "/home/jupyter",
                    },
                ],
                "healthCheck": {
                    "command": ["CMD-SHELL", "/etc/jupyter/docker_healthcheck.py >> /proc/1/fd/1 2>&1 || exit 1"],
                    "interval": 60,
                    "timeout": 5,
                    "retries": 5,
                    "startPeriod": 180,
                },
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": f"/ecs/{service_name}",
                        "awslogs-region": os.environ.get("AWS_REGION", "eu-west-1"),
                        "awslogs-stream-prefix": "ecs",
                        "awslogs-create-group": "true",
                    },
                },
            }
        ],
        volumes=[
            {
                "name": "efs-user",
                "efsVolumeConfiguration": {
                    "fileSystemId": efs_file_system_id,
                    "transitEncryption": "ENABLED",
                    "authorizationConfig": {
                        "accessPointId": access_point_id,
                    },
                },
            },
            {
                "name": "efs-shared",
                "efsVolumeConfiguration": {
                    "fileSystemId": efs_file_system_id,
                    "transitEncryption": "ENABLED",
                    "authorizationConfig": {
                        "accessPointId": efs_shared_access_point_id,
                    },
                },
            },
        ],
        tags=tags,
    )

    # Create ALB target group for this session
    tg_name = service_name.replace("_", "-")[:32]
    tg_resp = elbv2.create_target_group(
        Name=tg_name,
        Protocol="HTTP",
        Port=8888,
        VpcId=vpc_id,
        TargetType="ip",
        HealthCheckProtocol="HTTP",
        HealthCheckPath=f"{base_url}api",
        HealthCheckIntervalSeconds=30,
        HealthyThresholdCount=2,
        UnhealthyThresholdCount=3,
        Tags=[{"Key": "SessionService", "Value": service_name}] + [{"Key": item["key"], "Value": item["value"]} for item in tags],
    )
    target_group_arn = tg_resp["TargetGroups"][0]["TargetGroupArn"]

    # Create ALB listener rule for path-based routing
    # Use a hash of the service name as priority (1-50000)
    priority = (hash(service_name) % 49999) + 1
    elbv2.create_rule(
        ListenerArn=alb_listener_arn,
        Priority=priority,
        Conditions=[
            {
                "Field": "path-pattern",
                "Values": [f"/s/{service_name}/*", f"/s/{service_name}"],
            }
        ],
        Actions=[
            {
                "Type": "forward",
                "TargetGroupArn": target_group_arn,
            }
        ],
        Tags=[{"Key": "SessionService", "Value": service_name}] + [{"Key": item["key"], "Value": item["value"]} for item in tags],
    )

    ecs.create_service(
        cluster=cluster_name,
        serviceName=service_name,
        taskDefinition=task_def["taskDefinition"]["taskDefinitionArn"],
        desiredCount=1,
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
        loadBalancers=[
            {
                "targetGroupArn": target_group_arn,
                "containerName": service_name,
                "containerPort": 8888,
            }
        ],
        tags=tags,
    )

    return {
        "statusCode": 200,
        "headers": HEADERS,
        "body": json.dumps({"service_name": service_name, "jupyter_token": jupyter_token}),
    }
