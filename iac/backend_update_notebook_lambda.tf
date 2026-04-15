data "aws_iam_policy_document" "update_notebook_lambda" {
  statement {
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.notebooks.arn}/${local.notebooks_s3_prefix}*"]
  }
  statement {
    actions   = ["s3:DeleteObject"]
    resources = ["${aws_s3_bucket.notebooks.arn}/${local.rendered_notebooks_s3_prefix}*"]
  }
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.notebooks.arn]
  }
  statement {
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.labels.arn]
  }
  statement {
    actions   = ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:GetSchedule", "scheduler:DeleteSchedule"]
    resources = ["arn:aws:scheduler:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:schedule/default/${local.environment_name}_nb_*"]
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.eventbridge_scheduler.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.update_notebook.log_group_arn,
      "${module.update_notebook.log_group_arn}:*",
    ]
  }
}

module "update_notebook" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "update_notebook"
  code_path                     = "${path.root}/../code/backend/notebook/update_notebook/"
  timeout                       = 60
  memory_size                   = 512
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "PATCH /api/notebooks/{id}"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.update_notebook_lambda.json
  environment_variables = {
    NOTEBOOKS_BUCKET        = aws_s3_bucket.notebooks.id
    NOTEBOOKS_TABLE         = aws_dynamodb_table.notebooks.name
    LABELS_TABLE            = aws_dynamodb_table.labels.name
    LABEL_REGEX             = local.label_regex
    SCHEDULER_ROLE_ARN      = aws_iam_role.eventbridge_scheduler.arn
    RUN_NOTEBOOK_LAMBDA_ARN = module.run_notebook.function_arn
    ENVIRONMENT_NAME        = local.environment_name
  }
  tags_map = {
    Appli          = var.project_name
    Component      = local.domain_name
    Env            = terraform.workspace
    git_repository = var.git_repository
  }
  depends_on = [aws_ssm_parameter.cf_origin_secret]
}
