# AWS Serverless Notebook Platform

A self-hosted, serverless platform for managing and executing Jupyter notebooks on AWS. Built entirely with Terraform, it provides a web portal to upload notebooks, launch interactive Jupyter sessions on ECS Fargate, run notebooks as batch jobs, and schedule recurring executions — all behind Cognito authentication and CloudFront.

## Features

- **Notebook Management** — Upload, organize in folders, delete, and view rendered notebooks
- **Interactive Sessions** — Launch on-demand Jupyter environments on ECS Fargate with configurable CPU/memory/image/IAM role
- **Batch Execution** — Run notebooks as one-off ECS tasks with real-time status tracking
- **Scheduling** — Cron-based recurring execution via EventBridge Scheduler
- **Authentication** — Cognito User Pool with OAuth2 PKCE flow
- **Security** — WAF (rate limiting, geo-blocking, IP whitelist), CloudFront origin verification, API Gateway JWT authorization and throttling
- **Monitoring** — CloudWatch alarms on WAF, Lambda errors, ECS task failures, with SNS email notifications
- **Persistent Storage** — EFS filesystem available across sessions with dedicated and shared space for each users
- **Multi-environment** — Terraform workspaces for dev/staging/prod isolation

### High-level overview

```
User → WAF → CloudFront ──→ S3 (frontend SPA)
                         └─→ API Gateway (HTTP API, JWT auth)
                              └─→ Lambda functions
                                   ├── DynamoDB (notebooks, executions)
                                   ├── S3 (notebook files, rendered HTML)
                                   └── ECS Fargate (sessions, batch runs)
                                        └── EFS (persistent storage)

EventBridge ──→ Lambda (status sync, session cleanup)
           └──→ SNS (task failure alerts)
CloudWatch Alarms ──→ SNS ──→ Email
EventBridge Scheduler ──→ Lambda (scheduled notebook runs)
```

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.0
- AWS CLI configured with appropriate credentials
- An AWS account with permissions to create: VPC resources, ECS, Lambda, S3, DynamoDB, CloudFront, WAF, Cognito, EventBridge, SNS, EFS, IAM roles, CloudWatch, API Gateway, ECR, SSM
- An existing VPC with public subnets tagged `Tier = "Public"` and the VPC tagged with `Name = "{project_name}_network_platform_prod"`
- Docker (for building Lambda and Jupyter container images)

## Project Structure

```
.
├── code/
│   ├── backend/                    # Lambda function handlers (Python)
│   │   ├── upload_notebook/
│   │   ├── list_notebooks/
│   │   ├── delete_notebook/
│   │   ├── render_notebook/
│   │   ├── schedule_notebook/
│   │   ├── unschedule_notebook/
│   │   ├── list_executions/
│   │   ├── run_notebook/
│   │   ├── get_execution_status/
│   │   ├── run_session/
│   │   ├── get_session/
│   │   ├── get_session_status/
│   │   └── stop_session/
│   ├── frontend/                   # Static SPA (HTML + vanilla JS)
│   │   ├── index.html              # Notebook list, upload, session launcher
│   │   ├── notebook.html           # Notebook viewer, run, schedule
│   │   ├── run.html                # Session configuration
│   │   ├── executions.html         # Execution history
│   │   ├── execution_status.html   # Execution tracking
│   │   ├── status.html             # Session launch status
│   │   ├── auth.js                 # Cognito PKCE authentication
│   │   └── config.js.tpl           # Terraform-templated configuration
│   ├── docker_images/default/      # Base Jupyter Docker image
│   └── lambda_cleanup_idle_session/ # Session cleanup Lambda
├── iac/                            # Terraform root module
│   ├── lambda_backend_module/      # Reusable Lambda deployment module
│   ├── sandbox_instance_module/    # Reusable ECS Jupyter instance module
│   ├── terraform.tfvars            # Variable values
│   └── *.tf                        # Infrastructure definitions
├── architecture_functional.drawio
├── architecture_technical.drawio
└── LICENSE                         # CC BY-NC 4.0
```

## Deployment

All Terraform commands run from the `iac/` directory:

```bash
cd iac
```

### 1. Configure variables

Edit `terraform.tfvars`:

```hcl
project_name           = "myproject"
git_repository         = "https://github.com/you/your-repo"
alerting_emails        = "you@example.com,team@example.com"
cidr_list_to_whitelist = "1.2.3.4/32,5.6.7.8/32"
```

### 2. Configure the Terraform backend

Edit the `backend "s3"` block in `terraform.tf` with your own S3 bucket, DynamoDB table, and region.

### 3. Initialize and deploy

```bash
terraform init

# Create or select a workspace (workspace = environment name)
terraform workspace new prod
# or
terraform workspace select prod

terraform plan
terraform apply
```

### 4. Access the platform

```bash
# Get the CloudFront URL (main entry point)
terraform output cloudfront_url

# Get the API Gateway URL (direct API access)
terraform output api_gateway_url
```

Open the CloudFront URL in your browser. You will be redirected to Cognito for authentication. Sign up with your email to create an account.

## Configuration

### Terraform Variables

| Variable | Type | Description |
|----------|------|-------------|
| `project_name` | `string` | Project name, used in all resource naming |
| `git_repository` | `string` | Git repository URL (for resource tagging) |
| `alerting_emails` | `string` | Comma-separated emails for SNS alert subscriptions |
| `cidr_list_to_whitelist` | `string` | Comma-separated CIDRs allowed through WAF |
| `role_to_assume_arn` | `string` | (Optional) IAM role ARN to assume for deployment |

