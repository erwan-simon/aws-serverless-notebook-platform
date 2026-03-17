resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.function_name}_errors"
  alarm_description   = "Lambda ${var.lambda_name} is producing errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.main.function_name
  }

  alarm_actions = [var.sns_alerting_topic_arn]
}
