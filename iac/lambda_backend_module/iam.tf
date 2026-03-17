resource "aws_iam_role" "main" {
  name               = "${local.function_name}_lambda"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "main" {
  name   = "${local.function_name}_lambda"
  policy = var.iam_policy_json
}

resource "aws_iam_policy_attachment" "main" {
  name       = "${local.function_name}_lambda"
  roles      = [aws_iam_role.main.name]
  policy_arn = aws_iam_policy.main.arn
}

resource "aws_iam_role_policy" "ssm_origin_secret" {
  name = "${local.function_name}_ssm_origin_secret"
  role = aws_iam_role.main.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = data.aws_ssm_parameter.origin_secret.arn
      }
    ]
  })
}
