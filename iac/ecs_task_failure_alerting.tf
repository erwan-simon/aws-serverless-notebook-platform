resource "aws_cloudwatch_event_rule" "ecs_task_failure" {
  name = "${local.environment_name}_ecs_task_failure"
  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      clusterArn = [aws_ecs_cluster.main.arn]
      lastStatus = ["STOPPED"]
      stopCode   = ["TaskFailedToStart", "EssentialContainerExited", "ServiceSchedulerInitiated"]
      containers = {
        exitCode = [{ anything-but = 0 }]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "ecs_task_failure_sns" {
  rule = aws_cloudwatch_event_rule.ecs_task_failure.name
  arn  = aws_sns_topic.alerting.arn
}

resource "aws_sns_topic_policy" "alerting_eventbridge" {
  arn = aws_sns_topic.alerting.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "sns:Publish"
        Resource  = aws_sns_topic.alerting.arn
      }
    ]
  })
}
