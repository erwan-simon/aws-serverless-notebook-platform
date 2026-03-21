resource "aws_cognito_user_pool" "main" {
  name                     = local.environment_name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_resource_server" "main" {
  user_pool_id = aws_cognito_user_pool.main.id
  identifier   = "urn:${local.environment_name}:api"
  name         = "${local.environment_name}-api"

  scope {
    scope_name        = "api.read"
    scope_description = "Read access to API"
  }

  scope {
    scope_name        = "api.write"
    scope_description = "Write access to API"
  }
}

resource "random_string" "domain_prefix" {
  length  = 5
  upper   = false
  special = false

  keepers = {
    project = "never_changes"
  }
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = random_string.domain_prefix.result
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_user_pool_client" "main" {
  name         = local.environment_name
  user_pool_id = aws_cognito_user_pool.main.id

  # For browser-based apps using PKCE, do NOT generate a secret.
  generate_secret = false

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  callback_urls = ["https://${aws_cloudfront_distribution.main.domain_name}"]
  logout_urls   = ["https://${aws_cloudfront_distribution.main.domain_name}"]

  explicit_auth_flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]

  supported_identity_providers = ["COGNITO"]

  prevent_user_existence_errors = "ENABLED"

  access_token_validity  = "24"
  id_token_validity      = "24"
  refresh_token_validity = "24"
}
