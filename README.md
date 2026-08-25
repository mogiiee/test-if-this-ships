# Groundskeeper

Internal GitHub PR reviewer for appointment bridges (`appt_sys_*`). Sparse. Consequence-first. Points developers at real risk; does not nitpick clean code.

**Stack:** Python 3.14 · FastAPI · Anthropic Claude · GitHub API via env credentials

---

## UI?

**No.** Reviews appear as GitHub PR comments. The only HTTP extras are `GET /health` and FastAPI `/docs` (API schema, not a review UI).

Trigger: comment `@groundskeeper review` on a PR, or `POST /review`.

---

## How it works

```
@groundskeeper review
        │
        ▼
Load PR + diff + package.json from GitHub (token from env)
        │
        ▼
Parse appt-bridge-core version from package.json (#vX.Y.Z)
        │
        ▼
Fetch that tag from CORE_REPO on GitHub (never node_modules)
        │
        ▼
Load rules from context/*.md
        │
        ▼
TRIAGE (always) → then ONE of:
  • deep review (Opus)  — multiple files OR whole flow
  • Sonnet              — single file, but triage says it needs more
  • triage model only   — small one-file change
        │
        ▼
Post summary (+ inline comments when path:line exists)
```

### Model routing (not “always Sonnet”)

| When | Tier | Env | Default ID |
|---|---|---|---|
| Always first | triage | `MODEL_TRIAGE` | `claude-haiku-4-5` (latest Haiku) |
| 2+ files **or** complete flow | **deep** | `MODEL_OPUS` | `claude-opus-5` |
| 1 file, non-trivial | sonnet | `MODEL_SONNET` | `claude-sonnet-5` |
| 1 file, simple | triage only | `MODEL_TRIAGE` again | `claude-haiku-4-5` |

Sonnet is never the default entry point. Triage always runs; it decides sonnet vs deep vs “triage is enough”.

---

## Rules (`context/`)

| File | What it is |
|---|---|
| `how-we-review.md` | Tone: silence OK, sparse, developers smarter than model |
| `always-flag-these.md` | Must always comment if present (logout stub, try/catch, originalRequest, …) |
| `coding-rules.md` | How bridge code should be written |
| `how-core-works.md` | What `appt-bridge-core` does (lifecycle, verify routing) |
| `appointment-flows.md` | Flow names: auth, verify, create, change, cancel, logout, … |

Every `context/*.md` is loaded into the prompt. Restart the server after edits.

### What “always flag” means

`always-flag-these.md` is the short list of **non-negotiable** issues. If the PR has one, Groundskeeper must leave a finding. Everything else can stay quiet if the change is fine.

### Add a rule

1. Edit the matching file, or add a new `context/your-topic.md`.
2. Write plain English: what to flag + what breaks if it ships.
3. If it must never be skipped, add it to `always-flag-these.md`.
4. Restart Groundskeeper. Run `@groundskeeper review` on a PR.

### Edit / remove

- Edit markdown in place.
- Delete a file to drop that pack from the prompt.
- New `*.md` under `context/` is picked up automatically (no code change).

---

## Setup

Python **3.14+**.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # put GitHub + Anthropic secrets here
python -m groundskeeper
```

```bash
curl http://localhost:8787/health
python scripts/selfcheck.py
```

### Env (GitHub + Claude)

All GitHub access is from environment variables — nothing hardcoded.

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude |
| `GITHUB_TOKEN` | PAT: read `CORE_REPO`, load PRs, post comments, `POST /review` |
| `GITHUB_APP_ID` | GitHub App (webhooks) |
| `GITHUB_APP_PRIVATE_KEY` | App PEM (`\n` for newlines in env) |
| `GITHUB_WEBHOOK_SECRET` | Webhook HMAC |
| `CORE_REPO` | default `QdRepo/appt_bridge_core` |
| `BOT_LOGIN` | default `groundskeeper` |
| `MODEL_TRIAGE` | default `claude-haiku-4-5` |
| `MODEL_SONNET` | default `claude-sonnet-5` |
| `MODEL_OPUS` | default `claude-opus-5` |
| `PORT` | default `8787` |

Webhook URL for the App: `https://<host>/webhooks/github`  
App permissions: Pull requests R/W, Contents read, Issues write, Metadata read. Event: Issue comment.

