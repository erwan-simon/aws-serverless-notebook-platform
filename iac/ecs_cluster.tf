resource "aws_ecs_cluster" "main" {
  name = local.environment_name
  setting {
    name  = "containerInsights"
    value = "enhanced"
  }
  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"

      log_configuration {
        cloud_watch_encryption_enabled = true
        cloud_watch_log_group_name     = aws_cloudwatch_log_group.main.name
      }
    }
  }
}
