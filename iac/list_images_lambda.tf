data "aws_iam_policy_document" "list_images_lambda" {
  statement {
    actions   = ["dynamodb:Scan"]
    resources = [aws_dynamodb_table.images.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.list_images.log_group_arn,
      "${module.list_images.log_group_arn}:*",
    ]
  }
}

module "list_images" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "list_images"
  code_path                     = "${path.root}/../code/backend/list_images/"
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "GET /api/images"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.list_images_lambda.json
  environment_variables = {
    IMAGES_TABLE = aws_dynamodb_table.images.name
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
