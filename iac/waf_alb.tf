resource "aws_wafv2_ip_set" "alb" {
  name               = "${local.environment_name}_alb"
  scope              = "REGIONAL"
  ip_address_version = "IPV4"
  addresses          = split(",", var.cidr_list_to_whitelist)
}

resource "aws_wafv2_web_acl" "alb" {
  name  = "${local.environment_name}_alb"
  scope = "REGIONAL"

  default_action {
    block {}
  }

  rule {
    name     = "rate-limit"
    priority = 0

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 100
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.environment_name}_alb_rate_limit"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "whitelist-france"
    priority = 1

    action {
      allow {}
    }

    statement {
      geo_match_statement {
        country_codes = ["FR"]
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.environment_name}_alb_geo_match"
      sampled_requests_enabled   = true
    }
  }

  /*
  rule {
    name     = "allow-whitelisted-ips"
    priority = 2

    action {
      allow {}
    }

    statement {
      ip_set_reference_statement {
        arn = aws_wafv2_ip_set.alb.arn
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.environment_name}_alb_allow_ips"
      sampled_requests_enabled   = true
    }
  }
  */

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.environment_name}_alb_waf"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = aws_lb.sessions.arn
  web_acl_arn  = aws_wafv2_web_acl.alb.arn
}
