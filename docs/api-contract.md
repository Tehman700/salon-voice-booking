# API contract

The agreement between the backend (FastAPI) and the dashboard (Next.js). The backend's OpenAPI spec (`/openapi.json`) becomes the source of truth once an endpoint exists; until then this document is what the frontend mocks against.

**Changing the contract:** edit this file in the same PR as the code change and say so in the PR description. Shapes marked **draft** may still change when their module is built.

## Conventions

| Topic | Rule |
|---|---|
| Transport | JSON over HTTPS. The browser calls `/api/*` on the Next.js origin, which proxies to FastAPI (paths below are FastAPI paths, without `/api`) |
| Field names | `snake_case` in JSON |
| IDs | UUID strings |
| Timestamps | ISO 8601 in UTC with `Z` (e.g. `2026-11-03T14:30:00Z`). Location-local display uses the location's `timezone` (IANA name) |
| Dates / local times | `date`: `YYYY-MM-DD`; local wall-clock time: `HH:MM` (24 h) |
| Money | Integer minor units + currency: `{"price_minor": 250000, "currency": "PKR"}` |
| Pagination | `?limit=50&cursor=<opaque>` → `{"items": [...], "next_cursor": "..." \| null}` |
| Filtering | Query params, e.g. `GET /bookings?location_id=…&status=booked&from=…&to=…&q=…` |
| Tenant scope | Never sent by the client. The backend derives `business_id` from the access token. Cross-tenant IDs return **404**, not 403 |

### Errors
Every non-2xx response (validation `details` map each field path to a list of messages):
```json
{ "error": { "code": "slot_unavailable", "message": "That time was just booked.", "details": { } } }
```
| HTTP | When | Example `code` |
|---|---|---|
| 400 / 422 | Validation | `validation_error` (details: field → message list) |
| 401 | Missing / expired token | `not_authenticated`, `token_expired` |
| 403 | Authenticated but role not allowed | `forbidden` |
| 404 | Not found **or** other tenant's resource | `not_found` |
| 409 | Conflict (double booking, duplicate email, idempotency mismatch) | `slot_unavailable`, `email_taken` |
| 429 | Rate limited | `rate_limited` |

## Auth (M1)

- **Access token:** JWT, ~15 min, returned in the JSON body; the frontend keeps it in memory and sends `Authorization: Bearer <token>`.
- **Refresh token:** opaque, ~30 days, set by the backend as an `httpOnly; Secure; SameSite=Lax` cookie named `refresh_token`, scoped to path `/api/auth` (the path the browser sees through the Next.js proxy; configurable with `REFRESH_COOKIE_PATH`). Rotated on every refresh; reuse of an old one revokes the whole session family.
- Because the browser only talks to the Next.js origin, the cookie is first-party.

| Method | Path | Auth | Body → Response |
|---|---|---|---|
| POST | `/auth/signup` | none | `SignupRequest` → `201 AuthResponse` (creates business, its first location(s), and the owner) |
| POST | `/auth/login` | none | `{email, password}` → `AuthResponse` |
| POST | `/auth/refresh` | cookie | → `AuthResponse` (new cookie) |
| POST | `/auth/logout` | cookie | → `204` (revokes refresh token, clears cookie) |
| GET | `/auth/me` | bearer | → `Me` |
| POST | `/auth/accept-invite` | none | `{token, full_name, password}` → `AuthResponse` |

```ts
type Role = "platform_admin" | "owner" | "manager" | "staff";

type SignupRequest = {
  business_name: string;
  owner_full_name: string;
  email: string;
  password: string;               // min 10 chars
  location_mode: "single" | "multiple";
  locations: LocationInput[];     // exactly 1 when "single", 1+ when "multiple"
};

type AuthResponse = { access_token: string; token_type: "bearer"; expires_in: number; user: Me };

type Me = {
  id: string; email: string; full_name: string; role: Role;
  business: { id: string; name: string; location_mode: "single" | "multiple" } | null;
  location_ids: string[];         // locations this user may act on (all, for owners)
};
```

