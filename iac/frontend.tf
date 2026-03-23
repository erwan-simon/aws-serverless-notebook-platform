resource "aws_s3_object" "index_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "index.html"
  source       = "${path.root}/../code/frontend/index.html"
  content_type = "text/html"
  etag         = filemd5("${path.root}/../code/frontend/index.html")
}

resource "aws_s3_object" "notebook_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "notebook.html"
  source       = "${path.root}/../code/frontend/notebook.html"
  content_type = "text/html"
  etag         = filemd5("${path.root}/../code/frontend/notebook.html")
}

resource "aws_s3_object" "run_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "run.html"
  source       = "${path.root}/../code/frontend/run.html"
  content_type = "text/html"
  etag         = filemd5("${path.root}/../code/frontend/run.html")
}

resource "aws_s3_object" "session_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "session.html"
  source       = "${path.root}/../code/frontend/session.html"
  content_type = "text/html"
  etag         = filemd5("${path.root}/../code/frontend/session.html")
}

resource "aws_s3_object" "status_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "status.html"
  source       = "${path.root}/../code/frontend/status.html"
  content_type = "text/html"
  etag         = filemd5("${path.root}/../code/frontend/status.html")
}

resource "aws_s3_object" "execution_status_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "execution_status.html"
  source       = "${path.root}/../code/frontend/execution_status.html"
  content_type = "text/html"
  etag         = filemd5("${path.root}/../code/frontend/execution_status.html")
}

resource "aws_s3_object" "executions_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "executions.html"
  source       = "${path.root}/../code/frontend/executions.html"
  content_type = "text/html"
  etag         = filemd5("${path.root}/../code/frontend/executions.html")
}

resource "aws_s3_object" "configurations_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "configurations.html"
  source       = "${path.root}/../code/frontend/configurations.html"
  content_type = "text/html"
  etag         = filemd5("${path.root}/../code/frontend/configurations.html")
}

resource "aws_s3_object" "auth_js" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "auth.js"
  source       = "${path.root}/../code/frontend/auth.js"
  content_type = "application/javascript"
  etag         = filemd5("${path.root}/../code/frontend/auth.js")
}

resource "aws_s3_object" "config_js" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "config.js"
  content_type = "application/javascript"
  content = templatefile("${path.root}/../code/frontend/config.js.tpl", {
    api_base_url                  = ""
    cognito_domain                = "${aws_cognito_user_pool_domain.main.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
    cognito_client_id             = aws_cognito_user_pool_client.main.id
    cognito_redirect_uri          = "https://${aws_cloudfront_distribution.main.domain_name}"
    task_default_vcpu             = local.task_default_vcpu
    task_default_memory           = local.task_default_memory
    task_max_vcpu                 = local.task_max_vcpu
    task_max_memory               = local.task_max_memory
    session_idle_timeout_minutes  = local.session_idle_timeout_minutes
  })
}
