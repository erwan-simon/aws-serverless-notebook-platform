data "aws_iam_policy_document" "stop_session_lambda" {
  statement {
    actions = [
      "ecs:UpdateService",
      "ecs:DeleteService",
      "ecs:DescribeServices",
    ]
    resources = [
      "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:service/${aws_ecs_cluster.main.name}/${local.environment_name}_*",
    ]
  }
  statement {
    actions = [
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DeleteTargetGroup",
      "elasticloadbalancing:DescribeRules",
      "elasticloadbalancing:DeleteRule",
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
      module.stop_session.log_group_arn,
      "${module.stop_session.log_group_arn}:*",
    ]
  }
}

module "stop_session" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "stop_session"
  code_path                     = "${path.root}/../code/backend/stop_session/"
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "DELETE /api/sessions/{service_name}"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.stop_session_lambda.json
  environment_variables = {
    ECS_CLUSTER_NAME = aws_ecs_cluster.main.name
    ENVIRONMENT_NAME = local.environment_name
    ALB_LISTENER_ARN = aws_lb_listener.sessions.arn
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
