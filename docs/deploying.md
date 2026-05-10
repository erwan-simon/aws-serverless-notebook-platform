# Deploying the platform

This guide is for the platform / DevOps engineer standing the platform up in a real AWS
account. For the end-user perspective (uploading notebooks, launching sessions, scheduling),
see [`using.md`](using.md).

The whole stack is provisioned by the Terraform root module under [`iac/`](../iac). One
`terraform apply` builds Docker images, pushes them to ECR, deploys 17 Lambda functions
behind API Gateway, an ECS cluster, an ALB, a CloudFront distribution with WAF, a Cognito
user pool, EFS, DynamoDB tables, S3 buckets, and the supporting IAM and CloudWatch glue.

## Prerequisites

### Tooling

- **AWS CLI** configured with credentials for the target account.
- **Terraform** `>= 1.0` with the AWS provider `>= 5.60.0`.
- **Docker**, running locally — Terraform invokes it to build the Lambda images and the
  default notebook base image. No remote build pipeline is required.
- A user/role with rights to create the resource types listed below.

### IAM rights for the deploying principal

The principal running `terraform apply` must be able to create and manage:

- Networking: ALB, security groups, CloudFront, WAF v2 (in `us-east-1` and `eu-west-1`).
- Compute: ECS cluster, services, task definitions; Lambda functions; EventBridge rules
  and Scheduler resources.
- Storage: S3 buckets, EFS filesystems and access points, DynamoDB tables.
- API: API Gateway HTTP APIs, Cognito user pools.
- Observability: CloudWatch log groups, metric alarms, SNS topics and subscriptions.
- IAM: roles, policies, instance profiles for ECS execution and per-Lambda roles.
- Packaging: ECR repositories.
- Configuration: SSM Parameter Store (for the CloudFront origin secret).

