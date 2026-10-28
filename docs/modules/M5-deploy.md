# M5 — Deploy skeleton (staging)

**Track:** B (infra) · **Owns:** `infra/`, `.github/workflows/deploy-*.yml`, `docs/deployment.md` · **Depends on:** M0 · **Unblocks:** Retell testing over real HTTPS (M6), SES (M7)

## Goal
A repeatable staging environment: the backend image runs on AWS, talks to RDS, is reachable over HTTPS, and redeploys automatically from `main`. The frontend deploys to Vercel and proxies `/api/*` to the backend.

## Constraints
- AWS account `109257212304`, region **`ap-south-1`**, CLI already configured (`aws sts get-caller-identity` works). Vercel CLI logged in (team `rivonnaai-7184`). GitHub repo `Tehman700/salon-voice-booking`.
- **Ask the user in this terminal before any step that creates billable resources or changes DNS/IAM**, and show the plan (e.g. `terraform plan`) first. Target budget for staging: ~$40–60/month.
- Infrastructure as code: **Terraform**. If `terraform` is not installed, ask the user to approve `winget install Hashicorp.Terraform`. Remote state in an S3 bucket with native lockfile (`use_lockfile = true`).
- No long-lived AWS keys in GitHub: use **GitHub OIDC** → IAM role for deploys.
- No custom domain yet. Retell needs HTTPS, so put **CloudFront** in front of the ALB (HTTPS on `*.cloudfront.net`), or propose a better option to the user. Keep it swappable for a real domain + ACM later.
- Do not edit `backend/` or `frontend/` application code. If something there blocks deployment, describe it in the PR (or a note in `docs/deployment.md`) instead.

## Scope
- **Network:** VPC with public subnets for the ALB and Fargate tasks (public IP, no NAT gateway, to save cost) and private subnets for RDS. Security groups: ALB ← internet 80/443 (or CloudFront prefix list), tasks ← ALB only, RDS ← tasks only.
- **ECR** repository `salon-backend` with lifecycle policy (keep last ~10 images).
- **RDS PostgreSQL 18**, `db.t4g.micro`, 20 GB gp3, encrypted, automated backups (7 days), not publicly accessible, deletion protection on, parameter group allowing `btree_gist`/`citext` (both are supported on RDS). Master password managed by Secrets Manager (`manage_master_user_password`).
- **Secrets Manager:** `DATABASE_URL` (asyncpg URL incl. `?ssl=require`), `JWT_SECRET`. Injected into the task definition as secrets, never as plain env.
- **ECS Fargate:** cluster, task definition (0.25 vCPU / 0.5 GB), service (1 task) behind the **ALB** with health check `GET /health`; CloudWatch log group (14-day retention).
- **Migrations:** one-off ECS task with command `alembic upgrade head`, run by the deploy workflow before updating the service.
- **CI/CD** `.github/workflows/deploy-backend.yml`: on push to `main` (paths `backend/**`) and manual dispatch → build image → push to ECR (tag = git SHA) → run migration task and wait → update service → wait for stability → smoke-check `/health/ready` through CloudFront.
- **Vercel:** link a project with root directory `frontend`, env `BACKEND_URL` = staging backend URL, Git integration so `main` deploys to production and PRs get previews.
- **Docs:** `docs/deployment.md` — architecture diagram, how to deploy, how to run migrations manually, how to roll back, how to read logs, cost breakdown, teardown.

## Tests / verification
- `terraform fmt -check`, `terraform validate`, and `tflint` (if available) in a CI job for `infra/**`.
- After apply: `curl https://<cloudfront>/health/ready` → `{"status":"ok","database":"ok"}`.
- Deploy workflow green on a real run; a second run with no changes is a no-op deploy that stays healthy.
- Vercel deployment loads the home page; `/api/health` through the Vercel URL returns the backend's health JSON.

## Done when
- [ ] Staging backend reachable over HTTPS with DB ready.
- [ ] Push to `main` redeploys automatically; migrations run first.
- [ ] Frontend live on Vercel and proxying `/api/*`.
- [ ] `docs/deployment.md` written; outputs (URLs, ARNs) recorded there (no secrets).
- [ ] PR opened with the plan summary, monthly cost estimate, and any manual steps the user must do.
