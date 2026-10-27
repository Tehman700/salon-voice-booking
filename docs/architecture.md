# Architecture and build plan

Status: **planning** — no application code yet. This records the decisions made so far; it evolves as we build.

## System overview

```
          Phone caller
              │
        ┌─────▼──────┐   tool calls (HTTPS, signed)   ┌──────────────────────────────┐
        │  Retell AI │ ─────────────────────────────▶ │        FastAPI backend       │
        │ voice agent│ ◀── voice-friendly JSON ────── │        (AWS ECS Fargate)     │
        └─────┬──────┘                                │                              │
              │ call events                           │  /retell/functions/*  tools  │
              └─────────────────────────────────────▶ │  /webhooks/retell     logs   │
                                                      │  REST API for dashboard      │
        ┌────────────────┐   REST + JWT               │                              │
        │ Next.js admin  │ ─────────────────────────▶ │  Service layer: the ONE      │
        │ dashboard      │ ◀───────────────────────── │  place for booking rules     │
        │ (Vercel)       │                            └───────┬──────────────┬───────┘
        └────────────────┘                                    │              │ outbox
                                                     ┌────────▼───────┐ ┌────▼─────┐
                                                     │ PostgreSQL     │ │ Amazon   │
                                                     │ (AWS RDS)      │ │ SES      │
                                                     └────────────────┘ └──────────┘
```

The voice agent and the dashboard are two clients of one booking service layer. Business rules (hours, durations, conflicts, cancellation policy) live only there.

## Key decisions

| Topic | Decision |
|---|---|
| Tenancy | Multi-tenant: **Business → Locations (salons) → Staff**. A single salon is a business with one location. Onboarding asks "single or multiple locations?" |
| Isolation | Every tenant row carries `business_id`; repositories scope queries automatically; dedicated cross-tenant isolation tests |
| Roles | Platform admin, business owner (all locations), location manager (one location), staff (own calendar) |
| Customers | Belong to the business, so history follows a customer across branches |
| Services | Business-level catalog with per-location price/duration overrides |
| Cancellation policy | Default 2 hours before the appointment; editable at business level and overridable per location |
| Voice routing | One Retell number per location; inbound dialled number → location, injected into the agent as dynamic variables |
| Double booking | Postgres `EXCLUDE USING gist (staff_id WITH =, tstzrange(start_at, end_at) WITH &&)` on active appointments + idempotency keys; conflict → 409 with alternative slots |
| Time | Store UTC (`timestamptz`); each location has its own timezone |
| Notifications | Amazon SES via a transactional outbox (send only after commit); reminders via EventBridge Scheduler |
| Calendar UI | FullCalendar, restyled with our design tokens |
| Automation (n8n) | **Not used.** Booking logic must stay transactional in the backend; SES + EventBridge cover notifications and reminders |
| Hosting | FastAPI on AWS (ECR → ECS Fargate behind ALB), PostgreSQL on AWS RDS, frontend on Vercel; Docker for backend images and local dev |
| Testing | Everywhere: pytest (unit + integration on real Postgres, concurrency, tenant isolation), Retell tool contract tests, Vitest + RTL, Playwright E2E, CI on every push |

## Voice-agent rules
- Tools: `get_salon_info`, `list_services`, `list_staff`, `check_availability`, `create_booking`, `find_my_bookings`, `reschedule_booking`, `cancel_booking`, `end_call`.
- Caller ID pre-fills the phone number; name is confirmed before changing anything.
- Current date/time and location timezone are injected so "tomorrow at 3" resolves correctly.
- Always read details back before acting. Only say booked / changed / cancelled when the tool returns `success: true`; otherwise say so and offer alternatives.

## Data model (first draft)
`businesses`, `locations`, `users`, `staff`, `staff_services`, `services`, `location_services`, `staff_working_hours`, `staff_time_off`, `business_hours`, `closures`, `customers`, `appointments`, `appointment_events`, `call_logs`, `notification_outbox`, `policies/settings`.

## Modules (build order)

| # | Module | Scope | Testing |
|---|---|---|---|
| M0 | Foundation | Monorepo, uv/ruff/mypy, pnpm, docker-compose Postgres, GitHub Actions CI | CI gates lint, types, tests |
| M1 | Tenancy + Auth | Businesses, locations, users, roles, JWT, invites, tenant scoping | Auth + cross-tenant isolation |
| M2 | Catalog + Schedules | Services, overrides, staff, skills, hours, time off, closures, policies | CRUD + validation |
| M3 | Availability engine | Slot computation per staff / any staff, timezone-aware | DST, edges, buffers |
| M4 | Booking engine | Create / reschedule / cancel, exclusion constraint, idempotency, policy, audit | Parallel same-slot race, policy |
| M5 | Deploy skeleton | ECR, ECS Fargate + ALB/HTTPS, RDS, Secrets Manager, Vercel, staging, CI/CD | Smoke + health checks |
| M6 | Voice agent | Retell tool endpoints, inbound routing, call webhook, call logs, prompt + tool schemas | Contract, scripted conversations, staging calls |
| M7 | Notifications | Outbox, SES templates, reminders via EventBridge | Outbox tests, staging send |
| M8 | Dashboard | Tokens, auth, onboarding wizard, overview, calendar, bookings, staff, services, customers, calls, settings | Vitest + RTL, Playwright E2E |
| M9 | Docs + demo | API docs, schema diagram, setup/deploy guides, demo script | — |

## Planned repo layout
```
backend/   app/{api,services,models,schemas,core}, alembic/, tests/
frontend/  Next.js app router, components/ui (shadcn, themed)
retell/    agent prompt, tool JSON schemas, setup notes
infra/     AWS infrastructure as code
docs/      requirements, design, architecture, schema
```

## Open questions
1. Where are the salons? AWS region is `ap-south-1`; Retell is US-hosted (~200–300 ms extra per tool call).
2. Phone-number country (Retell sells US/CA numbers; others need Twilio/Telnyx via SIP).
3. Domain for SES sending and the API.
4. SES production access (sandbox only sends to verified addresses).
5. Infrastructure as code: Terraform (needs install) vs AWS CLI scripts.