## Business, locations, users (M1)

| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | `/business` | any | Current business |
| PATCH | `/business` | owner | Name, default timezone, default cancellation window |
| GET | `/locations` | any | Locations the user can access → `{items: Location[], next_cursor: null}` |
| POST | `/locations` | owner | Switches `location_mode` to `multiple` when a 2nd location is added |
| GET / PATCH | `/locations/{id}` | owner, manager (own) | |
| DELETE | `/locations/{id}` | owner | Soft-deactivate; cannot remove the last active location |
| GET | `/users` | owner, manager (own location) | Cursor-paginated: `?limit=50&cursor=` → `{items: User[], next_cursor}` |
| POST | `/users/invite` | owner, manager (own location, staff role only) | `{email, role, location_id}` → `201 Invite` (email sent in M7; the response includes `token` only while `EXPOSE_INVITE_TOKENS` is on, which defaults to local/test) |
| PATCH | `/users/{id}` | owner | Role, location, `is_active` |

```ts
type LocationInput = {
  name: string;
  timezone: string;               // IANA, e.g. "Asia/Karachi"
  phone?: string;                 // E.164
  address_line1?: string; city?: string; country?: string;  // ISO 3166-1 alpha-2
};

type Location = LocationInput & {
  id: string; slug: string; is_active: boolean;
  cancellation_window_minutes: number | null;   // null → inherit business default
  effective_cancellation_window_minutes: number;
};

type Business = {
  id: string; name: string; slug: string;
  location_mode: "single" | "multiple";
  default_timezone: string;
  cancellation_window_minutes: number;          // default 120
};

type User = {
  id: string; email: string; full_name: string; role: Role;
  location_id: string | null; is_active: boolean; last_login_at: string | null;
};
```

## Catalog and schedules (M2, built)

```ts
type Service = {
  id: string; name: string; description: string | null; category: string | null;
  duration_minutes: number; buffer_minutes: number;
  price_minor: number; currency: string; is_active: boolean;
  location_overrides: { location_id: string; price_minor: number | null; duration_minutes: number | null; is_offered: boolean }[];
};

type Staff = {
  id: string; location_id: string; user_id: string | null;
  full_name: string; title: string | null; color: string;     // calendar color
  service_ids: string[]; is_active: boolean;
};

type WorkingHours = { weekday: 0 | 1 | 2 | 3 | 4 | 5 | 6; start: string; end: string }[];  // 0 = Monday, local time
type TimeOff = { id: string; staff_id: string; starts_at: string; ends_at: string; reason: string | null };
type Closure = { id: string; location_id: string; date: string; reason: string | null };
```
### Built in M2 (catalog and schedules)

All roles can read; writes need **owner or manager** (managers only inside their own location). List endpoints return `{items, next_cursor: null}`.

| Method | Path | Notes |
|---|---|---|
| GET | `/services` | The business-wide catalog, with per-location overrides |
| POST | `/services` | `409 service_name_taken` (names are unique, ignoring case) |
| PATCH | `/services/{id}` | Partial. `location_overrides`, if present, replaces the overrides the caller may edit: owners all locations, managers only their own (other rows are left untouched) |
| DELETE | `/services/{id}` | `204`. Deactivates; services are never deleted |
| GET | `/staff?location_id=` | Owners see all; managers and staff only their own location |
| POST | `/staff` | Working hours start as a copy of the location's opening hours. Optional `user_id` links a dashboard login (`409 user_already_linked`) |
| PATCH | `/staff/{id}` | Partial. `service_ids` replaces the list; `title: null` clears it; only an owner can change `location_id` |
| DELETE | `/staff/{id}` | `204`. Deactivates |
| GET / PUT | `/staff/{id}/hours` | `WorkingHours`. PUT replaces everything; a day may have several non-overlapping blocks (`422` otherwise) |
| GET / POST | `/staff/{id}/time-off` | `POST {starts_at, ends_at, reason?}`; times must carry a timezone |
| DELETE | `/staff/{id}/time-off/{time_off_id}` | `204` |
| GET / PUT | `/locations/{id}/hours` | Opening hours; a weekday with no block is closed. New locations default to Mon-Sat 10:00-19:00 |
| GET / POST | `/locations/{id}/closures` | `POST {date, reason?}`; `409 closure_exists` |
| DELETE | `/locations/{id}/closures/{closure_id}` | `204` |

