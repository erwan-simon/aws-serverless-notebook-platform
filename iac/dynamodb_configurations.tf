resource "aws_dynamodb_table" "configurations" {
  name         = "${local.environment_name}_configurations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  tags = {
    Name = "${local.environment_name}_configurations"
  }
}