You need **both**: a PAT (`GITHUB_TOKEN`) to read private `QdRepo/appt_bridge_core`, and a GitHub App so `@groundskeeper review` on a PR fires a webhook.

### A. Personal access token (`GITHUB_TOKEN`)

Fine-grained PAT (preferred). Docs: [Creating a fine-grained personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token)

1. Open [https://github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta) (GitHub → avatar → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens**).
2. **Generate new token**.
3. Token name: `groundskeeper`.
4. Expiration: pick one (90 days is fine; you will rotate).
5. Resource owner: **QdRepo** (not your personal account). If QdRepo is missing, an org owner must allow PATs: [https://github.com/organizations/QdRepo/settings/personal-access-tokens](https://github.com/organizations/QdRepo/settings/personal-access-tokens)
6. Repository access: **Only select repositories**. Select at least:
   - `QdRepo/appt_bridge_core`
   - every `appt_sys_*` repo you want to review (or **All repositories** if that is simpler internally)
7. Permissions → Repository:
   - **Contents:** Read
   - **Pull requests:** Read and write
   - **Issues:** Read and write (PR comments use the Issues API)
   - **Metadata:** Read (automatic)
8. **Generate token**. Copy it once. Put it in `.env` as `GITHUB_TOKEN=ghp_…` or `github_pat_…`.
9. If QdRepo uses SAML SSO: on [https://github.com/settings/tokens](https://github.com/settings/tokens) click **Enable SSO** next to the token and authorize **QdRepo**.

Classic PAT alternative: [https://github.com/settings/tokens](https://github.com/settings/tokens) → **Generate new token (classic)** → scope `repo` → Enable SSO for QdRepo if asked. Broader than needed; use only if fine-grained is blocked.

### B. GitHub App (webhook bot)

Docs: [Registering a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app) · [Installing a GitHub App](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app)

Create it **on the QdRepo org** so it can be installed on org repos:

**Create App URL:** [https://github.com/organizations/QdRepo/settings/apps/new](https://github.com/organizations/QdRepo/settings/apps/new)  
(If you lack permission, an org owner must open that page. Personal-account fallback: [https://github.com/settings/apps/new](https://github.com/settings/apps/new) — then the App still has to be installed on QdRepo.)

1. Open the create-app URL above.
2. **GitHub App name:** `Groundskeeper` (must be unique on GitHub). This becomes the mention slug; keep `BOT_LOGIN=groundskeeper` in `.env` matching the slug (lowercase, no spaces). If GitHub assigns `groundskeeper-bot` or similar, set `BOT_LOGIN` to that slug (the part after `@`).
3. Homepage URL: your AWS URL later, or `https://github.com/QdRepo` for now.
4. **Webhook:**
   - Active: **checked**
   - Webhook URL: `https://<your-aws-https-host>/webhooks/github`  
     No public URL yet? Use a tunnel for local test ([ngrok](https://ngrok.com/) → `https://<ngrok>/webhooks/github`) or uncheck Active until AWS is up. Mentions will not auto-fire without a reachable webhook.
   - **Webhook secret:** generate a long random string (e.g. `openssl rand -hex 32`). Save it as `GITHUB_WEBHOOK_SECRET` in `.env`. Same value must be in the App form.
5. **Permissions** → Repository:
   - **Contents:** Read-only
   - **Issues:** Read and write
   - **Pull requests:** Read and write
   - **Metadata:** Read-only (required)
6. **Permissions** → Organization: leave none.
7. **Subscribe to events:**
   - **Issue comment** (required — this is `@groundskeeper review`)
   - Optional later: **Pull request** (only if you add auto-review on open)
8. **Where can this GitHub App be installed?** Only on this account (QdRepo).
9. **Create GitHub App**.
10. On the App page, copy **App ID** → `GITHUB_APP_ID` in `.env`. App settings live at `https://github.com/organizations/QdRepo/settings/apps/<slug>` (or **GitHub Apps** in org settings).
11. **Generate a private key** → download the `.pem`. Do not commit it. Either:
    - keep the file and later mount it, or
    - paste into `.env` as `GITHUB_APP_PRIVATE_KEY` with literal `\n` for newlines, e.g. `-----BEGIN RSA PRIVATE KEY-----\nMIIE…\n-----END RSA PRIVATE KEY-----`
12. **Install App:** App page → **Install App** → **QdRepo** → **Only select repositories** → pick `appt_bridge_core` if you want, plus every `appt_sys_*` to review → **Install**.  
    Direct install URL after creation: `https://github.com/apps/<slug>/installations/new`
13. Confirm the bot can comment: after install, GitHub will post as `Groundskeeper[bot]`. Mention as `@<slug>` (usually `@groundskeeper`).

You still keep `GITHUB_TOKEN` even after the App exists: the App may not be installed on `appt_bridge_core`, and core fetch uses the PAT.

### Trigger

```text
@groundskeeper review
```

```bash
curl -X POST http://localhost:8787/review \
  -H 'content-type: application/json' \
  -d '{"owner":"QdRepo","repo":"appt_sys_americold2","number":123}'
```

---

## Deploy

**No, it does not have to be on AWS.** Anything that can run a Python process with HTTPS (or a tunnel) works.

Groundskeeper is a **small always-on HTTP service**. GitHub App webhooks need a public URL:

`https://<host>/webhooks/github`

| Where | Fit |
|---|---|
| **Railway / Render / Fly.io / any VPS** | Best match for current design (webhook App) |
| **AWS** (ECS, App Runner, EC2, Lambda+API GW) | Fine if you already live there — not required |
| **Your laptop + Cloudflare Tunnel / ngrok** | Fine for testing |
| **GitHub Actions** | Possible, but different shape (see below) |
| **“On GitHub” as a hosted server** | **No** — GitHub does not host long-running apps |

### Can it run on GitHub itself?

**Not as this webhook server.** GitHub has no place to park a FastAPI process.

**Yes as GitHub Actions** (different trigger model):

- Workflow listens for `issue_comment` containing `@groundskeeper review` (or `workflow_dispatch` / PR events).
- Job installs Python, runs a one-shot review script, posts comments with `GITHUB_TOKEN` / App token.
- Secrets live in repo/org Actions secrets (`ANTHROPIC_API_KEY`, etc.).
- Pros: no separate host. Cons: cold start every run, Actions minutes cost, webhook App path in this repo is unused unless you keep both.

Today’s code is built for the **hosted webhook** path (`python -m groundskeeper`). Actions would be a thin wrapper calling the same pipeline in-process — not built yet.

### AWS (what this app actually needs)

You already use AWS — fine. Groundskeeper is a **single always-on HTTP service**. Today’s code does **not** use S3, SQS, DynamoDB, RDS, or Redis.

**Required**

| Piece | AWS service (typical) | Why |
|---|---|---|
| Run the Python/FastAPI process | **ECS Fargate** (or **App Runner**, or EC2) | Hosts `python -m groundskeeper` |
| Container image | **ECR** | Store the image ECS/App Runner pulls |
| HTTPS URL for GitHub webhooks | **Application Load Balancer** + **ACM** cert (ECS path), or App Runner’s built-in HTTPS | GitHub calls `https://…/webhooks/github` |
| Secrets in env | **Secrets Manager** (or SSM Parameter Store) | `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, App private key, webhook secret |
| Logs | **CloudWatch Logs** | stdout from the container |
| Outbound internet | VPC NAT (if private subnets) or public tasks | Calls `api.github.com` + Anthropic API |

**Not used by current code (do not provision for MSP)**

- S3, SQS, SNS, DynamoDB, RDS/Postgres, ElastiCache/Redis, Lambda (unless you rewrite the entrypoint later)

**Outside AWS (still required)**

- GitHub App + webhook pointing at the ALB/App Runner URL  
- Anthropic API (Claude) — not Bedrock unless you change the client later  

**Minimal shape that matches the code today**

```
GitHub webhook → ALB (HTTPS) → ECS Fargate task (1 service)
                                    │
                                    ├─ Secrets Manager (env)
                                    ├─ CloudWatch Logs
                                    ├─ → api.github.com
                                    └─ → Anthropic API
```

App Runner is fewer moving parts (HTTPS + deploy in one). ECS Fargate matches how many teams already run services on AWS.

### AWS step-by-step (App Runner — recommended)

You are an account admin. Create **one ECR repo** + **one App Runner service**. No ALB, ECS, S3, or SQS.

Pick a region you already use (example: `us-east-1`). Stay in that region for every console link.

#### 1. ECR repository

Console: [https://console.aws.amazon.com/ecr/repositories](https://console.aws.amazon.com/ecr/repositories)  
Docs: [Creating a private repository](https://docs.aws.amazon.com/AmazonECR/latest/userguide/repository-create.html)

1. **Create repository**
2. Visibility: **Private**
3. Name: `if-this-ships`
4. Create

On the repo page, **View push commands** — you will use those in step 3.

#### 2. Secrets Manager

Console: [https://console.aws.amazon.com/secretsmanager/home](https://console.aws.amazon.com/secretsmanager/home)  
Docs: [Create an AWS Secrets Manager secret](https://docs.aws.amazon.com/secretsmanager/latest/userguide/create_secret.html)

Create **one secret** (type: Other type of secret → Key/value):

| Key | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `GITHUB_TOKEN` | your PAT |
| `GITHUB_APP_ID` | `4664699` |
| `GITHUB_APP_PRIVATE_KEY` | full PEM including `BEGIN`/`END` lines (real newlines OK here) |
| `GITHUB_WEBHOOK_SECRET` | same secret as on the GitHub App |
| `BOT_LOGIN` | `if-this-ships` |
| `CORE_REPO` | `QdRepo/appt_bridge_core` |
| `MODEL_TRIAGE` | `claude-haiku-4-5` |
| `MODEL_SONNET` | `claude-sonnet-5` |
| `MODEL_OPUS` | `claude-opus-5` |

Name the secret `if-this-ships/env`. Copy the secret **ARN**.

#### 3. Build and push the image

Docker Desktop (or any Docker) on your machine. From this repo:

```bash
# set these
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=123456789012   # 12-digit account id

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin \
    "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

docker build -t if-this-ships .
docker tag if-this-ships:latest \
  "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/if-this-ships:latest"
docker push \
  "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/if-this-ships:latest"
```

Account ID: [https://console.aws.amazon.com/billing/home#/account](https://console.aws.amazon.com/billing/home#/account) (top of the page).

#### 4. App Runner service

Console: [https://console.aws.amazon.com/apprunner](https://console.aws.amazon.com/apprunner)  
Docs: [Creating an App Runner service](https://docs.aws.amazon.com/apprunner/latest/dg/manage-create.html)

1. **Create service**
2. Source: **Container registry** → **Amazon ECR** → browse `if-this-ships` → tag `latest`
3. Deployment: **Automatic** (redeploy on new `:latest` push) or Manual
4. ECR access: let App Runner **create a new service role** if asked
5. Service name: `if-this-ships`
6. Port: **8787**
7. CPU/memory: 1 vCPU / 2 GB is enough to start
8. **Environment variables:** add `PORT=8787`
9. **Secrets:** for each key in the Secrets Manager secret, add a reference (App Runner → Environment variables → Secrets). Map:
   - `ANTHROPIC_API_KEY` → `if-this-ships/env` / `ANTHROPIC_API_KEY`
   - same for `GITHUB_TOKEN`, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`, `BOT_LOGIN`, `CORE_REPO`, `MODEL_*`
10. Create & deploy. Wait until status is **Running**.
11. Copy the default URL: `https://xxxxx.region.awsapprunner.com`

Health check: `https://xxxxx.region.awsapprunner.com/health` should return `{"ok": true, ...}`.

App Runner needs IAM permission to read the secret. If deploy fails on secrets, attach `secretsmanager:GetSecretValue` on that ARN to the App Runner instance role. Docs: [Secrets in App Runner](https://docs.aws.amazon.com/apprunner/latest/dg/env-variable.html).

#### 5. Point the GitHub App at AWS

GitHub App → **General**: [https://github.com/settings/apps/if-this-ships](https://github.com/settings/apps/if-this-ships)

- Webhook **Active:** on
- Webhook URL: `https://xxxxx.region.awsapprunner.com/webhooks/github`
- Secret: same as `GITHUB_WEBHOOK_SECRET`
- Save

**Install App** on a personal test repo if you have not already.

#### 6. Test

On a PR in that repo, comment:

```text
@if-this-ships review
```

Or:

```bash
curl -X POST https://xxxxx.region.awsapprunner.com/review \
  -H 'content-type: application/json' \
  -d '{"owner":"mogiiee","repo":"YOUR_TEST_REPO","number":1}'
```

Later, an org owner installs the same App on QdRepo / Freight-Pins / T-U-F-T. You do not recreate AWS.

---

## Finding shape

1. Intent  
2. If this ships → process impact  
3. Why  
4. Fix direction  
5. Always-flag label (if it hit `always-flag-these.md`)

Clean PR → short summary only.

---

## Core version

From PR `package.json`:

```json
"appt-bridge-core": "git+https://…/appt_bridge_core.git#v1.0.59"
```

Fetches tag `v1.0.59` from `CORE_REPO` via GitHub API using your env token.

---

## CI/CD (merge to `main` → ECR → App Runner)

You do **not** run `docker build` / `docker push` on your laptop after this is wired. Push code to GitHub, merge to `main`, Actions builds `linux/amd64` and pushes `latest` (and the commit SHA) to ECR.

Workflow: [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)  
Registry in that file: account `339713020499`, region `us-east-1`, repo `my-ecr-repo`. Change `ECR_REPOSITORY` in the YAML if your ECR name is different.

### 1. IAM user for GitHub (AWS console)

1. [https://console.aws.amazon.com/iam/](https://console.aws.amazon.com/iam/) → **Users** → **Create user**
2. Name: `github-if-this-ships`
3. **Attach policies directly** → **Create policy** → JSON:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrPush",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:CompleteLayerUpload",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:DescribeRepositories"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AppRunnerDeploy",
      "Effect": "Allow",
      "Action": ["apprunner:StartDeployment", "apprunner:DescribeService"],
      "Resource": "*"
    }
  ]
}
```

4. Name the policy `github-if-this-ships-ecr` → attach to the user → Create user.
5. Open the user → **Security credentials** → **Create access key** → use case **Application running outside AWS** → create.
6. Copy **Access key ID** and **Secret access key** once.

### 2. GitHub repo secrets (GitHub UI)

This project must live on GitHub (create a repo, push this folder). Then:

1. Repo → **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret**
   - Name `AWS_ACCESS_KEY_ID` → paste access key ID
   - Name `AWS_SECRET_ACCESS_KEY` → paste secret access key

Optional (only if App Runner deployment trigger is **Manual**):

3. **Variables** (not Secrets) → **New repository variable**
   - Name `APP_RUNNER_SERVICE_ARN`
   - Value: App Runner → your service → **ARN** (looks like `arn:aws:apprunner:us-east-1:339713020499:service/if-this-ships/...`)

If App Runner **Automatic deployments** is on, skip the variable. A new `latest` image is enough.

### 3. App Runner: automatic deploys (console)

1. [https://console.aws.amazon.com/apprunner](https://console.aws.amazon.com/apprunner) → service `if-this-ships`
2. **Source and deployment** (or **Configuration**) → **Edit**
3. Deployment trigger: **Automatic**
4. Source: ECR `my-ecr-repo` tag `latest`
5. Save

### 4. What you do day to day

1. Branch → PR → **merge to `main`**
2. GitHub → **Actions** tab → workflow **Deploy to ECR** should go green
3. ECR shows a new `latest` (and a SHA tag)
4. App Runner goes to **Operation in progress** then **Running**
5. GitHub App webhook keeps using the same App Runner URL — do not change it

Manual run without merging: Actions → Deploy to ECR → **Run workflow**.

---

## Layout

```
.github/workflows/deploy.yml   # merge to main → ECR
context/                       # rules — edit these
groundskeeper/                 # Python service
scripts/selfcheck.py
Dockerfile
.env.example
```
