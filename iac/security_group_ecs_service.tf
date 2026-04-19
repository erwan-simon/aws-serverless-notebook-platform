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
    description     = "Jupyter from ALB"
    from_port       = 8888
    to_port         = 8888
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  ingress {
    description     = "Jupyter from ALB"
    from_port       = 8443
    to_port         = 8443
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description = "EFS and internal traffic from public subnets"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [for subnet in data.aws_subnet.publics : subnet.cidr_block]
  }

  tags = {
    Name = "${local.environment_name}_ecs_service"
  }
}
