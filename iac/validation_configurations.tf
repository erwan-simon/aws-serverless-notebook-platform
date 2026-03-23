resource "aws_dynamodb_table_item" "default_configuration" {
  table_name = aws_dynamodb_table.configurations.name
  hash_key   = aws_dynamodb_table.configurations.hash_key

  item = jsonencode({
    id            = { S = "default" }
    name          = { S = "Default" }
    ecr_image_uri = { S = "${module.build_base_image.ecr_url}:${local.image_tag}" }
    iam_role_arn  = { S = aws_iam_role.ecs_execution.arn }
    vcpu          = { N = tostring(local.task_default_vcpu) }
    memory        = { N = tostring(local.task_default_memory) }
    managed_by    = { S = "terraform" }
    created_at    = { S = "2026-01-01T00:00:00+00:00" }
    created_by    = { S = "terraform" }
  })
}
