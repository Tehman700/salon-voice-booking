# API contract

The agreement between the backend (FastAPI) and the dashboard (Next.js). The backend's OpenAPI spec (`/openapi.json`) becomes the source of truth once an endpoint exists; until then this document is what the frontend mocks against.

**Changing the contract:** edit this file in the same commit as the code change. Shapes marked **draft** may still change when their module is built.

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
  notification_email: string | null;            // booking alerts go here (M7); null = off
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

## Availability (M3) and bookings (M4), built

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
| POST | `/bookings` | **Built.** Body `{location_id, service_id, staff_id, starts_at (with timezone), customer: {full_name, phone, email?}, notes?}`. Requires an `Idempotency-Key` header (8-100 chars): repeating a request with the same key returns the original booking with `200` instead of `201`. Phones are normalised to `+<digits>` (a leading `0` takes the country code of the location's country) and must have the right number of digits for that country (e.g. 10 after +92); the customer is found or created by phone within the business. `409 slot_unavailable` carries `details.alternatives: Slot[]` (the nearest free slots). Bookings in the past, outside hours, or for a stylist who does not offer the service are refused. Double booking is also refused by the database itself |
| GET | `/bookings` | **Built.** Soonest first. Filters: `location_id, staff_id, status, source, from, to, q`; `from`/`to` are dates in the location's timezone (inclusive) or timestamps with a timezone; `q` matches customer name, phone, or reference. Cursor pagination, `limit` up to 500. Owners see everything, managers their location, staff only appointments of the stylist record linked to their user |
| GET | `/bookings/{id}` | **Built.** Anything the caller cannot see is `404` |
| PATCH | `/bookings/{id}` | **Built.** `starts_at` and/or `staff_id` reschedules (the new time must be free; the booking's own current time does not count against it), `notes` edits notes, `status: "completed" \| "no_show"` records the outcome (owner/manager only). Only `booked` appointments can change (`409 booking_not_active`). Inside the cancellation window: `409 cancellation_window_passed` with `details.window_minutes`; owners/managers override with `?force=true` (staff get `403`) |
| DELETE | `/bookings/{id}` | **Built.** Cancel, optional `?reason=`. Frees the time at once; the row is kept with `status: "cancelled"`. Same window and `?force=true` rules as PATCH. Returns the updated `Booking` |
| GET | `/customers`, `/customers/{id}` | **Built.** Owner/manager only (staff `403`). List has `q` (name or phone) and cursor pagination, with `booking_count` and `last_visit_at` (latest completed visit); managers see customers who booked at their location. Detail adds `bookings`, newest first |

The notice window is the location's `cancellation_window_minutes` if set, else the business's (default 120). Every change is recorded in an append-only audit trail.

## Booking emails (M7, built)

No endpoints of their own. Every create, reschedule and cancel (from the dashboard or the voice agent) writes its emails to an outbox in the same transaction, and a sender delivers them through Amazon SES:

| Recipient | When |
|---|---|
| The customer, if the booking has `customer.email` | confirmation, "booking moved", "booking cancelled", and a reminder 24 hours before (sent at once if booked less than a day ahead, skipped if booked less than 2 hours ahead; replaced when the booking moves, dropped when it is cancelled) |
| The business's `notification_email` (`PATCH /business`; `""` turns it off) | an alert for every new, moved or cancelled booking, saying whether it came by phone or from the dashboard |

Editing notes or recording an outcome sends nothing. Failed sends are retried (1, 2, 4, 8 minutes) and given up after 5 attempts. Without `EMAIL_FROM` configured the emails are queued but never sent.

## Calls and the voice agent (M6, built)

```ts
type CallOutcome = "booked" | "rescheduled" | "cancelled" | "info_only" | "failed" | "abandoned";
type CallLog = {
  id: string; retell_call_id: string; location_id: string;
  from_number: string | null; started_at: string; ended_at: string | null; duration_seconds: number | null;
  outcome: CallOutcome; summary: string | null;
  transcript: { role: "agent" | "user"; text: string }[] | null;
  booking_id: string | null;                                   // the booking this call made, moved or cancelled
};
type CallStats = { total: number; by_outcome: Record<CallOutcome, number>; per_day: { date: string; count: number }[] };
```

| Method | Path | Notes |
|---|---|---|
| GET | `/calls` | Newest first. Filters `location_id, outcome, from, to` (`YYYY-MM-DD`, inclusive, the salon's local days), cursor pagination (`limit` up to 200). Owners see all locations, managers their own, staff get `403` |
| GET | `/calls/stats` | Same filters. `by_outcome` always lists all six outcomes; `per_day` counts by each location's local day |
| GET | `/calls/{id}` | One call with its transcript; another location or business is `404` |

Outcomes: `booked`, `rescheduled` and `cancelled` are set only when a tool really changed a booking (the latest one wins); a call that did none of those is `info_only`, unless nobody spoke (`abandoned`) or Retell reported an error (`failed`).

### Calling the receptionist from the browser (Twilio Voice SDK)

| Method | Path | Notes |
|---|---|---|
| POST | `/twilio/token` | Any signed-in user. `{token, identity, expires_in}`: a Twilio Voice access token (outgoing calls only, 1 hour) for `@twilio/voice-sdk`. `503 browser_calling_not_configured` until the `TWILIO_*` settings exist |
| POST | `/twilio/voice` | Called by Twilio, not the dashboard; authenticated by `X-Twilio-Signature`. Answers TwiML that dials the configured salon line (`TWILIO_DIAL_TO`, a number or `sip:` URI), 15-minute limit. Whatever the request asks to dial is ignored, so it cannot be used to call anywhere else |

A call presented with the salon's own number as caller ID (as browser calls are) has no customer number: the agent asks for one.

### Endpoints Retell calls (not for the dashboard)

Authenticated by the `X-Retell-Signature` header (HMAC of the body with the Retell API key; requests more than 5 minutes old are refused), not by a user token. Without `RETELL_API_KEY` configured they answer `503 voice_not_configured`; a bad signature is `401 invalid_signature`.

**`POST /webhooks/retell`** takes `{event, call}` for `call_started`, `call_ended` and `call_analyzed`, and answers `{status: "recorded" | "ignored" | "unrouted"}`. Events can repeat or arrive out of order; each updates the same row. A call that can't be matched to a location is acknowledged (`unrouted`) so Retell does not retry forever.

**`POST /retell/functions/{tool}`** takes `{name, args, call}` (Retell's "payload: args only" setting must be off). The salon is found from `call.to_number` matched to a location's phone, or from a `location_id` dynamic variable. Every tool answers `200` with `{success: boolean, message: string, ...}`; `success: true` means the database really changed. Failures carry an `error` code instead.

| Tool | Arguments | Success data |
|---|---|---|
| `get_salon_info` | none | `name, address, phone, opening_hours[], today, today_spoken, time_now, timezone` |
| `list_services` | none | `services[{service_id, name, category, minutes, price, currency}]` |
| `list_staff` | `service_id?` | `staff[{staff_id, name, title}]` |
| `check_availability` | `service_id, date (YYYY-MM-DD), staff_id?, time_of_day? (morning, afternoon, evening), after? (HH:MM)` | `slots[{date, time (24h HH:MM), spoken, staff_id, staff_name}]` (at most 6, from the first day with space within 7 days), `slots_date` |
| `create_booking` | `service_id, staff_id, date, time, customer_name, phone?, notes?` | `reference, reference_spoken, service, staff, when, price, currency, phone` (the number the booking is under, to confirm) |
| `find_my_bookings` | `phone?, customer_name?` (name required with another number) | `bookings[{reference, reference_spoken, service, staff, staff_id, when}]` |
| `reschedule_booking` | `reference, customer_name, date, time, phone?, staff_id?` | `reference, when` |
| `cancel_booking` | `reference, customer_name, phone?, reason?` | `reference` |

Failure codes: `unknown_salon`, `unknown_tool`, `invalid_arguments` (the message names the fields), `invalid_request`, `invalid_time`, `past_date`, `need_phone`, `invalid_phone` (too many or too few digits for the country), `slot_unavailable` (with `alternatives`, same shape as `slots`), `not_found` (reference, name or phone don't match one upcoming booking), `not_active`, `too_late_to_change` (inside the notice period; the voice agent can never override it), `call_mismatch`, `failed`.

Times in arguments and results are the location's local time. Repeating a tool call within the same call is a retry: it returns the original booking instead of creating another. Bookings made by phone have `source: "voice"` and a `call_id`.

## Built in M1: additions and clarifications

- `Invite` response: `{id, email, role, location_id, expires_at, token?}`.
- Extra error codes: `invalid_credentials` (401, also for deactivated users), `invalid_invite` (400), `last_active_location` (409), `last_owner` (409), `location_conflict` / `signup_conflict` (409, rare races), `method_not_allowed` (405).
- Business users only: a platform admin calling business endpoints gets `403`. `GET /auth/me` works for everyone.
- Only an owner may change a location's `is_active`; managers may edit their own location otherwise (including its cancellation window).
- A new access token is not needed after a role change or deactivation: the backend reads the user's current state on every request.
