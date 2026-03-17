import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    detail = event.get("detail", {})
    task_arn = detail.get("taskArn", "")
    last_status = detail.get("lastStatus", "")

    if last_status != "STOPPED":
        logger.warning(
            "Unexpected lastStatus '%s' for task %s (expected STOPPED)", last_status, task_arn
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

    service_name = group[len("service:"):]
    environment_name = os.environ["ENVIRONMENT_NAME"]

    if not service_name.startswith(f"{environment_name}_"):
        logger.info("Service %s does not match environment, skipping", service_name)
        return

    cluster_name = os.environ["ECS_CLUSTER_NAME"]
    ecs = boto3.client("ecs")

    logger.info("Cleaning up idle session service %s (task %s exited cleanly)", service_name, task_arn)

    ecs.update_service(cluster=cluster_name, service=service_name, desiredCount=0)
    ecs.delete_service(cluster=cluster_name, service=service_name, force=True)

    logger.info("Service %s deleted", service_name)
