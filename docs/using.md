# Using the platform

This guide is for the **end users** of a deployed instance — the people uploading
notebooks, launching sessions, and scheduling runs from the web portal. For deploying the
platform itself, see [`deploying.md`](deploying.md).

Once your administrator has deployed the stack and created a Cognito user for you, you will
have received an invitation email with a temporary password. Open the CloudFront URL, sign
in, and you're in.

## What you can do

- **Upload Jupyter notebooks** and organize them in folders, with optional free-form labels.
- **Open an interactive session** — JupyterLab or VS Code in the browser — on ECS Fargate,
  with the image, IAM role, and CPU/memory of your choice.
- **Run a notebook headlessly** as a one-off ECS task (Papermill) and view the rendered
  HTML output once it finishes.
- **Schedule a notebook** to run on a cron expression. The scheduler reuses the same image
  and role you would have picked manually.
- **Bring your own image and role** — add a *configuration* from the UI and the platform
  validates it end-to-end before letting anyone use it.

## Working with notebooks

### Upload

From the home page, **+ Add Notebook** uploads an `.ipynb` file. You can:

- Pick a path with `/` separators in the filename — `data/etl/extract.ipynb` shows up under
  the `data/etl/` folder in the listing. Folders are virtual; they exist only as path
  prefixes.
- Add **labels** (free-form, lowercase letters / digits / hyphens, max 12 chars per label).
  Labels are filterable from the listing.

The owner of a notebook is the Cognito user who uploaded it — the listing surfaces it as
the *Owner* column and lets you filter by it.

### View and render

Clicking a notebook opens the read-only viewer. The platform renders the `.ipynb` to HTML
on demand — no kernel required.

### Update settings or delete

The **Edit notebook settings** action on each row lets you change labels and the schedule.
The **Delete** action removes the notebook from S3.

## Configurations

A **configuration** is a triplet picked at run time:

- A **Docker image** (an ECR repo URI). If the URI has no tag or digest (e.g.
  `123456.dkr.ecr.eu-west-1.amazonaws.com/my-image`), the platform automatically resolves
  it to the most recently pushed tag in the repository at run time — push a new image, the
  next session/run picks it up.
- An **IAM role** assumed by the ECS task. The role's permissions are what your code can
  do (read S3 buckets, query Athena, etc.).
- A **default vCPU / memory size**. You can override it when launching a session or
  running a notebook.

Configurations come in two flavors:

| Flavor              | Where it's defined                                                   | Who can edit it       |
|---------------------|----------------------------------------------------------------------|-----------------------|
| Terraform-managed   | Seeded from `MANAGED_CONFIGURATIONS` env var of `list_configurations`| Admin (code only)     |
| Custom              | Added through the UI                                                 | Any signed-in user    |

The bundled `Default` configuration covers the common case (a Jupyter base image with
`papermill`, `awswrangler`, `ipykernel`, plus `code-server`) and ships with both Jupyter
and VS Code support.

### Adding a custom configuration

From the **Configurations** page, **+ Add Configuration** lets you register:

- A name and short description.
- An ECR image URI (with or without a tag).
- An IAM role ARN.
- An optional default vCPU and memory size.

On submit, the platform launches three validations in parallel:

1. **Notebook validation** — runs a hello-world notebook with Papermill against your image
   and role. Fails if your image is missing Papermill or your role can't reach the
   notebook bucket.
2. **Jupyter session validation** — boots JupyterLab in the configuration's image and
   curls `/api`. Fails if your image lacks JupyterLab or the entrypoint clobbers the bind
   address.
3. **VS Code remote session validation** — boots `code-server` and curls `/healthz`. Fails
   if your image doesn't bundle `code-server`.

Each session type is enabled on the configuration **only** if its validation passed. A
configuration can be Notebook-Compatible without being Jupyter-Compatible if your image
ships Papermill but no JupyterLab, and so on. The Configurations list shows the status
explicitly.

#### Security tag requirement

Custom IAM roles and ECR repositories **must** carry a security allowlist tag —
`{project_name}:{domain_name} = allowed` — or the platform refuses to register the
configuration with a clear error message. This is a guardrail that prevents a typo or a
malicious payload from referencing a privileged role or a foreign image.

The tag is enforced by IAM policies on the platform's own roles, not by the application —
even if the UI check were bypassed, the underlying API call would fail. Ask your
administrator to tag the role and repo before retrying:

```bash
aws iam tag-role --role-name my-task-role \
  --tags "Key=poc:jupyter_sandbox,Value=allowed"

aws ecr tag-resource --resource-arn arn:aws:ecr:eu-west-1:123456789012:repository/my-image \
  --tags "Key=poc:jupyter_sandbox,Value=allowed"
```

(Replace `poc` with your `project_name` and `jupyter_sandbox` is the platform's domain
name.)

#### Custom IAM role requirements

Beyond the security tag, the role needs:

- A trust policy allowing `ecs-tasks.amazonaws.com` to assume it.
- Permission to pull the image from ECR and write to CloudWatch Logs.
- Whatever permissions your code needs (S3, Athena, Glue, …).

