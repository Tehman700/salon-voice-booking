# CLAUDE.md

Project memory for AI coding agents working in this repo.

## What this is
Multi-tenant AI salon booking platform: a Retell AI voice receptionist plus an admin dashboard, sharing one FastAPI booking backend on PostgreSQL. (The local folder is named `Restaurant-Voice`, but the product is for **salons**.)

## Read first
- [docs/requirements.md](docs/requirements.md) — original brief (direction, not a rigid spec)
- [docs/architecture.md](docs/architecture.md) — decisions, modules, build order, open questions
- [docs/design-file.txt](docs/design-file.txt) — design system (Vercel-inspired DESIGN.md); use it for all UI
- [docs/design-tokens.css](docs/design-tokens.css) — shadcn/ui theme variables, light + dark

## Non-negotiable rules
- The voice agent never says a booking was made, changed, or cancelled unless the backend returned success.
- PostgreSQL is the source of truth; double booking is prevented in the database (exclusion constraint), not only in code.
- All booking rules live in the backend service layer; the voice adapter and dashboard both call it.
- Every query is tenant-scoped by `business_id`; cross-tenant access must be covered by tests.
- Never commit secrets; use `.env` locally and AWS Secrets Manager / Vercel env in deployed environments.

## Stack and hosting
- Backend: Python FastAPI, SQLAlchemy, Alembic, uv — Docker image on AWS ECS Fargate (region `ap-south-1`)
- Database: PostgreSQL on AWS RDS (needs `btree_gist`)
- Frontend: Next.js + Tailwind + shadcn/ui + FullCalendar — deployed on Vercel
- Voice: Retell AI custom functions → `/retell/functions/*`; call events → `/webhooks/retell`
- Email: Amazon SES via a transactional outbox; reminders via EventBridge Scheduler
- No n8n — automation stays in the backend

## Product decisions
- Business → Locations → Staff; onboarding asks single vs multiple locations
- Cancellation policy: default 2 hours, editable per business and per location
- Customers are shared across a business's locations

## Design rules (dashboard)
- In-app scale: 6px radius buttons/inputs, no 100px pills on the same screen
- Geist / Geist Mono; mono only for table headers, eyebrows, technical labels
- Hairline borders (`#ebebeb`), stacked subtle shadows, ink `#171717` primary
- Mesh gradient only on auth/marketing screens, never inside the app
- Status colors: booked blue `#0070f3`, pending amber `#f5a623`, cancelled red `#ee0000`

## Testing expectations
Test everything: backend unit + integration against real Postgres, concurrency race tests, tenant isolation, Retell tool contracts, frontend component tests, Playwright E2E. CI must pass before merge.

## Local development
- Postgres: `docker compose up -d db` (host port **5544**). Full stack in containers: `docker compose up --build`.
- Backend (`backend/`): `uv sync`, `uv run alembic upgrade head`, `uv run uvicorn app.main:app --reload`. Checks: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest`.
- Frontend (`frontend/`): `pnpm install`, `pnpm dev`. Checks: `pnpm lint && pnpm typecheck && pnpm test && pnpm build && pnpm e2e`.
- Env files: copy `backend/.env.example` → `backend/.env`, `frontend/.env.example` → `frontend/.env.local`.

## Parallel work (multiple Claude sessions)
Work is split into tracks, each in its own git worktree (`.claude/worktrees/<name>`) with a brief in [docs/modules/](docs/modules/):
- **Track A — backend core** owns `backend/`: M1 → M2 → M3 → M4, strictly in order.
- **Track B — infra** owns `infra/`, `.github/workflows/deploy-*.yml`, `docs/deployment.md`: M5.
- **Track C — frontend** owns `frontend/`: M8a (mock data), later M8b (real API).

Rules:
- Stay inside your track's folders. If you need a change elsewhere, describe it in your PR instead of making it.
- **Only Track A writes Alembic migrations.** Before merging, rebase on `main` and make sure there is a single head.
- [docs/api-contract.md](docs/api-contract.md) is shared: change it only in the same PR as the code that needs it, and call it out in the PR description.
- Tests in a worktree automatically use their own database (`salon_test_<worktree>`), so parallel runs don't clash.
- Install dependencies inside the worktree (`uv sync`, `pnpm install`) — worktrees are fresh checkouts.
- One module per PR. Open the PR with `gh pr create` when the module's "Done when" checklist is met and all checks pass. Don't merge your own PR; the coordinating session reviews and merges.
- Never run destructive git commands, and never create billable cloud resources without the user's approval in that session.
