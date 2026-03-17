resource "aws_security_group" "ecs_service" {
  name        = "${local.environment_name}_ecs_service"
  description = "Allow outbound traffic"
  vpc_id      = data.aws_vpc.main.id

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    cidr_blocks = toset(concat([
      for subnet in data.aws_subnet.publics : subnet.cidr_block
    ], split(",", var.cidr_list_to_whitelist)))
  }

  tags = {
    Name = "${local.environment_name}_ecs_service"
  }
}