If you are deploying through a delegated role, set `role_to_assume_arn` in
`terraform.tfvars` (see [Terraform variables](#terraform-variables)).

### Pre-existing infrastructure

The framework expects these resources to already exist in the target account:

- **Terraform state backend.** An S3 bucket and a DynamoDB table for state and locking.
  Both are referenced from `backend.hcl` (see below).
- **VPC.** A VPC tagged `Name = {project_name}_network_platform_prod`, containing public
  subnets tagged `Tier = Public`. The platform looks up the VPC and subnets by tag, not by
  ID — a misnamed VPC produces an opaque "no matching VPC found" error during
  `terraform plan`.

The default deployment places the ALB and ECS tasks in the public subnets (no NAT gateway
required). If you want to move them to private subnets, you need a NAT gateway in the VPC
and the corresponding edits in `iac/data.tf` and the resources that consume `data.aws_subnets.public`.

## Configure

```bash
cd iac
cp backend.hcl.example      backend.hcl
cp terraform.tfvars.example terraform.tfvars
$EDITOR backend.hcl terraform.tfvars
```

`backend.hcl` points Terraform at your remote state:

```hcl
bucket         = "your-terraform-state-bucket"
dynamodb_table = "your-terraform-state-lock-table"
```

`terraform.tfvars` holds the deployment variables:

```hcl
project_name   = "myproject"
git_repository = "https://github.com/you/your-repo"

alerting_emails        = "you@example.com,team@example.com"
cidr_list_to_whitelist = "1.2.3.4/32,5.6.7.8/32"

# Optional — assume an IAM role for deployment
# role_to_assume_arn = "arn:aws:iam::123456789012:role/my-deploy-role"
```

Both files are gitignored by default — your secrets and IPs stay local.

## Initialize and deploy

```bash
terraform init -backend-config=backend.hcl

terraform workspace new prod        # or `terraform workspace select prod` after the first time
terraform plan
terraform apply
```

The first apply takes 10–15 minutes — most of that is Docker image builds and CloudFront
distribution provisioning.

When it finishes, two outputs you'll use:

```bash
terraform output cloudfront_url     # main entry point — open this in your browser
terraform output api_gateway_url    # direct API Gateway URL (debug only; CloudFront fronts everything)
```

## Create the first user

The Cognito user pool is configured `allow_admin_create_user_only = true` — no public
sign-up. Create the first user from the AWS console or the CLI:

```bash
USER_POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 \
  --query "UserPools[?Name=='${PROJECT_NAME}_jupyter_sandbox_prod'].Id" --output text)

aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username you@example.com \
  --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
```

Cognito sends an invitation email with a temporary password. The first sign-in forces a
password reset — after that, open the CloudFront URL and you're in.

## Terraform variables

Defined in [`iac/variables.tf`](../iac/variables.tf):

| Variable                 | Type     | Required | Description                                                                       |
|--------------------------|----------|----------|-----------------------------------------------------------------------------------|
| `project_name`           | `string` | yes      | Used in every resource name and as the IAM/ECR security tag key prefix.           |
| `git_repository`         | `string` | yes      | URL of the source repository — applied as a default tag on every resource.        |
| `alerting_emails`        | `string` | yes      | Comma-separated email addresses subscribed to the SNS alert topics.               |
| `cidr_list_to_whitelist` | `string` | yes      | Comma-separated CIDRs allowed through the WAF. Everything else is blocked.        |
| `role_to_assume_arn`     | `string` | no       | If set, the AWS provider assumes this role for all API calls. Default: empty.     |

## Key locals

Defined in [`iac/locals.tf`](../iac/locals.tf). Edit them in code if you need to override:

| Local                          | Default                  | What it controls                                                                       |
|--------------------------------|--------------------------|----------------------------------------------------------------------------------------|
| `domain_name`                  | `"jupyter_sandbox"`      | Second segment of every resource name. Rename only if you also change CI / state path. |
| `session_idle_timeout_minutes` | `60`                     | JupyterLab inactivity timeout — see [Idle session cleanup](#idle-session-cleanup).     |
| `task_default_vcpu`            | `512`                    | Default vCPU when a config or schedule does not specify (512 = 0.5 vCPU).              |
| `task_default_memory`          | `1024`                   | Default memory in MB.                                                                  |
| `task_max_vcpu`                | `4096`                   | Upper bound the UI lets users select (4096 = 4 vCPU).                                  |
| `task_max_memory`              | `16384`                  | Upper bound the UI lets users select (16 GB).                                          |
| `security_tag_key`             | `"{project}:{domain}"`   | Tag key required on custom IAM roles and ECR repos — see [Security model](#security-model). |
| `security_tag_value`           | `"allowed"`              | Required value for the security tag.                                                   |

## Stages, workspaces, and naming

Stages (`dev`, `staging`, `prod`, …) are derived **at deployment time** from the active
Terraform workspace — never hardcoded. Resource names follow:

```
{project_name}_{domain_name}_{workspace}_{resource_name}
```

For example, with `project_name = "poc"` and the `prod` workspace, the ECS cluster is
`poc_jupyter_sandbox_prod_ecs_cluster`. Switching environments locally:

```bash
terraform workspace select dev      # or `terraform workspace new dev` the first time
terraform apply
```

Skipping the workspace selection deploys against `default`, which is annoying to clean up
later — always select first.

## Security model

### CloudFront → ALB origin lockdown

The ALB security group inbound is restricted to the AWS-managed CloudFront origin-facing
prefix list, so the ALB itself is unreachable from the public internet. CloudFront also
injects an `x-origin-verify` header (random secret in SSM) on every request to the API
Gateway origin; every Lambda validates the header at the start of the handler. Combined,
these prevent direct access to the API Gateway URL or the ALB DNS — clients must go
through CloudFront, which means they go through the WAF.

### Tag-based allowlist for custom configurations

Custom configurations let users provide their own image and IAM role. To prevent a typo or
a malicious payload from referencing a privileged role or a foreign image, the framework
enforces a **tag-based allowlist**:

- `run_notebook` and `run_session` Lambdas can only `iam:PassRole` on roles tagged
  `{project_name}:{domain_name} = allowed`.
- The ECS execution role can only pull from ECR repositories carrying the same tag.
- `add_configuration` and `update_configuration` Lambdas pre-validate the tags and reject
  the request with a clear error if missing.

The bundled default role and base image are tagged automatically. Any custom resource
referenced through the UI (or seeded as a Terraform-managed configuration) must carry the
same tag — see the example role in
[`iac/iam_role_default_configuration.tf`](../iac/iam_role_default_configuration.tf).

### Authentication and authorization

- **Cognito User Pool** — email-based, admin-only sign-up, OAuth2 PKCE flow.
- **API Gateway JWT authorizer** — validates the Cognito access token on every request.
- **Granular per-function IAM** — every Lambda gets a dedicated role with the minimum
  policy required for its handler.

### WAF and throttling

- **WAF v2 on CloudFront** (in `us-east-1`) — rate limiting, geo-blocking (configurable),
  IP allowlist driven by `cidr_list_to_whitelist`. CloudFront sees real client IPs; no
  WAF is attached to the ALB because the ALB only ever sees CloudFront IPs.
- **API Gateway throttling** — 10 burst / 5 rate per second globally; 3 burst / 1 rate
  per second on expensive routes (`POST /api/sessions`, `DELETE /api/sessions/{name}`,
  `POST /api/executions`).

## Monitoring and alerting

| Alarm                          | Trigger                                          | Region        |
|--------------------------------|--------------------------------------------------|---------------|
| `*_waf_blocked_requests`       | > 50 blocked requests in 5 min                   | `us-east-1`   |
| `*_lambda_errors` (per Lambda) | Any non-zero error count over 5 min              | `eu-west-1`   |
| `*_ecs_task_failure`           | ECS task exits non-zero, or `TaskFailedToStart`  | `eu-west-1`   |

All alarms publish to an SNS topic that is email-subscribed to every address in
`alerting_emails`. SNS topics exist in both regions because WAF/CloudFront metrics live
only in `us-east-1`.

CloudWatch logs are collected for:

- Every Lambda function (14-day retention).
- API Gateway access logs (14-day retention).
- The ECS cluster (Container Insights enhanced mode).

## Operational notes

### Idle session cleanup

JupyterLab is started with `--ServerApp.shutdown_no_activity_timeout` and
`--MappingKernelManager.cull_idle_timeout` set to `session_idle_timeout_minutes * 60`. When
JupyterLab exits, the ECS task stops; an EventBridge rule routes the resulting `STOPPED`
event to a `cleanup_idle_session` Lambda that tears down the ALB listener rule, the target
group, and the ECS service.

**VS Code remote sessions do not have a built-in inactivity shutdown.** The
`session_idle_timeout_minutes` local does not apply to them — users must stop them
manually from the UI, or you must implement an external watchdog. Keep this in mind for
cost projection.

### Costs to watch

- **ECS Fargate** — billed per second per running session. With the default 60-min
  Jupyter idle timeout, an unattended Jupyter session costs roughly the size you picked
  for one hour. Code-server sessions stay up indefinitely.
- **NAT gateway** — only relevant if you switch to private subnets. The default public
  subnet deployment avoids it entirely.
- **CloudFront + WAF** — a few dollars a month per environment; not significant.
- **Athena** — the default IAM role grants Athena access; user queries are not capped by
  this stack. Wire AWS Budgets if `prod` users have access to large datasets.
- **EFS** — pay-per-GB; use for working files only, not for archival data.

### Persistent storage

EFS is mounted at `/home/user` in every session. Each user gets a dedicated access point
(created on first session, reused afterwards), so files persist between sessions and across
restarts. A second mount, `/shared`, gives team-wide read/write access and is provisioned
once via a Terraform-managed access point.

## Common gotchas

- **VPC tags missing.** The platform looks up the VPC by `Name = {project}_network_platform_prod`
  and subnets by `Tier = Public`. A misnamed VPC produces an opaque "no matching VPC"
  error during `terraform plan`.
- **First Cognito user not created.** Sign-up is admin-only — opening the CloudFront URL
  before creating a user gets you a Cognito error page. Create the user first.
- **Custom configuration rejected at create time.** The allowlist tag is the most common
  cause: the IAM role or ECR repo you referenced does not carry
  `{project_name}:{domain_name} = allowed`. Add the tag and retry.
- **Code-server session never stops.** Inactivity shutdown only applies to JupyterLab.
  Stop code-server sessions from the UI when you're done, or wire an external watchdog.
- **`terraform destroy` fails on the CloudFront distribution.** CloudFront takes ~15 min
  to disable before it can be deleted; the GitLab CI handles this with a manual
  `destroy-service` job that targets the destroy-blockers explicitly. From the CLI, it
  usually requires running `terraform destroy` twice with a wait in between.
- **Workspace forgotten.** Without `terraform workspace select`, you deploy against
  `default` — annoying to clean up. Always select first.
