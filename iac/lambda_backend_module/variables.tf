variable "environment_name" {
  type = string
}

variable "lambda_name" {
  type = string
}

variable "code_path" {
  type = string
}

variable "timeout" {
  type    = number
  default = 30
}

variable "memory_size" {
  type    = number
  default = 256
}

variable "environment_variables" {
  type    = map(string)
  default = {}
}

# ARN of the SSM SecureString parameter containing the CloudFront origin verify secret.
# The Lambda reads this at startup and checks the x-origin-verify header on each request
# to ensure traffic comes through CloudFront (and the WAF), not directly to the API Gateway.
# See: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html
variable "origin_verify_secret_ssm_name" {
  type = string
}

variable "iam_policy_json" {
  type = string
}

variable "api_id" {
  type = string
}

variable "api_execution_arn" {
  type = string
}

variable "route_key" {
  type = string
}

variable "authorizer_id" {
  type = string
}

variable "tags_map" {
  type    = map(string)
  default = {}
}

