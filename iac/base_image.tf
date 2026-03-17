locals {
  source_code_path = "${path.module}/../code/docker_images/default/"
  rebuild_trigger = {
    # compute a map composed of the relative file path as key and the file hash as value, for every files of your processing jobs, recursively. Ignoring some irrelevant path patterns
    task_code_hashes = jsonencode({
      for file_path in fileset(local.source_code_path, "**") :
      file_path => filemd5("${path.root}/${trimsuffix(local.source_code_path, "/")}/${file_path}")
      if alltrue([
        for directory_pattern_to_ignore in [
          ".mypy_cache/", ".ipynb_checkpoints/", "__pycache__/", "login_error_message.txt"
        ] :
        !strcontains(file_path, directory_pattern_to_ignore)
      ]) # ignoring path if it contains any of the irrelevant directory
    })
    dockerfile_hash = filemd5("${local.source_code_path}/Dockerfile"),
  }
  # AWS lambda does not detect image change if tag is the same ('latest' for exemple)
  image_tag = sha1(jsonencode(local.rebuild_trigger))
}

module "build_base_image" {
  source = "git::https://github.com/erwan-simon/terraform-module-build-image-and-push-to-ecr//iac/?ref=v1.0.1"

  ecr_name              = "${local.environment_name}_base_image"
  tags_map              = {}
  code_path             = abspath(local.source_code_path)
  image_tag             = local.image_tag
  image_rebuild_trigger = jsonencode(local.rebuild_trigger)
}
