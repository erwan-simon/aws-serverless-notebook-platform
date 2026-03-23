data "aws_iam_policy_document" "get_execution_status_lambda" {
  statement {
    actions   = ["ecs:DescribeTasks"]
    resources = ["*"]
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
      module.get_execution_status.log_group_arn,
      "${module.get_execution_status.log_group_arn}:*",
    ]
  }
}

module "get_execution_status" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "get_execution_status"
  code_path                     = "${path.root}/../code/backend/execution/get_execution_status/"
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "GET /api/executions/{execution_id}/status"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.get_execution_status_lambda.json
  environment_variables = {
    ECS_CLUSTER_NAME = aws_ecs_cluster.main.name
    ENVIRONMENT_NAME = local.environment_name
    EXECUTIONS_TABLE = aws_dynamodb_table.executions.name
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
