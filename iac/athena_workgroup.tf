locals {
  athena_results_s3_prefix = "athena_results/"
}

resource "aws_athena_workgroup" "default" {
  name          = local.environment_name
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data.bucket}/${local.athena_results_s3_prefix}"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "expire-athena-results"
    status = "Enabled"

    filter {
      prefix = local.athena_results_s3_prefix
    }

    expiration {
      days = 30
    }
  }
}
