data "aws_iam_policy_document" "run_session_lambda" {
  statement {
    actions = ["ecs:RegisterTaskDefinition", "ecs:TagResource"]
    resources = [
      "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${local.environment_name}_*",
    ]
  }
  statement {
    actions = [
      "ecs:CreateService",
      "ecs:DescribeServices",
      "ecs:TagResource",
    ]
    resources = [
      "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:service/${aws_ecs_cluster.main.name}/${local.environment_name}_*",
    ]
  }
  statement {
    actions = ["iam:PassRole"]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*",
    ]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
  statement {
    actions = [
      "elasticfilesystem:DescribeAccessPoints",
      "elasticfilesystem:CreateAccessPoint",
      "elasticfilesystem:TagResource",
    ]
    resources = [
      aws_efs_file_system.sessions.arn,
    ]
  }
  statement {
    actions = [
      "elasticloadbalancing:CreateTargetGroup",
      "elasticloadbalancing:DeleteTargetGroup",
      "elasticloadbalancing:CreateRule",
      "elasticloadbalancing:DeleteRule",
      "elasticloadbalancing:DescribeRules",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:AddTags",
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
      module.run_session.log_group_arn,
      "${module.run_session.log_group_arn}:*",
    ]
  }
}

module "run_session" {
  source                        = "./lambda_backend_module/"
  environment_name              = local.environment_name
  lambda_name                   = "run_session"
  code_path                     = "${path.root}/../code/backend/session/run_session/"
  timeout                       = 60
  api_id                        = aws_apigatewayv2_api.main.id
  api_execution_arn             = aws_apigatewayv2_api.main.execution_arn
  authorizer_id                 = aws_apigatewayv2_authorizer.cognito.id
  route_key                     = "POST /api/sessions"
  origin_verify_secret_ssm_name = aws_ssm_parameter.cf_origin_secret.name
  iam_policy_json               = data.aws_iam_policy_document.run_session_lambda.json
  environment_variables = {
    ENVIRONMENT_NAME             = local.environment_name
    ECS_CLUSTER_NAME             = aws_ecs_cluster.main.name
    SECURITY_GROUP_ID            = aws_security_group.ecs_service.id
    ECS_EXECUTION_ROLE_ARN       = aws_iam_role.ecs_execution.arn
    SUBNET_IDS                   = join(",", tolist(data.aws_subnets.public.ids))
    EFS_FILE_SYSTEM_ID           = aws_efs_file_system.sessions.id
    EFS_SHARED_ACCESS_POINT_ID   = aws_efs_access_point.shared.id
    SESSION_IDLE_TIMEOUT_MINUTES = tostring(local.session_idle_timeout_minutes)
    TASK_DEFAULT_VCPU            = tostring(local.task_default_vcpu)
    TASK_DEFAULT_MEMORY          = tostring(local.task_default_memory)
    TASK_MAX_VCPU                = tostring(local.task_max_vcpu)
    TASK_MAX_MEMORY              = tostring(local.task_max_memory)
    ALB_LISTENER_ARN             = aws_lb_listener.sessions.arn
    ALB_DNS_NAME                 = aws_lb.sessions.dns_name
    VPC_ID                       = data.aws_vpc.main.id
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
  depends_on = [aws_ssm_parameter.cf_origin_secret]
}
