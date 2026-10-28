# M8a — Dashboard shell (mock data)

**Track:** C (frontend) · **Owns:** `frontend/` · **Depends on:** M0 · **Later:** M8b connects each page to the real API as backend modules merge

## Goal
The complete look, navigation, and page structure of the admin dashboard, built against [api-contract.md](../api-contract.md) with mock data, so that wiring the real backend later is a data-layer swap, not a redesign.

## Before writing code
- **Read `frontend/AGENTS.md`.** This is Next.js 16.4 with Cache Components and Partial Prefetching on; read the relevant guides in `frontend/node_modules/next/dist/docs/` (App Router, layouts, `use cache`, route handlers, authentication with cache components) before writing code.
- Follow the design rules in the root `CLAUDE.md` and [design-file.txt](../design-file.txt). Theme values: [design-tokens.css](../design-tokens.css) (convert the HSL triplets to Tailwind v4 / current shadcn format). Existing tokens and `StatusBadge` are in `src/app/globals.css` and `src/components/`.

## Scope
- **shadcn/ui** initialised (Tailwind v4), themed with our tokens, light + dark mode (system default + toggle). In-app controls use the 6 px radius.
- **Auth screens** (UI + client validation, mocked submit): login, signup / onboarding wizard — business details → "single or multiple salons?" → location(s) with timezone → opening hours → done. Mesh gradient allowed here only.
- **App shell:** sidebar (Overview, Calendar, Bookings, Customers, Staff, Services, Calls, Settings), top bar with **location switcher** (hidden when `location_mode` is `single`) and user menu; mobile drawer navigation; no horizontal scroll at 375 px.
- **Pages with mock data:**
  - Overview: cards for today's appointments, upcoming, cancellations, voice-booked share; recent calls list.
  - Calendar: **FullCalendar** (`@fullcalendar/react` + daygrid/timegrid/interaction — free plugins only; resource/scheduler views are paid, so do staff columns via filtering/colour instead). Day/week/month, event colours per staff, status styling.
  - Bookings: table with search, filters (status, staff, date range, source), status badges, create/edit/reschedule/cancel dialogs (mocked).
  - Customers: list + detail with appointment history.
  - Staff: list, profile, working hours editor, time off.
  - Services: list, create/edit (price, duration, buffer, per-location overrides).
  - Calls: list with outcome badges, detail with transcript + summary; simple analytics (calls per day, outcome split).
  - Settings: business details, cancellation policy (default 120 min, per-location override), locations management.
  - Empty, loading, and error states for every list.
- **Data layer:** `src/lib/api/` — typed client mirroring the contract (`snake_case` types), a single fetch wrapper (bearer token, `/api` base, error-shape parsing, 401 → refresh once), and a mock implementation selected by `NEXT_PUBLIC_API_MOCKS=true`. Prefer **MSW** so the real client code path runs in dev and tests.
- **Auth state:** access token in memory, refresh via `/api/auth/refresh` (cookie), route protection for the app shell. Role-aware nav (staff see only their calendar and bookings).

## Tests
- Vitest + Testing Library for components and the API client (error parsing, refresh-once logic, mock handlers).
- Playwright E2E (desktop + mobile projects, running with mocks): login validation, onboarding wizard both paths (single / multiple), navigation through every page, bookings filter + cancel dialog flow, location switcher, dark mode toggle, no horizontal scroll on every page.
- Accessibility basics: every form control labelled, dialogs focus-trapped, keyboard navigation through the sidebar; add `@axe-core/playwright` checks on main pages.

## Done when
- [ ] `pnpm lint && pnpm typecheck && pnpm test && pnpm build && pnpm e2e` green locally and in CI.
- [ ] Every page reachable, responsive, light + dark.
- [ ] No API shape invented outside [api-contract.md](../api-contract.md); if one was needed, the contract is updated in the same PR and flagged in the description.
- [ ] PR opened with screenshots (desktop + mobile) of the main pages.

## Out of scope
Real backend calls (M8b), real Retell data, email.
