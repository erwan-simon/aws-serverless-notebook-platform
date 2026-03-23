data "aws_iam_policy_document" "render_notebook_lambda" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.notebooks.arn}/*"]
  }
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.notebooks.arn, aws_dynamodb_table.executions.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.render_notebook.log_group_arn,
      "${module.render_notebook.log_group_arn}:*",
    ]
  }
}

module "render_notebook" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "render_notebook"
  code_path                     = "${path.root}/../code/backend/notebook/render_notebook/"
  timeout                       = 60
  memory_size                   = 512
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "GET /api/notebooks/render"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.render_notebook_lambda.json
  environment_variables = {
    NOTEBOOKS_BUCKET = aws_s3_bucket.notebooks.id
    NOTEBOOKS_TABLE  = aws_dynamodb_table.notebooks.name
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
