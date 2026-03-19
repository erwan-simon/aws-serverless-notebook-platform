data "aws_iam_policy_document" "get_session_status_lambda" {
  statement {
    actions = [
      "ecs:ListTasks",
      "ecs:DescribeTasks",
    ]
    resources = ["*"]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.get_session_status.log_group_arn,
      "${module.get_session_status.log_group_arn}:*",
    ]
  }
}

module "get_session_status" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "get_session_status"
  code_path                     = "${path.root}/../code/backend/get_session_status/"
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "GET /api/sessions/{service_name}/status"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.get_session_status_lambda.json
  environment_variables = {
    ECS_CLUSTER_NAME = aws_ecs_cluster.main.name
    ENVIRONMENT_NAME = local.environment_name
    ALB_DNS_NAME     = aws_lb.sessions.dns_name
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
