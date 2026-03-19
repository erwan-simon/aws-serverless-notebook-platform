output "cloudfront_url" {
  value = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "api_gateway_url" {
  value = aws_apigatewayv2_stage.main.invoke_url
}

output "alb_sessions_url" {
  value = "http://${aws_lb.sessions.dns_name}"
}
