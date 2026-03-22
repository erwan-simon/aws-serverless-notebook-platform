resource "aws_s3_object" "validation_notebook" {
  bucket       = aws_s3_bucket.notebooks.id
  key          = "validation/hello_world.ipynb"
  source       = "${path.root}/../hello_world.ipynb"
  content_type = "application/x-ipynb+json"
  etag         = filemd5("${path.root}/../hello_world.ipynb")
}

resource "aws_dynamodb_table_item" "validation_notebook" {
  table_name = aws_dynamodb_table.notebooks.name
  hash_key   = aws_dynamodb_table.notebooks.hash_key

  item = jsonencode({
    id          = { S = local.validation_notebook_id }
    s3_key      = { S = aws_s3_object.validation_notebook.key }
    name        = { S = "_system/hello_world.ipynb" }
    uploaded_at = { S = "2026-01-01T00:00:00+00:00" }
    owner_id    = { S = local.technical_owner_id }
    owner_email = { S = local.technical_owner_id }
  })
}
