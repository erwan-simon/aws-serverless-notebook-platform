locals {
  stage_name          = terraform.workspace
  environment_name    = "${var.project_name}_${local.domain_name}_${local.stage_name}"
  domain_name         = "jupyter_sandbox"
  notebooks_s3_prefix = "notebooks/"

  available_configurations = [
    {
      name          = "Default"
      ecr_image_uri = "${module.build_base_image.ecr_url}:${local.image_tag}"
      iam_role_arn  = aws_iam_role.ecs_execution.arn
      vcpu          = local.task_default_vcpu
      memory        = local.task_default_memory
    },
  ]

  session_idle_timeout_minutes = 60

  task_default_vcpu   = 256
  task_default_memory = 512
  task_max_vcpu       = 4096
  task_max_memory     = 16384

  technical_owner_id     = "system"
  validation_notebook_id = "validation_hello_world"
}
