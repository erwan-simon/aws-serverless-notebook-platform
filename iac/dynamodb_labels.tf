resource "aws_dynamodb_table" "labels" {
  name         = "${local.environment_name}_labels"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "name"

  attribute {
    name = "name"
    type = "S"
  }

  tags = {
    Name           = "${local.environment_name}_labels"
    Appli          = var.project_name
    Component      = local.domain_name
    Env            = terraform.workspace
    git_repository = var.git_repository
  }
}