`Closure` is `{id, date, reason}` (the location is the one in the URL). Services and staff are shared records of one business: another business's ids, and (for managers) other locations' staff, are `404`.

## Availability (M3, built) and bookings (M4, draft)

```ts
type AvailabilityRequest = {
  location_id: string; service_id: string; staff_id?: string;   // omit = any staff
  date_from: string; date_to: string;                           // YYYY-MM-DD, location-local
};
type Slot = { starts_at: string; ends_at: string; staff_id: string; staff_name: string };

type BookingStatus = "booked" | "completed" | "cancelled" | "no_show";
type Booking = {
  id: string; reference: string;                                 // short, speakable, e.g. "K7Q2M"
  location_id: string; service_id: string; staff_id: string;
  customer: { id: string; full_name: string; phone: string; email: string | null };
  starts_at: string; ends_at: string; status: BookingStatus;
  source: "voice" | "dashboard"; call_id: string | null;
  price_minor: number; currency: string; notes: string | null;
  created_at: string; cancelled_at: string | null; cancellation_reason: string | null;
};
```
| Method | Path | Notes |
|---|---|---|
| POST | `/availability` | **Built.** `AvailabilityRequest` → `{ slots: Slot[] }`. Any role, for locations they can access. Dates are location-local, at most 31 days. Slots are every 15 minutes where the whole service fits inside the location's opening hours and the staff member's working hours, clear of time off and existing appointments (including the service's cleanup buffer); times in the past are never offered. `staff_id` omitted = any staff. A closed, inactive or not-offered situation gives `{slots: []}`, not an error |
| POST | `/bookings` | Requires `Idempotency-Key` header. `409 slot_unavailable` includes `details.alternatives: Slot[]` |
| GET | `/bookings` | Filters: `location_id, staff_id, status, from, to, q`. Staff role sees only their own |
| GET | `/bookings/{id}` | |
| PATCH | `/bookings/{id}` | Reschedule (`starts_at`, optional `staff_id`) or edit notes |
| DELETE | `/bookings/{id}` | Cancel; `409 cancellation_window_passed` inside the policy window (owners/managers may override with `?force=true`) |
| GET | `/customers`, `/customers/{id}` | Includes appointment history |

## Calls (M6) — draft

```ts
type CallLog = {
  id: string; retell_call_id: string; location_id: string;
  from_number: string; started_at: string; ended_at: string | null; duration_seconds: number | null;
  outcome: "booked" | "rescheduled" | "cancelled" | "info_only" | "failed" | "abandoned";
  summary: string | null; transcript: { role: "agent" | "user"; text: string }[] | null;
  booking_id: string | null;
};
```
Endpoints: `GET /calls`, `GET /calls/{id}`, `GET /calls/stats?from=&to=&location_id=`.

## Built in M1: additions and clarifications

- `Invite` response: `{id, email, role, location_id, expires_at, token?}`.
- Extra error codes: `invalid_credentials` (401, also for deactivated users), `invalid_invite` (400), `last_active_location` (409), `last_owner` (409), `location_conflict` / `signup_conflict` (409, rare races), `method_not_allowed` (405).
- Business users only: a platform admin calling business endpoints gets `403`. `GET /auth/me` works for everyone.
- Only an owner may change a location's `is_active`; managers may edit their own location otherwise (including its cancellation window).
- A new access token is not needed after a role change or deactivation: the backend reads the user's current state on every request.
