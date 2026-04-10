locals {
  frontend_static_files = {
    "index.html"            = "text/html"
    "notebook.html"         = "text/html"
    "run.html"              = "text/html"
    "session.html"          = "text/html"
    "status.html"           = "text/html"
    "execution_status.html" = "text/html"
    "executions.html"       = "text/html"
    "configurations.html"   = "text/html"
    "style.css"             = "text/css"
    "auth.js"               = "application/javascript"
  }
}

resource "aws_s3_object" "frontend" {
  for_each     = local.frontend_static_files
  bucket       = aws_s3_bucket.frontend.id
  key          = each.key
  source       = "${path.root}/../code/frontend/${each.key}"
  content_type = each.value
  etag         = filemd5("${path.root}/../code/frontend/${each.key}")
}

resource "aws_s3_object" "config_js" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "config.js"
  content_type = "application/javascript"
  content = templatefile("${path.root}/../code/frontend/config.js.tpl", {
    api_base_url                 = ""
    cognito_domain               = "${aws_cognito_user_pool_domain.main.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
    cognito_client_id            = aws_cognito_user_pool_client.main.id
    cognito_redirect_uri         = "https://${aws_cloudfront_distribution.main.domain_name}"
    task_default_vcpu            = local.task_default_vcpu
    task_default_memory          = local.task_default_memory
    task_max_vcpu                = local.task_max_vcpu
    task_max_memory              = local.task_max_memory
    session_idle_timeout_minutes = local.session_idle_timeout_minutes
    label_regex                  = local.label_regex
  })
}
