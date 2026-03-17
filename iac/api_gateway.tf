resource "aws_apigatewayv2_api" "main" {
  name          = local.environment_name
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "DELETE", "OPTIONS"]
    allow_headers = ["Content-Type", "Authorization"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.main.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${local.environment_name}_cognito"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.main.id]
    issuer   = "https://cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  }
}

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${local.environment_name}"
  retention_in_days = 14
}

resource "aws_apigatewayv2_stage" "main" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  # Global default: 10 req/s burst, 5 req/s sustained
  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }

  # Stricter limits on expensive/destructive endpoints
  route_settings {
    route_key              = "POST /api/sessions"
    throttling_burst_limit = 3
    throttling_rate_limit  = 1
  }

  route_settings {
    route_key              = "DELETE /api/sessions/{service_name}"
    throttling_burst_limit = 3
    throttling_rate_limit  = 1
  }

  route_settings {
    route_key              = "POST /api/executions"
    throttling_burst_limit = 3
    throttling_rate_limit  = 1
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      ip               = "$context.identity.sourceIp"
      requestTime      = "$context.requestTime"
      httpMethod       = "$context.httpMethod"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      protocol         = "$context.protocol"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }
}

