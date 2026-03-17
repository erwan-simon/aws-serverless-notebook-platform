data "aws_iam_policy_document" "run_notebook_lambda" {
  statement {
    actions = ["ecs:RegisterTaskDefinition", "ecs:RunTask", "ecs:TagResource"]
    resources = [
      "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${local.environment_name}_*",
      "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task/${aws_ecs_cluster.main.name}/*",
    ]
  }
  statement {
    actions = ["iam:PassRole"]
    resources = concat(
      [aws_iam_role.ecs_execution.arn],
      [for role in local.available_iam_roles : role],
    )
  }
  statement {
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.notebooks.arn]
  }
  statement {
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.executions.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      module.run_notebook.log_group_arn,
      "${module.run_notebook.log_group_arn}:*",
    ]
  }
}

resource "aws_lambda_permission" "run_notebook_scheduler" {
  statement_id  = "AllowEventBridgeScheduler"
  action        = "lambda:InvokeFunction"
  function_name = module.run_notebook.function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = aws_iam_role.eventbridge_scheduler.arn
}

module "run_notebook" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "run_notebook"
  code_path                     = "${path.root}/../code/backend/run_notebook/"
  timeout                       = 60
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "POST /api/executions"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.run_notebook_lambda.json
  environment_variables = {
    ENVIRONMENT_NAME       = local.environment_name
    ECS_CLUSTER_NAME       = aws_ecs_cluster.main.name
    SECURITY_GROUP_ID      = aws_security_group.ecs_service.id
    ECS_EXECUTION_ROLE_ARN = aws_iam_role.ecs_execution.arn
    NOTEBOOKS_BUCKET       = aws_s3_bucket.notebooks.id
    NOTEBOOKS_TABLE        = aws_dynamodb_table.notebooks.name
    EXECUTIONS_TABLE       = aws_dynamodb_table.executions.name
    SUBNET_IDS             = join(",", tolist(data.aws_subnets.public.ids))
    TASK_DEFAULT_VCPU      = tostring(local.task_default_vcpu)
    TASK_DEFAULT_MEMORY    = tostring(local.task_default_memory)
    TASK_MAX_VCPU          = tostring(local.task_max_vcpu)
    TASK_MAX_MEMORY        = tostring(local.task_max_memory)
    RESOURCE_TAGS = jsonencode({
      Appli          = var.project_name
      Component      = local.domain_name
      Env            = terraform.workspace
      git_repository = var.git_repository
    })
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
