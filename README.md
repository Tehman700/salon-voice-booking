# Salon Voice Booking

An AI-powered, multi-location salon booking platform. Customers call a natural-sounding **Retell AI** receptionist that answers questions, checks real-time availability, and books, reschedules, or cancels appointments. Salon owners, managers, and staff run everything from a responsive admin dashboard.

> **Status:** planning. Architecture and module plan are agreed; implementation starts with M0 (foundation).

## Highlights
- **Voice receptionist** — Retell AI custom functions backed by real booking APIs; never confirms an action the backend didn't confirm.
- **Conflict-proof booking** — PostgreSQL exclusion constraints and idempotency keys prevent double bookings, even under simultaneous requests.
- **Multi-tenant** — one business can run many salons, each with its own hours, timezone, staff, prices, and phone number.
- **Admin dashboard** — calendars (day/week/month), bookings, staff schedules, services, customers, call logs and analytics.
- **Notifications** — booking confirmations and reminders by email via Amazon SES.

## Stack
| Layer | Technology | Hosting |
|---|---|---|
| Voice agent | Retell AI | Retell |
| Backend | Python, FastAPI, SQLAlchemy, Alembic | AWS ECS Fargate (Docker) |
| Database | PostgreSQL | AWS RDS |
| Frontend | Next.js, Tailwind CSS, shadcn/ui, FullCalendar | Vercel |
| Email | Amazon SES | AWS |

## Documentation
- [Requirements brief](docs/requirements.md)
- [Architecture and build plan](docs/architecture.md)
- [Design system](docs/design-file.txt) and [theme tokens](docs/design-tokens.css)
- [CLAUDE.md](CLAUDE.md) — project memory for AI coding agents

## Roadmap
M0 Foundation → M1 Tenancy + Auth → M2 Catalog + Schedules → M3 Availability engine → M4 Booking engine → M5 Deploy skeleton → M6 Voice agent → M7 Notifications → M8 Dashboard → M9 Docs + demo.
