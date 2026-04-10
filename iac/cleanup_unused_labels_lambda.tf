locals {
  cleanup_unused_labels_function_name = "${local.environment_name}_cleanup_unused_labels"
  cleanup_unused_labels_code_path     = "${path.root}/../code/lambda_cleanup_unused_labels/"
  cleanup_unused_labels_rebuild_trigger = {
    task_code_hashes = jsonencode({
      for file_path in fileset(trimsuffix(local.cleanup_unused_labels_code_path, "/"), "**") :
      file_path => filemd5("${trimsuffix(local.cleanup_unused_labels_code_path, "/")}/${file_path}")
      if !strcontains(file_path, "__pycache__/")
    })
    dockerfile_hash = filemd5("${local.cleanup_unused_labels_code_path}Dockerfile")
  }
  cleanup_unused_labels_image_tag = sha1(jsonencode(local.cleanup_unused_labels_rebuild_trigger))
}

module "cleanup_unused_labels_image" {
  source                = "git::https://github.com/erwan-simon/terraform-module-build-image-and-push-to-ecr//iac/?ref=v1.0.2"
  ecr_name              = local.cleanup_unused_labels_function_name
  code_path             = abspath(local.cleanup_unused_labels_code_path)
  image_tag             = local.cleanup_unused_labels_image_tag
  image_rebuild_trigger = jsonencode(local.cleanup_unused_labels_rebuild_trigger)
  tags_map = {
    Appli          = var.project_name
    Component      = local.domain_name
    Env            = terraform.workspace
    git_repository = var.git_repository
  }
}

resource "time_sleep" "cleanup_unused_labels_ecr" {
  depends_on      = [module.cleanup_unused_labels_image]
  triggers        = local.cleanup_unused_labels_rebuild_trigger
  create_duration = "30s"
}

resource "aws_lambda_function" "cleanup_unused_labels" {
  function_name = local.cleanup_unused_labels_function_name
  role          = aws_iam_role.cleanup_unused_labels.arn
  package_type  = "Image"
  image_uri     = "${module.cleanup_unused_labels_image.ecr_url}:${local.cleanup_unused_labels_image_tag}"
  timeout       = 120
  memory_size   = 256

  environment {
    variables = {
      NOTEBOOKS_TABLE      = aws_dynamodb_table.notebooks.name
      CONFIGURATIONS_TABLE = aws_dynamodb_table.configurations.name
      LABELS_TABLE         = aws_dynamodb_table.labels.name
    }
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.cleanup_unused_labels.name
  }
  depends_on = [time_sleep.cleanup_unused_labels_ecr]
}

resource "aws_cloudwatch_log_group" "cleanup_unused_labels" {
  name              = "${local.environment_name}/cleanup_unused_labels"
  retention_in_days = 14
}

resource "aws_lambda_function_event_invoke_config" "cleanup_unused_labels" {
  function_name                = aws_lambda_function.cleanup_unused_labels.function_name
  maximum_event_age_in_seconds = 60
  maximum_retry_attempts       = 0
}

# IAM
resource "aws_iam_role" "cleanup_unused_labels" {
  name = "${local.cleanup_unused_labels_function_name}_lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "cleanup_unused_labels" {
  name   = "${local.cleanup_unused_labels_function_name}_policy"
  role   = aws_iam_role.cleanup_unused_labels.id
  policy = data.aws_iam_policy_document.cleanup_unused_labels_lambda.json
}

data "aws_iam_policy_document" "cleanup_unused_labels_lambda" {
  statement {
    actions   = ["dynamodb:Scan"]
    resources = [
      aws_dynamodb_table.notebooks.arn,
      aws_dynamodb_table.configurations.arn,
      aws_dynamodb_table.labels.arn,
    ]
  }
  statement {
    actions   = ["dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.labels.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.cleanup_unused_labels.arn,
      "${aws_cloudwatch_log_group.cleanup_unused_labels.arn}:*",
    ]
  }
}

# EventBridge rule — daily schedule
resource "aws_cloudwatch_event_rule" "cleanup_unused_labels_daily" {
  name                = "${local.environment_name}_cleanup_unused_labels_daily"
  schedule_expression = "rate(1 day)"
}

resource "aws_cloudwatch_event_target" "cleanup_unused_labels" {
  rule = aws_cloudwatch_event_rule.cleanup_unused_labels_daily.name
  arn  = aws_lambda_function.cleanup_unused_labels.arn
}

resource "aws_lambda_permission" "cleanup_unused_labels_eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cleanup_unused_labels.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.cleanup_unused_labels_daily.arn
}

resource "aws_cloudwatch_metric_alarm" "cleanup_unused_labels_errors" {
  alarm_name          = "${local.cleanup_unused_labels_function_name}_errors"
  alarm_description   = "Lambda cleanup_unused_labels is producing errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.cleanup_unused_labels.function_name
  }

  alarm_actions = [aws_sns_topic.alerting.arn]
}
