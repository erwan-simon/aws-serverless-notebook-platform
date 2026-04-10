locals {
  stage_name          = terraform.workspace
  environment_name    = "${var.project_name}_${local.domain_name}_${local.stage_name}"
  domain_name         = "jupyter_sandbox"
  notebooks_s3_prefix = "notebooks/"

  session_idle_timeout_minutes = 60

  task_default_vcpu   = 512
  task_default_memory = 1024
  task_max_vcpu       = 4096
  task_max_memory     = 16384

  technical_owner_id     = "system"
  validation_notebook_id = "validation_hello_world"

  label_regex = "^[a-z\\u00e0-\\u00f6\\u00f8-\\u00ff0-9\\-]{1,12}$"

  security_tag_key   = "${var.project_name}:${local.domain_name}"
  security_tag_value = "allowed"
}
