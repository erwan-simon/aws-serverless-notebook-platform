variable "project_name" {
  type        = string
  description = "Name of the project"
}

variable "git_repository" {
  type        = string
  description = "git respository from which this resource is from"
}

variable "role_to_assume_arn" {
  type        = string
  description = "ARN of the role to assume to deploy the resources"
  default     = ""
}

variable "alerting_emails" {
  type        = string
  description = "Email addresses to receive alerting notifications, separated by commas"
}

variable "cidr_list_to_whitelist" {
  type        = string
  description = "List of CIDR to whitelist to give access to the metabase server, separated by commas"
}
