import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


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
    detail = event.get("detail", {})
    task_arn = detail.get("taskArn", "")
    last_status = detail.get("lastStatus", "")

    if last_status != "STOPPED":
        logger.warning(
            "Unexpected lastStatus '%s' for task %s (expected STOPPED)",
            last_status,
            task_arn,
        )
        return

    # Check container exit code — only cleanup on clean shutdown (exit code 0)
    containers = detail.get("containers", [])
    if not containers:
        logger.info("No containers in event for task %s, skipping", task_arn)
        return

    exit_code = containers[0].get("exitCode")
    if exit_code != 0:
        logger.info(
            "Task %s exited with code %s (not 0), skipping cleanup", task_arn, exit_code
        )
        return

    # Extract service name from the task group: "service:<service_name>"
    group = detail.get("group", "")
    if not group.startswith("service:"):
        logger.info("Task %s group is not a service (%s), skipping", task_arn, group)
        return

    service_name = group[len("service:") :]
    environment_name = os.environ["ENVIRONMENT_NAME"]

    if not service_name.startswith(f"{environment_name}_"):
        logger.info("Service %s does not match environment, skipping", service_name)
        return

    cluster_name = os.environ["ECS_CLUSTER_NAME"]
    alb_listener_arn = os.environ["ALB_LISTENER_ARN"]
    ecs = boto3.client("ecs")
    elbv2 = boto3.client("elbv2")

    logger.info(
        "Cleaning up idle session service %s (task %s exited cleanly)",
        service_name,
        task_arn,
    )

    try:
        ecs.delete_service(cluster=cluster_name, service=service_name, force=True)
    except ecs.exceptions.ServiceNotActiveException:
        logger.info("Service %s already inactive, skipping delete", service_name)
    except ecs.exceptions.ServiceNotFoundException:
        logger.info("Service %s already gone, skipping delete", service_name)

    _cleanup_alb_resources(elbv2, alb_listener_arn, service_name)

    logger.info("Service %s deleted and ALB resources cleaned up", service_name)
