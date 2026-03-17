locals {
  cleanup_idle_session_function_name = "${local.environment_name}_cleanup_idle_session"
  cleanup_idle_session_code_path     = "${path.root}/../code/lambda_cleanup_idle_session/"
  cleanup_idle_session_rebuild_trigger = {
    task_code_hashes = jsonencode({
      for file_path in fileset(trimsuffix(local.cleanup_idle_session_code_path, "/"), "**") :
      file_path => filemd5("${trimsuffix(local.cleanup_idle_session_code_path, "/")}/${file_path}")
      if alltrue([
        for directory_pattern_to_ignore in [
          "__pycache__/", "login_error_message.txt"
        ] :
        !strcontains(file_path, directory_pattern_to_ignore)
      ])
    })
    dockerfile_hash = filemd5("${local.cleanup_idle_session_code_path}Dockerfile")
  }
  cleanup_idle_session_image_tag = sha1(jsonencode(local.cleanup_idle_session_rebuild_trigger))
}

module "cleanup_idle_session_image" {
  source                = "git::https://github.com/erwan-simon/terraform-module-build-image-and-push-to-ecr//iac/?ref=v1.0.1"
  ecr_name              = local.cleanup_idle_session_function_name
  code_path             = abspath(local.cleanup_idle_session_code_path)
  image_tag             = local.cleanup_idle_session_image_tag
  image_rebuild_trigger = jsonencode(local.cleanup_idle_session_rebuild_trigger)
  tags_map = {
    Appli          = var.project_name
    Component      = local.domain_name
    Env            = terraform.workspace
    git_repository = var.git_repository
  }
}

resource "time_sleep" "cleanup_idle_session_ecr" {
  depends_on      = [module.cleanup_idle_session_image]
  triggers        = local.cleanup_idle_session_rebuild_trigger
  create_duration = "30s"
}

resource "aws_lambda_function" "cleanup_idle_session" {
  function_name = local.cleanup_idle_session_function_name
  role          = aws_iam_role.cleanup_idle_session.arn
  package_type  = "Image"
  image_uri     = "${module.cleanup_idle_session_image.ecr_url}:${local.cleanup_idle_session_image_tag}"
  timeout       = 30
  memory_size   = 256

  environment {
    variables = {
      ENVIRONMENT_NAME = local.environment_name
      ECS_CLUSTER_NAME = aws_ecs_cluster.main.name
    }
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.cleanup_idle_session.name
  }
  depends_on = [time_sleep.cleanup_idle_session_ecr]
}

resource "aws_cloudwatch_log_group" "cleanup_idle_session" {
  name              = "${local.environment_name}/cleanup_idle_session"
  retention_in_days = 14
}

resource "aws_lambda_function_event_invoke_config" "cleanup_idle_session" {
  function_name                = aws_lambda_function.cleanup_idle_session.function_name
  maximum_event_age_in_seconds = 60
  maximum_retry_attempts       = 0
}

# IAM
resource "aws_iam_role" "cleanup_idle_session" {
  name = "${local.cleanup_idle_session_function_name}_lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "cleanup_idle_session" {
  name   = "${local.cleanup_idle_session_function_name}_policy"
  role   = aws_iam_role.cleanup_idle_session.id
  policy = data.aws_iam_policy_document.cleanup_idle_session_lambda.json
}

data "aws_iam_policy_document" "cleanup_idle_session_lambda" {
  statement {
    actions = ["ecs:UpdateService", "ecs:DeleteService"]
    resources = [
      "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:service/${aws_ecs_cluster.main.name}/${local.environment_name}_*",
    ]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.cleanup_idle_session.arn,
      "${aws_cloudwatch_log_group.cleanup_idle_session.arn}:*",
    ]
  }
}

# EventBridge rule — ECS task state changes for session services
resource "aws_cloudwatch_event_rule" "ecs_session_task_stopped" {
  name = "${local.environment_name}_ecs_session_task_stopped"
  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      clusterArn = [aws_ecs_cluster.main.arn]
      lastStatus = ["STOPPED"]
      group      = [{ prefix = "service:${local.environment_name}_" }]
    }
  })
}

resource "aws_cloudwatch_event_target" "cleanup_idle_session" {
  rule = aws_cloudwatch_event_rule.ecs_session_task_stopped.name
  arn  = aws_lambda_function.cleanup_idle_session.arn
}

resource "aws_lambda_permission" "cleanup_idle_session_eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cleanup_idle_session.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ecs_session_task_stopped.arn
}

resource "aws_cloudwatch_metric_alarm" "cleanup_idle_session_errors" {
  alarm_name          = "${local.cleanup_idle_session_function_name}_errors"
  alarm_description   = "Lambda cleanup_idle_session is producing errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.cleanup_idle_session.function_name
  }

  alarm_actions = [aws_sns_topic.alerting.arn]
}
