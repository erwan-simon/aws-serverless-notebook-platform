data "aws_iam_policy_document" "upload_notebook_lambda" {
  statement {
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.notebooks.arn}/${local.notebooks_s3_prefix}*"]
  }
  statement {
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.notebooks.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.upload_notebook.log_group_arn,
      "${module.upload_notebook.log_group_arn}:*",
    ]
  }
}

module "upload_notebook" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "upload_notebook"
  code_path                     = "${path.root}/../code/backend/notebook/upload_notebook/"
  timeout                       = 60
  memory_size                   = 512
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "POST /api/notebooks"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.upload_notebook_lambda.json
  environment_variables = {
    NOTEBOOKS_BUCKET    = aws_s3_bucket.notebooks.id
    NOTEBOOKS_S3_PREFIX = local.notebooks_s3_prefix
    NOTEBOOKS_TABLE     = aws_dynamodb_table.notebooks.name
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
