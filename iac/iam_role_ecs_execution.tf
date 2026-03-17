resource "aws_iam_role" "ecs_execution" {
  name = "${local.environment_name}_ecs_execution"

  assume_role_policy = data.aws_iam_policy_document.ecs_execution_assume.json
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
    actions = [
      "ecr:DescribeRegistry",
      "ecr:DescribeImages",
      "ecr:GetRepositoryPolicy",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer"
    ]
    resources = concat(
      [module.build_base_image.ecr_arn],
      [for img in local.available_ecr_images : "arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/${split(":", split("/", img)[1])[0]}"],
    )
  }
}
