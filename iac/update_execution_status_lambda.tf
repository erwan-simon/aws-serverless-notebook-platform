locals {
  update_execution_status_function_name = "${local.environment_name}_update_execution_status"
  update_execution_status_code_path     = "${path.root}/../code/backend/update_execution_status/"
  update_execution_status_rebuild_trigger = {
    task_code_hashes = jsonencode({
      for file_path in fileset(trimsuffix(local.update_execution_status_code_path, "/"), "**") :
      file_path => filemd5("${trimsuffix(local.update_execution_status_code_path, "/")}/${file_path}")
      if alltrue([
        for directory_pattern_to_ignore in [
          "__pycache__/", "login_error_message.txt"
        ] :
        !strcontains(file_path, directory_pattern_to_ignore)
      ])
    })
    dockerfile_hash = filemd5("${local.update_execution_status_code_path}Dockerfile")
  }
  update_execution_status_image_tag = sha1(jsonencode(local.update_execution_status_rebuild_trigger))
}

module "update_execution_status_image" {
  source                = "git::https://github.com/erwan-simon/terraform-module-build-image-and-push-to-ecr//iac/?ref=v1.0.1"
  ecr_name              = local.update_execution_status_function_name
  code_path             = abspath(local.update_execution_status_code_path)
  image_tag             = local.update_execution_status_image_tag
  image_rebuild_trigger = jsonencode(local.update_execution_status_rebuild_trigger)
  tags_map = {
    Appli          = var.project_name
    Component      = local.domain_name
    Env            = terraform.workspace
    git_repository = var.git_repository
  }
}

resource "time_sleep" "update_execution_status_ecr" {
  depends_on      = [module.update_execution_status_image]
  triggers        = local.update_execution_status_rebuild_trigger
  create_duration = "30s"
}

resource "aws_lambda_function" "update_execution_status" {
  function_name = local.update_execution_status_function_name
  role          = aws_iam_role.update_execution_status.arn
  package_type  = "Image"
  image_uri     = "${module.update_execution_status_image.ecr_url}:${local.update_execution_status_image_tag}"
  timeout       = 30
  memory_size   = 256

  environment {
    variables = {
      EXECUTIONS_TABLE = aws_dynamodb_table.executions.name
      ECS_CLUSTER_NAME = aws_ecs_cluster.main.name
    }
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.update_execution_status.name
  }
  depends_on = [time_sleep.update_execution_status_ecr]
}

resource "aws_cloudwatch_log_group" "update_execution_status" {
  name              = "${local.environment_name}/update_execution_status"
  retention_in_days = 14
}

resource "aws_lambda_function_event_invoke_config" "update_execution_status" {
  function_name                = aws_lambda_function.update_execution_status.function_name
  maximum_event_age_in_seconds = 60
  maximum_retry_attempts       = 0
}

# IAM
resource "aws_iam_role" "update_execution_status" {
  name = "${local.update_execution_status_function_name}_lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "update_execution_status" {
  name   = "${local.update_execution_status_function_name}_policy"
  role   = aws_iam_role.update_execution_status.id
  policy = data.aws_iam_policy_document.update_execution_status_lambda.json
}

data "aws_iam_policy_document" "update_execution_status_lambda" {
  statement {
    actions   = ["ecs:DescribeTasks"]
    resources = ["arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task/${aws_ecs_cluster.main.name}/*"]
  }
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.executions.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.update_execution_status.arn,
      "${aws_cloudwatch_log_group.update_execution_status.arn}:*",
    ]
  }
}

# EventBridge rule — ECS task state changes for execution tasks only
resource "aws_cloudwatch_event_rule" "ecs_task_state_change" {
  name = "${local.environment_name}_ecs_exec_task_state"
  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      clusterArn = [aws_ecs_cluster.main.arn]
      group      = [{ prefix = "family:${local.environment_name}_exec_" }]
    }
  })
}

resource "aws_cloudwatch_event_target" "update_execution_status" {
  rule = aws_cloudwatch_event_rule.ecs_task_state_change.name
  arn  = aws_lambda_function.update_execution_status.arn
}

resource "aws_lambda_permission" "update_execution_status_eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.update_execution_status.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ecs_task_state_change.arn
}

resource "aws_cloudwatch_metric_alarm" "update_execution_status_errors" {
  alarm_name          = "${local.update_execution_status_function_name}_errors"
  alarm_description   = "Lambda update_execution_status is producing errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.update_execution_status.function_name
  }

  alarm_actions = [aws_sns_topic.alerting.arn]
}
