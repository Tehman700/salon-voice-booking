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
- Status colors: booked blue (badge text `#0556b3`, deeper than brand `#0070f3` for 4.5:1 contrast), pending amber `#f5a623`, cancelled red `#ee0000`

## Testing expectations
Test everything: backend unit + integration against real Postgres, concurrency race tests, tenant isolation, Retell tool contracts, frontend component tests, Playwright E2E. CI must pass before merge.

## Local development
- Postgres: `docker compose up -d db` (host port **5544**). Full stack in containers: `docker compose up --build`.
- Backend (`backend/`): `uv sync`, `uv run alembic upgrade head`, `uv run uvicorn app.main:app --reload`. Checks: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest`.
- Frontend (`frontend/`): `pnpm install`, `pnpm dev`. Checks: `pnpm lint && pnpm typecheck && pnpm test && pnpm build && pnpm e2e`.
- Env files: copy `backend/.env.example` → `backend/.env`, `frontend/.env.example` → `frontend/.env.local`.

## Frontend notes
- `NEXT_PUBLIC_API_MOCKS=true` runs the whole dashboard on MSW sample data (`src/mocks/`); `false` uses the real backend through the `/api/*` proxy. Mock responses must match `docs/api-contract.md` (and the real backend) exactly.
- Dialog forms are mounted inside their `DialogContent` (state starts fresh each open); don't reset form state in `useEffect` (the `react-hooks/set-state-in-effect` lint rule forbids it).
- FullCalendar is v7: plugins come from `@fullcalendar/react/<plugin>`; event colors are `color`/`contrastColor`.
- E2E tests (`pnpm e2e`) need a production build in demo mode; Playwright starts its own server on port 3199.

## Workflow
Modules are built one at a time, in the order in [docs/architecture.md](docs/architecture.md) (briefs in [docs/modules/](docs/modules/)), one branch and pull request per module.
- [docs/api-contract.md](docs/api-contract.md) is shared with the frontend: change it in the same PR as the code that needs it.
- Tenant-scoped data access goes through `app/repositories/tenant.py`; rules like "keep one active owner/location" take `lock_business()` first (see `app/db/locks.py`) to avoid races and deadlocks.
- Tests use a real Postgres on `127.0.0.1:5544` (use the IP, not `localhost`: on Windows `localhost` adds ~2 s per connection).
- Backend coverage: `uv run pytest --cov` (greenlet-aware config is in pyproject.toml).
- Never run destructive git commands, and never create billable cloud resources without the user's approval.
