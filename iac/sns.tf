resource "aws_sns_topic" "alerting" {
  name = "${local.environment_name}_alerting"
}

resource "aws_sns_topic_subscription" "alerting_email" {
  for_each  = toset(split(",", var.alerting_emails))
  topic_arn = aws_sns_topic.alerting.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_sns_topic" "alerting_us_east_1" {
  provider = aws.us_east_1
  name     = "${local.environment_name}_alerting"
}

resource "aws_sns_topic_subscription" "alerting_email_us_east_1" {
  provider  = aws.us_east_1
  for_each  = toset(split(",", var.alerting_emails))
  topic_arn = aws_sns_topic.alerting_us_east_1.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_cloudwatch_metric_alarm" "waf_blocked_requests" {
  provider            = aws.us_east_1
  alarm_name          = "${local.environment_name}_waf_blocked_requests"
  alarm_description   = "High number of blocked requests by WAF"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "BlockedRequests"
  namespace           = "AWS/WAFV2"
  period              = 300
  statistic           = "Sum"
  threshold           = 50
  treat_missing_data  = "notBreaching"

  dimensions = {
    WebACL = local.environment_name
    Region = "us-east-1"
    Rule   = "ALL"
  }

  alarm_actions = [aws_sns_topic.alerting_us_east_1.arn]
}
