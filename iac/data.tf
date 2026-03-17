data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

data "aws_vpc" "main" {
  filter {
    name   = "tag:Name"
    values = toset(["${var.project_name}_network_platform_prod"])
  }
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
  tags = {
    Tier = "Public"
  }
}

data "aws_subnet" "publics" {
  for_each = toset(data.aws_subnets.public.ids)
  id       = each.value
}

data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
  tags = {
    Tier = "Private"
  }
}

data "aws_subnet" "privates" {
  for_each = toset(data.aws_subnets.private.ids)
  id       = each.value
}

data "aws_subnets" "intra" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
  tags = {
    Tier = "Intra"
  }
}

# https://docs.aws.amazon.com/elasticloadbalancing/latest/application/enable-access-logging.html#attach-bucket-policy
data "aws_elb_service_account" "main" {}
