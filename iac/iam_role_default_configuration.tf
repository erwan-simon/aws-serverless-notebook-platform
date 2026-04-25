resource "aws_iam_role" "default_configuration" {
  name = "${local.environment_name}_default_configuration"

  assume_role_policy = data.aws_iam_policy_document.default_configuration_assume.json

  tags = {
    (local.security_tag_key) = local.security_tag_value
  }
}

data "aws_iam_policy_document" "default_configuration_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type = "Service"

      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "default_configuration" {
  name   = "${local.environment_name}_default_configuration"
  policy = data.aws_iam_policy_document.default_configuration.json
}

resource "aws_iam_policy_attachment" "default_configuration" {
  name       = "${local.environment_name}_default_configuration"
  roles      = [aws_iam_role.default_configuration.name]
  policy_arn = aws_iam_policy.default_configuration.arn
}

data "aws_iam_policy_document" "default_configuration" {
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
      "athena:ListWorkGroups",
      "athena:ListDataCatalogs",
      "athena:GetDataCatalog",
    ]
    resources = ["*"]
  }
  statement {
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:SearchTables",
      "glue:GetCatalogImportStatus",
    ]
    resources = ["*"]
  }
  statement {
    actions = [
      "lakeformation:GetDataAccess",
      "lakeformation:GetTemporaryGlueTableCredentials",
    ]
    resources = ["*"]
  }
  statement {
    actions = [
      "s3:GetBucketLocation",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
      "s3:ListMultipartUploadParts",
      "s3:AbortMultipartUpload",
    ]
    resources = [
      aws_s3_bucket.data.arn,
      "${aws_s3_bucket.data.arn}/*",
    ]
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
