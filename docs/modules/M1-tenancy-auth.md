# M1 — Tenancy + Auth

**Track:** A (backend core) · **Owns:** `backend/` · **Depends on:** M0 · **Unblocks:** M2, real API for the dashboard

## Goal
Multi-tenant foundation: businesses with one or many locations, users with roles, secure login, and a tenant-scoping mechanism that every later module reuses so cross-tenant data leaks are structurally hard.

## Scope
### Data model (Alembic migration `0002`)
- `businesses`: id (uuid), name, slug (unique), location_mode (`single`/`multiple`), default_timezone, cancellation_window_minutes (default 120, ≥ 0), timestamps.
- `locations`: id, business_id (FK, indexed), name, slug (unique per business), timezone (validated IANA), phone (E.164), address fields, cancellation_window_minutes (nullable override), is_active, timestamps.
- `users`: id, business_id (nullable only for `platform_admin`), email (`citext`, globally unique), password_hash, full_name, role (Postgres enum), location_id (nullable; required for manager/staff), is_active, last_login_at, timestamps. Check constraints for the role/location rules.
- `refresh_tokens`: id, user_id, family_id, token_hash (SHA-256, unique), expires_at, revoked_at, replaced_by_id, created_at, user_agent/ip (optional).
- `invites`: id, business_id, location_id, email, role, token_hash, expires_at, accepted_at, invited_by.

### Auth
- Passwords: Argon2id (`pwdlib[argon2]` or `argon2-cffi`). Minimum 10 characters.
- Access JWT (PyJWT, HS256, ~15 min) with `sub`, `bid` (business), `role`, `exp`, `iat`, `jti`. Secret from settings (`JWT_SECRET`, required outside local/test).
- Refresh token: random 256-bit, stored hashed, `httpOnly` cookie per [api-contract.md](../api-contract.md). Rotation on every refresh; **reuse of a rotated token revokes the whole family**.
- Login: generic "invalid email or password" for both unknown email and wrong password; equal-time path (hash a dummy password when the user is missing).
- Endpoints exactly as in [api-contract.md § Auth / Business, locations, users](../api-contract.md).

### Tenant scoping (the important part)
- A `CurrentPrincipal` dependency resolves the user from the bearer token: `user_id`, `business_id`, `role`, `location_ids`.
- Role guard dependency, e.g. `require_roles("owner", "manager")`.
- A scoped-query helper / repository base that **always** adds `business_id = principal.business_id`, and for managers/staff the location restriction. Services never build unscoped queries for tenant tables.
- Other-tenant IDs → `404 not_found`.

### Cross-cutting
- Standard error format from the contract (exception handlers for validation, HTTP, domain errors).
- Settings additions: `JWT_SECRET`, `ACCESS_TOKEN_TTL_SECONDS`, `REFRESH_TOKEN_TTL_DAYS`, `COOKIE_SECURE`.
- Seed command (`python -m app.scripts.seed`) creating a demo business with 2 locations, an owner, a manager, and a staff user.

## Tests (must all pass, real Postgres)
- Signup single vs multiple; validation errors; duplicate email → 409.
- Login success / failure (same error message), inactive user blocked.
- Access token expiry and tampering rejected.
- Refresh rotation; reuse detection revokes family; logout revokes.
- Role guards for every endpoint (owner / manager / staff / anonymous matrix).
- **Cross-tenant isolation:** a user of business A gets 404 for every read/update/delete on business B's locations, users, and invites. Write this as a reusable fixture/helper later modules can extend.
- Manager limited to their own location; cannot invite owners.
- Cannot deactivate the last active location.
- Migration upgrade/downgrade round-trip still passes; `alembic check` clean.

## Done when
- [ ] All endpoints above implemented and documented in OpenAPI (summaries, response models, error responses).
- [ ] `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest` green locally and in CI.
- [ ] [api-contract.md](../api-contract.md) updated if any shape changed.
- [ ] PR opened from this worktree's branch with a summary of endpoints, tables, and test coverage.

## Out of scope
Services/staff/schedules (M2), emails for invites (M7 — return the token in non-production responses instead), rate limiting (note it as a TODO in the PR).
