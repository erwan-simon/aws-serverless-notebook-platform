data "aws_iam_policy_document" "delete_notebook_lambda" {
  statement {
    actions   = ["s3:DeleteObject"]
    resources = ["${aws_s3_bucket.notebooks.arn}/${local.notebooks_s3_prefix}*"]
  }
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:DeleteItem", "dynamodb:PutItem"]
    resources = [aws_dynamodb_table.notebooks.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.delete_notebook.log_group_arn,
      "${module.delete_notebook.log_group_arn}:*",
    ]
  }
}

module "delete_notebook" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "delete_notebook"
  code_path                     = "${path.root}/../code/backend/notebook/delete_notebook/"
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "DELETE /api/notebooks/{id}"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.delete_notebook_lambda.json
  environment_variables = {
    NOTEBOOKS_BUCKET = aws_s3_bucket.notebooks.id
    NOTEBOOKS_TABLE  = aws_dynamodb_table.notebooks.name
  }
  tags_map = {
    Appli          = var.project_name
    Component      = local.domain_name
    Env            = terraform.workspace
    git_repository = var.git_repository
  }
  depends_on = [aws_ssm_parameter.cf_origin_secret]
}
