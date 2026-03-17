resource "aws_s3_bucket" "notebooks" {
  bucket        = "${replace(local.environment_name, "_", "-")}-notebooks"
  force_destroy = false
}

resource "aws_s3_bucket_server_side_encryption_configuration" "notebooks" {
  bucket = aws_s3_bucket.notebooks.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "notebooks" {
  bucket = aws_s3_bucket.notebooks.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "notebooks" {
  bucket = aws_s3_bucket.notebooks.id
  policy = data.aws_iam_policy_document.s3_notebooks.json
}

data "aws_iam_policy_document" "s3_notebooks" {
  statement {
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.notebooks.arn}/*",
      aws_s3_bucket.notebooks.arn,
    ]
    principals {
      type        = "AWS"
      identifiers = [data.aws_elb_service_account.main.arn]
    }
  }
}
