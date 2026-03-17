resource "aws_cloudwatch_log_group" "main" {
  name = "${local.environment_name}/cluster"
}
