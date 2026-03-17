resource "aws_apigatewayv2_integration" "main" {
  api_id                 = var.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.main.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "main" {
  api_id             = var.api_id
  route_key          = var.route_key
  target             = "integrations/${aws_apigatewayv2_integration.main.id}"
  authorization_type = "JWT"
  authorizer_id      = var.authorizer_id
}

resource "aws_lambda_permission" "main" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.main.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${var.api_execution_arn}/*/*"
}
