resource "aws_iam_role" "ecs_service" {
  name               = "${local.environment_name}_ecs_service"
  assume_role_policy = data.aws_iam_policy_document.ecs_service_assume.json
}

data "aws_iam_policy_document" "ecs_service_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type = "Service"

      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "ecs_service" {
  name   = "${local.environment_name}_ecs_service"
  policy = data.aws_iam_policy_document.ecs_service.json
}

resource "aws_iam_policy_attachment" "ecs_service" {
  name       = "${local.environment_name}_ecs_service"
  roles      = [aws_iam_role.ecs_service.name]
  policy_arn = aws_iam_policy.ecs_service.arn
}

data "aws_iam_policy_document" "ecs_service" {
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
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["*"]
  }
}

