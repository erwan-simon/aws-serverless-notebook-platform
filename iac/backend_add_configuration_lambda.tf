data "aws_iam_policy_document" "add_configuration_lambda" {
  statement {
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.configurations.arn]
  }
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [module.run_notebook.function_arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.add_configuration.log_group_arn,
      "${module.add_configuration.log_group_arn}:*",
    ]
  }
}

module "add_configuration" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "add_configuration"
  code_path                     = "${path.root}/../code/backend/configuration/add_configuration/"
  timeout                       = 60
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "POST /api/configurations"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.add_configuration_lambda.json
  environment_variables = {
    CONFIGURATIONS_TABLE       = aws_dynamodb_table.configurations.name
    RUN_NOTEBOOK_FUNCTION_NAME = module.run_notebook.function_name
    VALIDATION_NOTEBOOK_ID     = local.validation_notebook_id
    TECHNICAL_OWNER_ID         = local.technical_owner_id
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
