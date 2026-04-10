data "aws_iam_policy_document" "update_configuration_lambda" {
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.configurations.arn]
  }
  statement {
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.labels.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.update_configuration.log_group_arn,
      "${module.update_configuration.log_group_arn}:*",
    ]
  }
}

module "update_configuration" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "update_configuration"
  code_path                     = "${path.root}/../code/backend/configuration/update_configuration/"
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "PATCH /api/configurations/{id}"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.update_configuration_lambda.json
  environment_variables = {
    CONFIGURATIONS_TABLE = aws_dynamodb_table.configurations.name
    LABELS_TABLE         = aws_dynamodb_table.labels.name
  }
  tags_map = {
    Appli          = var.project_name
    Component      = local.domain_name
    Env            = terraform.workspace
    git_repository = var.git_repository
  }
  depends_on = [aws_ssm_parameter.cf_origin_secret]
}
