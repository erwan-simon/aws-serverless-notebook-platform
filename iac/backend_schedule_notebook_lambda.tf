data "aws_iam_policy_document" "schedule_notebook_lambda" {
  statement {
    actions   = ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:GetSchedule"]
    resources = ["arn:aws:scheduler:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:schedule/default/${local.environment_name}_nb_*"]
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.eventbridge_scheduler.arn]
  }
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.notebooks.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.schedule_notebook.log_group_arn,
      "${module.schedule_notebook.log_group_arn}:*",
    ]
  }
}

module "schedule_notebook" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "schedule_notebook"
  code_path                     = "${path.root}/../code/backend/schedule/schedule_notebook/"
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "POST /api/notebooks/{id}/schedule"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.schedule_notebook_lambda.json
  environment_variables = {
    NOTEBOOKS_TABLE         = aws_dynamodb_table.notebooks.name
    SCHEDULER_ROLE_ARN      = aws_iam_role.eventbridge_scheduler.arn
    RUN_NOTEBOOK_LAMBDA_ARN = module.run_notebook.function_arn
    ENVIRONMENT_NAME        = local.environment_name
  }
  tags_map = {
    Appli          = var.project_name
    Component      = local.domain_name
    Env            = terraform.workspace
    git_repository = var.git_repository
  }
  sns_alerting_topic_arn = aws_sns_topic.alerting.arn
  depends_on             = [aws_ssm_parameter.cf_origin_secret]
}
