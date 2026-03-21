resource "aws_dynamodb_table" "roles" {
  name         = "${local.environment_name}_roles"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  tags = {
    Name = "${local.environment_name}_roles"
  }
}
