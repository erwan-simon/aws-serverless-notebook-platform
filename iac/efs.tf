resource "aws_efs_file_system" "sessions" {
  tags = {
    Name = "${local.environment_name}_sessions"
  }
}

resource "aws_efs_mount_target" "sessions" {
  for_each        = toset(data.aws_subnets.public.ids)
  file_system_id  = aws_efs_file_system.sessions.id
  subnet_id       = each.value
  security_groups = [aws_security_group.ecs_service.id]
}

resource "aws_efs_access_point" "shared" {
  file_system_id = aws_efs_file_system.sessions.id
  posix_user {
    uid = 0
    gid = 0
  }
  root_directory {
    path = "/shared"
    creation_info {
      owner_uid   = 0
      owner_gid   = 0
      permissions = "755"
    }
  }
  tags = {
    Name = "${local.environment_name}_shared"
  }
}