The bundled default role at
[`iac/iam_role_default_configuration.tf`](../iac/iam_role_default_configuration.tf) is a
working example you can copy.

## Interactive sessions

A session is your own JupyterLab or VS Code, running on ECS Fargate, served at a
per-session URL through CloudFront → ALB.

### Launching a session

From the home page or from a notebook, **Open Session** brings up the launch form:

- **Configuration** — pick from the list. Only configurations whose corresponding
  session-type validation succeeded show up.
- **Session type** — Jupyter session or VS Code remote session.
- **vCPU / Memory** — default comes from the configuration; you can override up to the
  platform's max (4 vCPU / 16 GB by default).

Click **Launch**. The session takes 30–90 seconds to come up — image pull, ALB target
registration, JupyterLab/code-server boot. The UI polls and switches to **Open
JupyterLab** / **Open VS Code** when it's ready.

You can have **one session at a time**. The session card on the home page surfaces the
running session with quick **Open**, **Details**, and **Stop** actions.

### Idle behavior

| Session type | Auto-stop on inactivity? | Notes                                                          |
|--------------|--------------------------|----------------------------------------------------------------|
| Jupyter      | Yes (default 60 min)     | JupyterLab itself shuts down after no kernel activity, then ECS reaps the task. |
| VS Code      | No                       | Code-server has no inactivity timeout. **Stop it manually** when you're done.  |

Stopped sessions are gone forever — the ECS task, ALB listener rule, and target group are
cleaned up. Your files in `/home/user` and `/shared` survive (see
[Persistent storage](#persistent-storage)).

### Session details

The Session view shows:

- The image and IAM role used.
- The vCPU / memory.
- Links to **CloudWatch Logs** (for the running container) and **CloudWatch Metrics** for
  infra resource monitoring.

## Persistent storage

Every session mounts EFS at two paths:

- **`/home/user`** — your private home directory. A dedicated EFS access point per Cognito
  user, created on first session, reused afterwards. Files survive between sessions and
  across image changes. JupyterLab opens in this directory by default.
- **`/shared`** — read/write for all users. Use it for reference data, shared notebooks,
  team scratch.

EFS is pay-per-GB, so it's the right place for working files but a bad place for archival
data. For datasets, write to S3 (Athena reads from there) and use EFS only for code and
scratch.

## Running a notebook headlessly

From a notebook view, **Run** runs the notebook as a one-off ECS task with Papermill and
saves the rendered HTML output. You pick the same configuration / size / role you would
for a session.

The task takes a few seconds to spin up, then runs to completion or failure. The
**Executions** drawer on the notebook view (and the per-notebook Executions page) shows:

- Status (running, succeeded, failed).
- Duration.
- Owner of the run.
- Link to the rendered HTML output (for successful runs).
- Link to CloudWatch logs for the executing container.

Executions are kept in DynamoDB and never auto-deleted; the rendered HTML lives in S3.

## Scheduling a notebook

From the **Schedule** tab on a notebook view, you set up recurring execution:

- **Cron expression** — standard EventBridge Scheduler cron syntax,
  `cron(min hour day-of-month month day-of-week year)`. Example: `cron(0 9 * * ? *)` for
  every day at 9:00.
- **Timezone** — IANA name (e.g. `Europe/Paris`); defaults to `UTC`.
- **Configuration / image / role / size** — same picker as a manual run. The scheduler
  uses these settings every time it fires.

The schedule is materialized as an EventBridge Scheduler rule that calls the
`run_notebook` Lambda. Each scheduled run shows up as a regular execution in the
notebook's Executions list, marked as `scheduled` (vs `manual`) — you get the same
rendered HTML and CloudWatch logs as a manual run.

To stop scheduling, hit **Unschedule** on the same tab. This removes the EventBridge rule
but keeps existing executions intact.

## Troubleshooting

### "I can't see the configuration I just added in the session picker."

Configurations only appear in a session-type picker once the corresponding validation has
**succeeded**. Open the **Configurations** page — each card shows the status of all three
validations. If one is still `Running`, wait for it (under a minute usually). If it's
`Failed`, click into it to see the CloudWatch logs link.

### "My session won't start (or the URL returns 502 / 404)."

Sessions take 30–90 seconds to come up. The first symptoms of a failure:

- 502 from the ALB → the container is still booting, or it crashed. Check the session's
  CloudWatch Logs link.
- 404 → the ALB listener rule isn't there yet, or the session was already stopped.
  Refresh the session card.
- WAF block (CloudFront error page) → your IP isn't in `cidr_list_to_whitelist`. Ask your
  admin.

### "The platform rejects my custom IAM role / ECR repo."

The role or repo is missing the security allowlist tag. See
[Security tag requirement](#security-tag-requirement) above and ask your admin to add it.

### "My VS Code session is still running and I'm not using it."

Code-server has no inactivity timeout. Stop the session manually from the home page.
