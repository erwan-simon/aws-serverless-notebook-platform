locals {
  stage_name          = terraform.workspace
  environment_name    = "${var.project_name}_${local.domain_name}_${local.stage_name}"
  domain_name         = "jupyter_sandbox"
  notebooks_s3_prefix = "notebooks/"

  available_iam_roles = [
    aws_iam_role.ecs_execution.arn,
  ]

  available_ecr_images = [
    "${module.build_base_image.ecr_url}:${local.image_tag}",
  ]

  session_idle_timeout_minutes = 60

  task_default_vcpu   = 256
  task_default_memory = 512
  task_max_vcpu       = 4096
  task_max_memory     = 16384
}
