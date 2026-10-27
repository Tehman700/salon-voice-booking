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