### Key Locals

Defined in `iac/locals.tf`:

| Local | Default | Description |
|-------|---------|-------------|
| `session_idle_timeout_minutes` | `60` | Minutes before idle sessions are cleaned up |
| `task_default_vcpu` | `256` | Default vCPU for tasks (256 = 0.25 vCPU) |
| `task_default_memory` | `512` | Default memory in MB |
| `task_max_vcpu` | `4096` | Max vCPU users can select (4096 = 4 vCPU) |
| `task_max_memory` | `16384` | Max memory users can select (16 GB) |

### Adding Custom Docker Images

Custom Docker images allow you to provide pre-installed libraries, tools, or configurations tailored to specific use cases (e.g. a data science image with pandas/scikit-learn, a Spark image, etc.). Users can then select the appropriate image when launching a session or running a notebook.

Add ECR image URIs to the `available_ecr_images` list in `iac/locals.tf`:

```hcl
available_ecr_images = [
  "${module.build_base_image.ecr_url}:${local.image_tag}",
  "123456789.dkr.ecr.eu-west-1.amazonaws.com/my-custom-jupyter:latest",
]
```

Images must be hosted in ECR and accessible by the IAM role assigned to the task (see below).

### Adding Custom IAM Roles

Custom IAM roles allow you to grant different AWS permissions depending on the workload. For example, a role with read-only access to a specific S3 bucket for one team, and a role with Athena + Glue permissions for another. Users select the role when launching a session or running a notebook.

Add role ARNs to the `available_iam_roles` list in `iac/locals.tf`:

```hcl
available_iam_roles = [
  aws_iam_role.ecs_execution.arn,
  "arn:aws:iam::123456789:role/my-custom-role",
]
```

Custom roles **must**:
- Have a trust policy allowing `ecs-tasks.amazonaws.com` to assume the role
- Have permission to pull the Docker image from ECR (`ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`)
- Have permission to write CloudWatch logs

Refer to the default role in `iac/iam_role_ecs_execution.tf` for a working example.

## Base Docker Image

The default Jupyter image is built from `code/docker_images/default/Dockerfile`:

```dockerfile
FROM jupyter/base-notebook:x86_64-ubuntu-22.04
RUN apt-get update && apt-get install -y awscli
RUN pip install --no-cache-dir papermill
```

It includes:
- Jupyter Notebook
- AWS CLI
- Papermill (for notebook execution)

The image tag is a SHA1 hash of the build context, so any file change triggers a rebuild on `terraform apply`.

## API Endpoints

All routes require Cognito JWT authentication and are proxied through CloudFront.

### Notebooks

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/notebooks` | List all notebooks |
| `POST` | `/api/notebooks` | Upload a notebook |
| `DELETE` | `/api/notebooks/{id}` | Delete a notebook |
| `GET` | `/api/notebooks/render` | Render notebook to HTML |
| `GET` | `/api/notebooks/{notebook_id}/executions` | List executions for a notebook |
| `POST` | `/api/notebooks/{id}/schedule` | Schedule recurring execution |
| `DELETE` | `/api/notebooks/{id}/schedule` | Remove schedule |

### Executions

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/executions` | Run a notebook |
| `GET` | `/api/executions/{id}/status` | Get execution status |

### Sessions

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/sessions` | Launch a Jupyter session |
| `GET` | `/api/sessions/me` | Get current user's session |
| `GET` | `/api/sessions/{service_name}/status` | Get session status |
| `DELETE` | `/api/sessions/{service_name}` | Stop a session |

## Security

### Network

- **WAF v2** (CloudFront scope) — Rate limiting (100 req/5min), geo-blocking (configurable), IP whitelist
- **CloudFront origin verification** — Random secret in SSM Parameter Store, injected as custom header by CloudFront, verified by every Lambda
- **API Gateway throttling** — 10 burst / 5 rate globally, 3 burst / 1 rate for expensive operations
- **Security Group** — ECS tasks only accessible from whitelisted CIDRs

### Authentication & Authorization

- **Cognito User Pool** — Email-based signup with verification, OAuth2 authorization code flow with PKCE
- **JWT validation** — API Gateway JWT authorizer validates tokens on every request
- **IAM roles** — Granular per-function Lambda roles, configurable ECS task execution roles

### Data

- **S3** — Server-side encryption (AES-256), public access blocked
- **DynamoDB** — Pay-per-request billing, no public access
- **EFS** — Mounted only within VPC, root-owned shared access point

## Monitoring & Alerting

| Alert | Trigger | Destination |
|-------|---------|-------------|
| WAF blocked requests | > 50 blocked in 5 min | SNS (us-east-1) |
| Lambda errors | Any error (per function) | SNS (eu-west-1) |
| ECS task failure | Non-zero exit code, TaskFailedToStart | SNS (eu-west-1) |

All alerts are sent to email addresses configured in `alerting_emails`. SNS topics exist in two regions because WAF/CloudFront metrics are only available in us-east-1.

CloudWatch logs are collected for:
- All Lambda functions (14-day retention)
- API Gateway access logs (14-day retention)
- ECS cluster (Container Insights enhanced mode)
- Per-sandbox instance logs

## Resource Naming Convention

All resources follow the pattern:

```
{project_name}_{domain_name}_{workspace}_{resource_name}
```

Example: `poc_jupyter_sandbox_prod_ecs_cluster`

The Terraform workspace maps to the environment/stage name.

## License

This project is licensed under the [Creative Commons Attribution-NonCommercial 4.0 International](LICENSE) license (CC BY-NC 4.0).
