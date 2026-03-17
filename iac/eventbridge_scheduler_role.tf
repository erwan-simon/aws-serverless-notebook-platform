resource "aws_iam_role" "eventbridge_scheduler" {
  name               = "${local.environment_name}_eventbridge_scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name   = "${local.environment_name}_scheduler_invoke_lambda"
  role   = aws_iam_role.eventbridge_scheduler.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [module.run_notebook.function_arn]
  }
}
