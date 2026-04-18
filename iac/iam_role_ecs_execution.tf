resource "aws_iam_role" "ecs_execution" {
  name = "${local.environment_name}_ecs_execution"

  assume_role_policy = data.aws_iam_policy_document.ecs_execution_assume.json

  tags = {
    (local.security_tag_key) = local.security_tag_value
  }
}

data "aws_iam_policy_document" "ecs_execution_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type = "Service"

      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "ecs_execution" {
  name   = "${local.environment_name}_ecs_execution"
  policy = data.aws_iam_policy_document.ecs_execution.json
}

resource "aws_iam_policy_attachment" "ecs_execution" {
  name       = "${local.environment_name}_ecs_execution"
  roles      = [aws_iam_role.ecs_execution.name]
  policy_arn = aws_iam_policy.ecs_execution.arn
}

data "aws_iam_policy_document" "ecs_execution" {
  statement {
    actions = [
      "athena:*",
      "s3:Get*",
      "s3:List*",
      "glue:*",
      "lakeformation:*"
    ]
    resources = ["*"]
  }
  statement {
    actions = [
      "athena:GetWorkGroup",
      "athena:StartQueryExecution",
      "athena:StopQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:GetQueryResultsStream",
      "athena:ListQueryExecutions",
      "athena:BatchGetQueryExecution",
    ]
    resources = [aws_athena_workgroup.default.arn]
  }
  statement {
    actions = [
      "s3:PutObject"
    ]
    resources = [
      "${aws_s3_bucket.notebooks.arn}/notebooks/*",
      "${aws_s3_bucket.notebooks.arn}/notebook_executions/*",
      "${aws_s3_bucket.data.arn}/*",
    ]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "ecr:GetAuthorizationToken"
    ]
    resources = ["*"]
  }
  statement {
    actions = [
      "elasticfilesystem:ClientMount",
      "elasticfilesystem:ClientWrite",
      "elasticfilesystem:DescribeMountTargets",
    ]
    resources = [aws_efs_file_system.sessions.arn]
  }
  statement {
    actions   = ["ecr:DescribeRegistry"]
    resources = ["*"]
  }
  statement {
    actions = [
      "ecr:DescribeImages",
      "ecr:GetRepositoryPolicy",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer"
    ]
    resources = ["arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/*"]
    condition {
      test     = "StringEquals"
      variable = "ecr:ResourceTag/${local.security_tag_key}"
      values   = [local.security_tag_value]
    }
  }
}
