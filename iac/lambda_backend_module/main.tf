data "aws_ssm_parameter" "origin_secret" {
  name = var.origin_verify_secret_ssm_name
}

locals {
  function_name = "${var.environment_name}_${var.lambda_name}"
  code_path     = var.code_path
  rebuild_trigger = {
    task_code_hashes = jsonencode({
      for file_path in fileset(trimsuffix(local.code_path, "/"), "**") :
      file_path => filemd5("${trimsuffix(local.code_path, "/")}/${file_path}")
      if alltrue([
        for directory_pattern_to_ignore in [
          "__pycache__/", "login_error_message.txt"
        ] :
        !strcontains(file_path, directory_pattern_to_ignore)
      ])
    })
    dockerfile_hash = filemd5("${local.code_path}Dockerfile")
  }
  image_tag = sha1(jsonencode(local.rebuild_trigger))
}

module "image" {
  source                = "git::https://github.com/erwan-simon/terraform-module-build-image-and-push-to-ecr//iac/?ref=v1.0.1"
  ecr_name              = local.function_name
  code_path             = abspath(local.code_path)
  image_tag             = local.image_tag
  image_rebuild_trigger = jsonencode(local.rebuild_trigger)
  tags_map              = var.tags_map
}

resource "time_sleep" "ecr" {
  depends_on      = [module.image]
  triggers        = local.rebuild_trigger
  create_duration = "30s"
}

resource "aws_lambda_function" "main" {
  function_name = local.function_name
  role          = aws_iam_role.main.arn
  package_type  = "Image"
  image_uri     = "${module.image.ecr_url}:${local.image_tag}"
  timeout       = var.timeout
  memory_size   = var.memory_size

  environment {
    variables = merge(var.environment_variables, {
      ORIGIN_VERIFY_SECRET_SSM_NAME = var.origin_verify_secret_ssm_name
    })
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.main.name
  }
  depends_on = [time_sleep.ecr]
}

resource "aws_cloudwatch_log_group" "main" {
  name              = "${var.environment_name}/${var.lambda_name}"
  retention_in_days = 14
}

resource "aws_lambda_function_event_invoke_config" "main" {
  function_name                = aws_lambda_function.main.function_name
  maximum_event_age_in_seconds = 60
  maximum_retry_attempts       = 0
}
