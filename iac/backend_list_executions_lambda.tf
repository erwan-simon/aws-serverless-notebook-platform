data "aws_iam_policy_document" "list_executions_lambda" {
  statement {
    actions   = ["dynamodb:Scan"]
    resources = [aws_dynamodb_table.executions.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.list_executions.log_group_arn,
      "${module.list_executions.log_group_arn}:*",
    ]
  }
}

module "list_executions" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "list_executions"
  code_path                     = "${path.root}/../code/backend/execution/list_executions/"
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "GET /api/notebooks/{notebook_id}/executions"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.list_executions_lambda.json
  environment_variables = {
    EXECUTIONS_TABLE = aws_dynamodb_table.executions.name
  }
  tags_map = {
    Appli          = var.project_name
    Component      = local.domain_name
    Env            = terraform.workspace
    git_repository = var.git_repository
  }
  depends_on = [aws_ssm_parameter.cf_origin_secret]
}
