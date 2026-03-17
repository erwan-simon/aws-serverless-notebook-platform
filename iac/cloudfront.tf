# Secret shared between CloudFront and the API Gateway origin.
# CloudFront injects this value as a custom header (x-origin-verify) on every request to the API origin.
# Each Lambda verifies this header to ensure requests come through CloudFront (and thus the WAF).
# CloudFront always overwrites this header, so a client cannot spoof it.
# The secret is stored in SSM Parameter Store (SecureString) so Lambdas can read it at startup.
# See: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html
resource "random_password" "cf_origin_secret" {
  length  = 32
  special = false
}

resource "aws_ssm_parameter" "cf_origin_secret" {
  name  = "/${local.environment_name}/cf-origin-verify-secret"
  type  = "SecureString"
  value = random_password.cf_origin_secret.result
}

resource "aws_cloudfront_origin_access_control" "main" {
  name                              = local.environment_name
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  web_acl_id          = aws_wafv2_web_acl.main.arn

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.main.id
  }

  # API Gateway origin — CloudFront proxies /api/* requests to the HTTP API.
  # The custom x-origin-verify header restricts direct access to the API Gateway URL.
  # See: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html
  origin {
    domain_name = "${aws_apigatewayv2_api.main.id}.execute-api.${data.aws_region.current.name}.amazonaws.com"
    origin_id   = "api-gateway"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    custom_header {
      name  = "x-origin-verify"
      value = random_password.cf_origin_secret.result
    }
  }

  ordered_cache_behavior {
    path_pattern           = "/api/*"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "api-gateway"
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Content-Type"]
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }
}
