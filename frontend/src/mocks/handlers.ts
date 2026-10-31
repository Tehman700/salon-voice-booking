import { delay, HttpResponse, type PathParams } from "msw";
import { http } from "msw/http";

import type {
  AuthResponse,
  Booking,
  BookingStatus,
  CallOutcome,
  CallStats,
  CreateBookingRequest,
  Customer,
  CustomerDetail,
  Location,
  LocationInput,
  LocationPatch,
  Me,
  Service,
  SignupRequest,
  Slot,
  Staff,
  UpdateBookingRequest,
  WorkingHours,
} from "@/lib/api/types";

import { getDb, persist } from "./db";
import { makeReference, mockId, type MockDb, type MockUser } from "./seed";

/** Matches `/api/...` on any origin (browser origin in dev/e2e, jsdom origin in unit tests). */
const API = "*/api";
const ACCESS_TTL_SECONDS = 900;

type Ctx = { db: MockDb; user: MockUser };

function error(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
  return HttpResponse.json({ error: { code, message, details } }, { status });
}

const notFound = () => error(404, "not_found", "Not found.");
const forbidden = () => error(403, "forbidden", "You don't have permission to do that.");

function stripTenant<T extends { business_id: string }>(record: T): Omit<T, "business_id"> {
  const { business_id: _ignored, ...rest } = record;
  void _ignored;
  return rest;
}

function nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

// ---- Auth helpers ----

function accessTokenFor(userId: string) {
  return `mock.${userId}.${Date.now() + ACCESS_TTL_SECONDS * 1000}`;
}

function buildMe(db: MockDb, user: MockUser): Me {
  const business = db.businesses.find((b) => b.id === user.business_id) ?? null;
  const locationIds =
    user.role === "owner" || user.role === "platform_admin"
      ? db.locations.filter((l) => l.business_id === user.business_id && l.is_active).map((l) => l.id)
      : user.location_id
        ? [user.location_id]
        : [];
  return {
    id: user.id,
    email: user.email,
    full_name: user.full_name,
    role: user.role,
    business: business ? { id: business.id, name: business.name, location_mode: business.location_mode } : null,
    location_ids: locationIds,
  };
}

function authResponse(db: MockDb, user: MockUser, init: { status?: number } = {}) {
  const refresh = crypto.randomUUID();
  db.refreshTokens[refresh] = user.id;
  user.last_login_at = nowIso();
  persist();
  const body: AuthResponse = {
    access_token: accessTokenFor(user.id),
    token_type: "bearer",
    expires_in: ACCESS_TTL_SECONDS,
    user: buildMe(db, user),
  };
  // Not httpOnly here only because MSW mirrors mocked cookies into document.cookie. The cookie path
  // is the one the browser sees through the Next.js proxy (see api-contract.md, Auth).
  return HttpResponse.json(body, {
    status: init.status ?? 200,
    headers: { "Set-Cookie": `refresh_token=${refresh}; Path=/api/auth; SameSite=Lax; Max-Age=2592000` },
  });
}

/** Resolve the caller from the bearer token, or return the 401 response to send. */
function authenticate(request: Request): Ctx | Response {
  const db = getDb();
  const header = request.headers.get("Authorization") ?? "";
  const match = /^Bearer mock\.([^.]+)\.(\d+)$/.exec(header);
  if (!match) return error(401, "not_authenticated", "Sign in to continue.");
  if (Number(match[2]) < Date.now()) return error(401, "token_expired", "Your session expired.");
  const user = db.users.find((u) => u.id === match[1] && u.is_active);
  if (!user) return error(401, "not_authenticated", "Sign in to continue.");
  return { db, user };
}

/** Wrap a resolver so it only runs for an authenticated caller. */
function authed<P extends Record<string, string> = Record<string, string>>(
  resolver: (args: { request: Request; params: P; ctx: Ctx }) => Response | Promise<Response>,
) {
  return async ({ request, params }: { request: Request; params: PathParams }) => {
    await delay();
    const ctx = authenticate(request);
    if (ctx instanceof Response) return ctx;
    return resolver({ request, params: params as P, ctx });
  };
}

/** Pending invitations by token (kept in memory only; enough for a demo session). */
const invites = new Map<string, { email: string; role: MockUser["role"]; location_id: string | null; business_id: string }>();

const isManager = (user: MockUser) => user.role === "owner" || user.role === "manager" || user.role === "platform_admin";

// ---- Domain helpers ----

function tenantLocations({ db, user }: Ctx) {
  return db.locations.filter((l) => l.business_id === user.business_id);
}

function effectiveWindow(db: MockDb, location: Location & { business_id: string }) {
  const business = db.businesses.find((b) => b.id === location.business_id)!;
  return location.cancellation_window_minutes ?? business.cancellation_window_minutes;
}

function refreshEffectiveWindows(db: MockDb, businessId: string) {
  for (const location of db.locations.filter((l) => l.business_id === businessId)) {
    location.effective_cancellation_window_minutes = effectiveWindow(db, location);
  }
}

function overlaps(aStart: string, aEnd: string, bStart: string, bEnd: string) {
  return new Date(aStart) < new Date(bEnd) && new Date(bStart) < new Date(aEnd);
}

function serviceFor(db: MockDb, serviceId: string, locationId: string) {
  const service = db.services.find((s) => s.id === serviceId);
  if (!service) return null;
  const override = service.location_overrides.find((o) => o.location_id === locationId);
  return {
    service,
    duration: override?.duration_minutes ?? service.duration_minutes,
    price: override?.price_minor ?? service.price_minor,
    offered: override ? override.is_offered : true,
  };
}

function staffConflict(db: MockDb, staffId: string, startsAt: string, endsAt: string, ignoreId?: string) {
  return db.bookings.some(
    (b) => b.staff_id === staffId && b.status === "booked" && b.id !== ignoreId && overlaps(b.starts_at, b.ends_at, startsAt, endsAt),
  );
}

/** Location-local (Asia/Karachi-style fixed offset) helpers for availability. */
function tzOffsetMinutes(timeZone: string, at: Date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).formatToParts(at);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"));
  return Math.round((asUtc - at.getTime()) / 60_000);
}

function localToUtc(date: string, time: string, timeZone: string) {
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  const guess = Date.UTC(y, m - 1, d, hh, mm);
  const offset = tzOffsetMinutes(timeZone, new Date(guess));
  return new Date(guess - offset * 60_000);
}

function computeSlots(
  db: MockDb,
  businessId: string,
  req: { location_id: string; service_id: string; staff_id?: string; date_from: string; date_to: string },
): Slot[] {
  const location = db.locations.find((l) => l.id === req.location_id && l.business_id === businessId);
  const info = serviceFor(db, req.service_id, req.location_id);
  if (!location || !info || !info.offered) return [];
  const members = db.staff.filter(
    (s) =>
      s.business_id === businessId &&
      s.is_active &&
      s.location_id === location.id &&
      s.service_ids.includes(req.service_id) &&
      (!req.staff_id || s.id === req.staff_id),
  );
  const slots: Slot[] = [];
  const start = new Date(`${req.date_from}T00:00:00Z`);
  const end = new Date(`${req.date_to}T00:00:00Z`);
  for (let day = new Date(start); day <= end; day.setUTCDate(day.getUTCDate() + 1)) {
    const date = day.toISOString().slice(0, 10);
    const weekday = ((day.getUTCDay() + 6) % 7) as 0 | 1 | 2 | 3 | 4 | 5 | 6;
    for (const member of members) {
      for (const block of (db.hours[member.id] ?? []).filter((h) => h.weekday === weekday)) {
        const blockEnd = localToUtc(date, block.end, location.timezone).getTime();
        for (let t = localToUtc(date, block.start, location.timezone).getTime(); t + info.duration * 60_000 <= blockEnd; t += 30 * 60_000) {
          if (t < Date.now()) continue;
          const startsAt = new Date(t).toISOString().replace(".000Z", "Z");
          const endsAt = new Date(t + info.duration * 60_000).toISOString().replace(".000Z", "Z");
          const onLeave = db.timeOff.some((o) => o.staff_id === member.id && overlaps(o.starts_at, o.ends_at, startsAt, endsAt));
          if (onLeave || staffConflict(db, member.id, startsAt, endsAt)) continue;
          slots.push({ starts_at: startsAt, ends_at: endsAt, staff_id: member.id, staff_name: member.full_name });
        }
      }
    }
  }
  return slots.sort((a, b) => a.starts_at.localeCompare(b.starts_at));
}

function paginate<T>(items: T[], url: URL) {
  const limit = Math.min(Number(url.searchParams.get("limit") ?? 50) || 50, 500);
  const offset = Number(url.searchParams.get("cursor") ?? 0) || 0;
  const page = items.slice(offset, offset + limit);
  return { items: page, next_cursor: offset + limit < items.length ? String(offset + limit) : null };
}

/** `from`/`to` accept a date (YYYY-MM-DD) or a full timestamp. */
function boundary(value: string | null, endOfDay = false) {
  if (!value) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T${endOfDay ? "23:59:59" : "00:00:00"}Z`);
  return new Date(value);
}

function customerSummary(db: MockDb, customer: MockDb["customers"][number]): Customer {
  const bookings = db.bookings.filter((b) => b.customer.id === customer.id);
  const visits = bookings.filter((b) => b.status === "completed").map((b) => b.starts_at).sort();
  return {
    ...stripTenant(customer),
    booking_count: bookings.length,
    last_visit_at: visits.at(-1) ?? null,
  };
}

function validationError(details: Record<string, string[]>) {
  return error(422, "validation_error", "Please fix the highlighted fields.", details);
}

export const handlers = [
  // ---- Auth ----
  http.post(`${API}/auth/login`, async ({ request }) => {
    await delay();
    const db = getDb();
    const body = (await request.json()) as { email?: string; password?: string };
    const user = db.users.find((u) => u.email.toLowerCase() === (body.email ?? "").toLowerCase());
    if (!user || user.password !== body.password || !user.is_active) {
      return error(401, "invalid_credentials", "Invalid email or password.");
    }
    return authResponse(db, user);
  }),

  http.post(`${API}/auth/signup`, async ({ request }) => {
    await delay();
    const db = getDb();
    const body = (await request.json()) as SignupRequest;
    const details: Record<string, string[]> = {};
    if (!body.business_name?.trim()) details.business_name = ["Required"];
    if (!body.owner_full_name?.trim()) details.owner_full_name = ["Required"];
    if (!body.password || body.password.length < 10) details.password = ["Must be at least 10 characters"];
    if (!body.locations?.length) details.locations = ["Add at least one location"];
    if (body.location_mode === "single" && body.locations?.length !== 1) details.locations = ["Exactly one location"];
    if (Object.keys(details).length) return validationError(details);
    if (db.users.some((u) => u.email.toLowerCase() === body.email.toLowerCase())) {
      return error(409, "email_taken", "An account with that email already exists.");
    }
    const businessId = mockId();
    db.businesses.push({
      id: businessId,
      name: body.business_name.trim(),
      slug: body.business_name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-"),
      location_mode: body.location_mode,
      default_timezone: body.locations[0].timezone,
      cancellation_window_minutes: 120,
    });
    for (const input of body.locations) {
      db.locations.push({
        ...input,
        business_id: businessId,
        id: mockId(),
        slug: input.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
        is_active: true,
        cancellation_window_minutes: null,
        effective_cancellation_window_minutes: 120,
      });
    }
    const user: MockUser = {
      business_id: businessId,
      id: mockId(),
      email: body.email,
      full_name: body.owner_full_name.trim(),
      role: "owner",
      location_id: null,
      is_active: true,
      last_login_at: null,
      password: body.password,
    };
    db.users.push(user);
    return authResponse(db, user, { status: 201 });
  }),

  http.post(`${API}/auth/refresh`, async ({ cookies }) => {
    await delay();
    const db = getDb();
    const token = cookies.refresh_token;
    const userId = token ? db.refreshTokens[token] : undefined;
    const user = userId ? db.users.find((u) => u.id === userId && u.is_active) : undefined;
    if (!token || !user) return error(401, "not_authenticated", "Sign in to continue.");
    delete db.refreshTokens[token]; // rotate
    return authResponse(db, user);
  }),

  http.post(`${API}/auth/logout`, async ({ cookies }) => {
    await delay();
    const db = getDb();
    if (cookies.refresh_token) delete db.refreshTokens[cookies.refresh_token];
    persist();
    return new HttpResponse(null, {
      status: 204,
      headers: { "Set-Cookie": "refresh_token=; Path=/api/auth; SameSite=Lax; Max-Age=0" },
    });
  }),

  http.get(`${API}/auth/me`, authed(({ ctx }) => HttpResponse.json(buildMe(ctx.db, ctx.user)))),

  // ---- Business ----
  http.get(
    `${API}/business`,
    authed(({ ctx }) => HttpResponse.json(ctx.db.businesses.find((b) => b.id === ctx.user.business_id))),
  ),

  http.patch(
    `${API}/business`,
    authed(async ({ request, ctx }) => {
      if (ctx.user.role !== "owner") return forbidden();
      const body = (await request.json()) as Record<string, unknown>;
      const business = ctx.db.businesses.find((b) => b.id === ctx.user.business_id)!;
      if (typeof body.name === "string") {
        if (!body.name.trim()) return validationError({ name: ["Required"] });
        business.name = body.name.trim();
      }
      if (typeof body.default_timezone === "string") business.default_timezone = body.default_timezone;
      if (typeof body.cancellation_window_minutes === "number") {
        if (body.cancellation_window_minutes < 0) return validationError({ cancellation_window_minutes: ["Must be 0 or more"] });
        business.cancellation_window_minutes = body.cancellation_window_minutes;
        refreshEffectiveWindows(ctx.db, business.id);
      }
      persist();
      return HttpResponse.json(business);
    }),
  ),

  // ---- Locations ----
  http.get(
    `${API}/locations`,
    authed(({ ctx }) => {
      const allowed = buildMe(ctx.db, ctx.user).location_ids;
      const list = tenantLocations(ctx).filter((l) => isManager(ctx.user) || allowed.includes(l.id));
      return HttpResponse.json({ items: list.map(stripTenant), next_cursor: null });
    }),
  ),

  http.post(
    `${API}/locations`,
    authed(async ({ request, ctx }) => {
      if (ctx.user.role !== "owner") return forbidden();
      const body = (await request.json()) as LocationInput;
      if (!body.name?.trim()) return validationError({ name: ["Required"] });
      if (!body.timezone) return validationError({ timezone: ["Required"] });
      const business = ctx.db.businesses.find((b) => b.id === ctx.user.business_id)!;
      const location = {
        ...body,
        business_id: business.id,
        id: mockId(),
        slug: body.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
        is_active: true,
        cancellation_window_minutes: null,
        effective_cancellation_window_minutes: business.cancellation_window_minutes,
      };
      ctx.db.locations.push(location);
      if (tenantLocations(ctx).filter((l) => l.is_active).length > 1) business.location_mode = "multiple";
      persist();
      return HttpResponse.json(stripTenant(location), { status: 201 });
    }),
  ),

  http.get(
    `${API}/locations/:id`,
    authed<{ id: string }>(({ params, ctx }) => {
      const location = tenantLocations(ctx).find((l) => l.id === params.id);
      return location ? HttpResponse.json(stripTenant(location)) : notFound();
    }),
  ),

  http.patch(
    `${API}/locations/:id`,
    authed<{ id: string }>(async ({ request, params, ctx }) => {
      const location = tenantLocations(ctx).find((l) => l.id === params.id);
      if (!location) return notFound();
      if (!isManager(ctx.user) || (ctx.user.role === "manager" && ctx.user.location_id !== location.id)) return forbidden();
      const body = (await request.json()) as LocationPatch;
      if (body.name !== undefined && !body.name.trim()) return validationError({ name: ["Required"] });
      Object.assign(location, body);
      location.effective_cancellation_window_minutes = effectiveWindow(ctx.db, location);
      persist();
      return HttpResponse.json(stripTenant(location));
    }),
  ),

  http.delete(
    `${API}/locations/:id`,
    authed<{ id: string }>(({ params, ctx }) => {
      if (ctx.user.role !== "owner") return forbidden();
      const location = tenantLocations(ctx).find((l) => l.id === params.id);
      if (!location) return notFound();
      if (tenantLocations(ctx).filter((l) => l.is_active).length <= 1 && location.is_active) {
        return error(409, "last_location", "You can't deactivate your only active location.");
      }
      location.is_active = false;
      persist();
      return new HttpResponse(null, { status: 204 });
    }),
  ),

  // ---- Services ----
  http.get(
    `${API}/services`,
    authed(({ ctx }) =>
      HttpResponse.json(ctx.db.services.filter((s) => s.business_id === ctx.user.business_id).map(stripTenant)),
    ),
  ),

  http.post(
    `${API}/services`,
    authed(async ({ request, ctx }) => {
      if (!isManager(ctx.user)) return forbidden();
      const body = (await request.json()) as Omit<Service, "id">;
      const details: Record<string, string[]> = {};
      if (!body.name?.trim()) details.name = ["Required"];
      if (!(body.duration_minutes > 0)) details.duration_minutes = ["Must be more than 0"];
      if (!(body.price_minor >= 0)) details.price_minor = ["Must be 0 or more"];
      if (Object.keys(details).length) return validationError(details);
      const service = { ...body, business_id: ctx.user.business_id, id: mockId() };
      ctx.db.services.push(service);
      persist();
      return HttpResponse.json(stripTenant(service), { status: 201 });
    }),
  ),

  http.patch(
    `${API}/services/:id`,
    authed<{ id: string }>(async ({ request, params, ctx }) => {
      if (!isManager(ctx.user)) return forbidden();
      const service = ctx.db.services.find((s) => s.id === params.id && s.business_id === ctx.user.business_id);
      if (!service) return notFound();
      Object.assign(service, await request.json());
      persist();
      return HttpResponse.json(stripTenant(service));
    }),
  ),

  http.delete(
    `${API}/services/:id`,
    authed<{ id: string }>(({ params, ctx }) => {
      if (!isManager(ctx.user)) return forbidden();
      const index = ctx.db.services.findIndex((s) => s.id === params.id && s.business_id === ctx.user.business_id);
      if (index === -1) return notFound();
      ctx.db.services.splice(index, 1);
      persist();
      return new HttpResponse(null, { status: 204 });
    }),
  ),

  // ---- Staff ----
  http.get(
    `${API}/staff`,
    authed(({ request, ctx }) => {
      const locationId = new URL(request.url).searchParams.get("location_id");
      const list = ctx.db.staff.filter(
        (s) => s.business_id === ctx.user.business_id && (!locationId || s.location_id === locationId),
      );
      return HttpResponse.json(list.map(stripTenant));
    }),
  ),

  http.post(
    `${API}/staff`,
    authed(async ({ request, ctx }) => {
      if (!isManager(ctx.user)) return forbidden();
      const body = (await request.json()) as Omit<Staff, "id" | "user_id">;
      if (!body.full_name?.trim()) return validationError({ full_name: ["Required"] });
      const member = { ...body, business_id: ctx.user.business_id, id: mockId(), user_id: null };
      ctx.db.staff.push(member);
      ctx.db.hours[member.id] = [];
      persist();
      return HttpResponse.json(stripTenant(member), { status: 201 });
    }),
  ),

  http.patch(
    `${API}/staff/:id`,
    authed<{ id: string }>(async ({ request, params, ctx }) => {
      if (!isManager(ctx.user)) return forbidden();
      const member = ctx.db.staff.find((s) => s.id === params.id && s.business_id === ctx.user.business_id);
      if (!member) return notFound();
      Object.assign(member, await request.json());
      persist();
      return HttpResponse.json(stripTenant(member));
    }),
  ),

  http.delete(
    `${API}/staff/:id`,
    authed<{ id: string }>(({ params, ctx }) => {
      if (!isManager(ctx.user)) return forbidden();
      const member = ctx.db.staff.find((s) => s.id === params.id && s.business_id === ctx.user.business_id);
      if (!member) return notFound();
      member.is_active = false;
      persist();
      return new HttpResponse(null, { status: 204 });
    }),
  ),

  http.get(
    `${API}/staff/:id/hours`,
    authed<{ id: string }>(({ params, ctx }) => {
      const member = ctx.db.staff.find((s) => s.id === params.id && s.business_id === ctx.user.business_id);
      return member ? HttpResponse.json(ctx.db.hours[member.id] ?? []) : notFound();
    }),
  ),

  http.put(
    `${API}/staff/:id/hours`,
    authed<{ id: string }>(async ({ request, params, ctx }) => {
      if (!isManager(ctx.user)) return forbidden();
      const member = ctx.db.staff.find((s) => s.id === params.id && s.business_id === ctx.user.business_id);
      if (!member) return notFound();
      const body = (await request.json()) as WorkingHours;
      const invalid = body.find((h) => h.start >= h.end);
      if (invalid) return validationError({ hours: [`Start must be before end on weekday ${invalid.weekday}`] });
      ctx.db.hours[member.id] = body;
      persist();
      return HttpResponse.json(body);
    }),
  ),

  http.get(
    `${API}/staff/:id/time-off`,
    authed<{ id: string }>(({ params, ctx }) => {
      const member = ctx.db.staff.find((s) => s.id === params.id && s.business_id === ctx.user.business_id);
      if (!member) return notFound();
      return HttpResponse.json(ctx.db.timeOff.filter((t) => t.staff_id === member.id).map(stripTenant));
    }),
  ),

  http.post(
    `${API}/staff/:id/time-off`,
    authed<{ id: string }>(async ({ request, params, ctx }) => {
      if (!isManager(ctx.user)) return forbidden();
      const member = ctx.db.staff.find((s) => s.id === params.id && s.business_id === ctx.user.business_id);
      if (!member) return notFound();
      const body = (await request.json()) as { starts_at: string; ends_at: string; reason: string | null };
      if (!body.starts_at || !body.ends_at || body.starts_at >= body.ends_at) {
        return validationError({ ends_at: ["End must be after start"] });
      }
      const entry = { ...body, business_id: ctx.user.business_id, id: mockId(), staff_id: member.id };
      ctx.db.timeOff.push(entry);
      persist();
      return HttpResponse.json(stripTenant(entry), { status: 201 });
    }),
  ),

  // ---- Availability and bookings ----
  http.post(
    `${API}/availability`,
    authed(async ({ request, ctx }) => {
      const body = (await request.json()) as Parameters<typeof computeSlots>[2];
      return HttpResponse.json({ slots: computeSlots(ctx.db, ctx.user.business_id, body) });
    }),
  ),

  http.get(
    `${API}/bookings`,
    authed(({ request, ctx }) => {
      const url = new URL(request.url);
      const p = url.searchParams;
      const from = boundary(p.get("from"));
      const to = boundary(p.get("to"), true);
      const q = p.get("q")?.trim().toLowerCase();
      const ownStaff = ctx.user.role === "staff" ? ctx.db.staff.find((s) => s.user_id === ctx.user.id)?.id ?? "none" : null;
      const list = ctx.db.bookings
        .filter((b) => b.business_id === ctx.user.business_id)
        .filter((b) => !ownStaff || b.staff_id === ownStaff)
        .filter((b) => !p.get("location_id") || b.location_id === p.get("location_id"))
        .filter((b) => !p.get("staff_id") || b.staff_id === p.get("staff_id"))
        .filter((b) => !p.get("status") || b.status === p.get("status"))
        .filter((b) => !p.get("source") || b.source === p.get("source"))
        .filter((b) => !from || new Date(b.starts_at) >= from)
        .filter((b) => !to || new Date(b.starts_at) <= to)
        .filter(
          (b) =>
            !q ||
            b.customer.full_name.toLowerCase().includes(q) ||
            b.customer.phone.includes(q) ||
            b.reference.toLowerCase().includes(q),
        )
        .sort((a, b) => a.starts_at.localeCompare(b.starts_at))
        .map(stripTenant);
      return HttpResponse.json(paginate(list, url));
    }),
  ),

  http.get(
    `${API}/bookings/:id`,
    authed<{ id: string }>(({ params, ctx }) => {
      const booking = ctx.db.bookings.find((b) => b.id === params.id && b.business_id === ctx.user.business_id);
      return booking ? HttpResponse.json(stripTenant(booking)) : notFound();
    }),
  ),

  http.post(
    `${API}/bookings`,
    authed(async ({ request, ctx }) => {
      const key = request.headers.get("Idempotency-Key");
      if (!key) return validationError({ "Idempotency-Key": ["Header is required"] });
      const body = (await request.json()) as CreateBookingRequest;
      const details: Record<string, string[]> = {};
      if (!body.customer?.full_name?.trim()) details["customer.full_name"] = ["Required"];
      if (!body.customer?.phone?.trim()) details["customer.phone"] = ["Required"];
      if (!body.starts_at) details.starts_at = ["Required"];
      if (Object.keys(details).length) return validationError(details);

      const location = tenantLocations(ctx).find((l) => l.id === body.location_id);
      const member = ctx.db.staff.find((s) => s.id === body.staff_id && s.business_id === ctx.user.business_id);
      const info = serviceFor(ctx.db, body.service_id, body.location_id);
      if (!location || !member || !info || info.service.business_id !== ctx.user.business_id) return notFound();

      const endsAt = new Date(new Date(body.starts_at).getTime() + info.duration * 60_000).toISOString().replace(".000Z", "Z");
      if (staffConflict(ctx.db, member.id, body.starts_at, endsAt)) {
        const day = body.starts_at.slice(0, 10);
        const alternatives = computeSlots(ctx.db, ctx.user.business_id, {
          location_id: location.id, service_id: info.service.id, staff_id: member.id, date_from: day, date_to: day,
        }).slice(0, 3);
        return error(409, "slot_unavailable", "That time was just booked.", { alternatives });
      }

      let customer = ctx.db.customers.find((c) => c.business_id === ctx.user.business_id && c.phone === body.customer.phone);
      if (!customer) {
        customer = {
          business_id: ctx.user.business_id, id: mockId(), full_name: body.customer.full_name.trim(),
          phone: body.customer.phone.trim(), email: body.customer.email ?? null, notes: null, created_at: nowIso(),
        };
        ctx.db.customers.push(customer);
      }
      const booking: Booking & { business_id: string } = {
        business_id: ctx.user.business_id,
        id: mockId(),
        reference: makeReference(),
        location_id: location.id,
        service_id: info.service.id,
        staff_id: member.id,
        customer: { id: customer.id, full_name: customer.full_name, phone: customer.phone, email: customer.email },
        starts_at: body.starts_at,
        ends_at: endsAt,
        status: "booked",
        source: "dashboard",
        call_id: null,
        price_minor: info.price,
        currency: info.service.currency,
        notes: body.notes ?? null,
        created_at: nowIso(),
        cancelled_at: null,
        cancellation_reason: null,
      };
      ctx.db.bookings.push(booking);
      persist();
      return HttpResponse.json(stripTenant(booking), { status: 201 });
    }),
  ),

  http.patch(
    `${API}/bookings/:id`,
    authed<{ id: string }>(async ({ request, params, ctx }) => {
      const booking = ctx.db.bookings.find((b) => b.id === params.id && b.business_id === ctx.user.business_id);
      if (!booking) return notFound();
      const body = (await request.json()) as UpdateBookingRequest;
      if (body.starts_at || body.staff_id) {
        if (booking.status !== "booked") return error(409, "booking_not_active", "Only active bookings can be rescheduled.");
        const startsAt = body.starts_at ?? booking.starts_at;
        const staffId = body.staff_id ?? booking.staff_id;
        const minutes = (new Date(booking.ends_at).getTime() - new Date(booking.starts_at).getTime()) / 60_000;
        const endsAt = new Date(new Date(startsAt).getTime() + minutes * 60_000).toISOString().replace(".000Z", "Z");
        if (staffConflict(ctx.db, staffId, startsAt, endsAt, booking.id)) {
          return error(409, "slot_unavailable", "That time was just booked.", { alternatives: [] });
        }
        Object.assign(booking, { starts_at: startsAt, ends_at: endsAt, staff_id: staffId });
      }
      if (body.notes !== undefined) booking.notes = body.notes;
      persist();
      return HttpResponse.json(stripTenant(booking));
    }),
  ),

  http.delete(
    `${API}/bookings/:id`,
    authed<{ id: string }>(({ request, params, ctx }) => {
      const booking = ctx.db.bookings.find((b) => b.id === params.id && b.business_id === ctx.user.business_id);
      if (!booking) return notFound();
      if (booking.status !== "booked") return error(409, "booking_not_active", "This booking is no longer active.");
      const force = new URL(request.url).searchParams.get("force") === "true";
      const location = ctx.db.locations.find((l) => l.id === booking.location_id)!;
      const minutesUntil = (new Date(booking.starts_at).getTime() - Date.now()) / 60_000;
      const windowMinutes = effectiveWindow(ctx.db, location);
      if (minutesUntil < windowMinutes && !(force && isManager(ctx.user))) {
        return error(409, "cancellation_window_passed", `Bookings can't be cancelled less than ${windowMinutes} minutes before the start.`, {
          window_minutes: windowMinutes,
        });
      }
      booking.status = "cancelled" satisfies BookingStatus;
      booking.cancelled_at = nowIso();
      booking.cancellation_reason = "Cancelled from dashboard";
      persist();
      return HttpResponse.json(stripTenant(booking));
    }),
  ),

  // ---- Customers ----
  http.get(
    `${API}/customers`,
    authed(({ request, ctx }) => {
      const url = new URL(request.url);
      const q = url.searchParams.get("q")?.trim().toLowerCase();
      const list = ctx.db.customers
        .filter((c) => c.business_id === ctx.user.business_id)
        .filter((c) => !q || c.full_name.toLowerCase().includes(q) || c.phone.includes(q) || c.email?.toLowerCase().includes(q))
        .sort((a, b) => a.full_name.localeCompare(b.full_name))
        .map((c) => customerSummary(ctx.db, c));
      return HttpResponse.json(paginate(list, url));
    }),
  ),

  http.get(
    `${API}/customers/:id`,
    authed<{ id: string }>(({ params, ctx }) => {
      const customer = ctx.db.customers.find((c) => c.id === params.id && c.business_id === ctx.user.business_id);
      if (!customer) return notFound();
      const detail: CustomerDetail = {
        ...customerSummary(ctx.db, customer),
        bookings: ctx.db.bookings
          .filter((b) => b.customer.id === customer.id)
          .sort((a, b) => b.starts_at.localeCompare(a.starts_at))
          .map(stripTenant),
      };
      return HttpResponse.json(detail);
    }),
  ),

  http.post(`${API}/auth/accept-invite`, async ({ request }) => {
    await delay();
    const db = getDb();
    const body = (await request.json()) as { token?: string; full_name?: string; password?: string };
    const invite = body.token ? invites.get(body.token) : undefined;
    if (!invite) return error(400, "invalid_invite", "This invitation is invalid or has expired.");
    if (!body.full_name?.trim() || (body.password?.length ?? 0) < 10) {
      return validationError({ password: ["Use at least 10 characters"] });
    }
    invites.delete(body.token!);
    const user: MockUser = {
      id: mockId(),
      business_id: invite.business_id,
      email: invite.email,
      full_name: body.full_name.trim(),
      role: invite.role,
      location_id: invite.location_id,
      is_active: true,
      last_login_at: null,
      password: body.password!,
    };
    db.users.push(user);
    return authResponse(db, user);
  }),

  // ---- Team (users) ----
  http.get(
    `${API}/users`,
    authed(({ ctx }) => {
      if (ctx.user.role !== "owner" && ctx.user.role !== "manager") return forbidden();
      const items = ctx.db.users
        .filter(
          (u) =>
            u.business_id === ctx.user.business_id &&
            (ctx.user.role === "owner" || u.location_id === ctx.user.location_id),
        )
        .map(({ password: _password, business_id: _business, ...user }) => {
          void _password;
          void _business;
          return user;
        });
      return HttpResponse.json({ items, next_cursor: null });
    }),
  ),

  http.post(
    `${API}/users/invite`,
    authed(async ({ request, ctx }) => {
      if (ctx.user.role !== "owner" && ctx.user.role !== "manager") return forbidden();
      const body = (await request.json()) as { email?: string; role?: string; location_id?: string | null };
      if (!body.email?.includes("@")) return validationError({ email: ["Enter a valid email"] });
      if (ctx.db.users.some((u) => u.email.toLowerCase() === body.email!.toLowerCase())) {
        return error(409, "email_taken", "An account with that email already exists.");
      }
      if (ctx.user.role === "manager" && body.role !== "staff") return forbidden();
      if (body.role !== "owner" && !body.location_id) return validationError({ location_id: ["Choose a location"] });
      const token = crypto.randomUUID();
      invites.set(token, {
        email: body.email,
        role: body.role as MockUser["role"],
        location_id: body.location_id ?? null,
        business_id: ctx.user.business_id,
      });
      return HttpResponse.json(
        {
          id: mockId(),
          email: body.email,
          role: body.role,
          location_id: body.location_id ?? null,
          expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString(),
          token,
        },
        { status: 201 },
      );
    }),
  ),

  http.patch(
    `${API}/users/:id`,
    authed<{ id: string }>(async ({ params, request, ctx }) => {
      if (ctx.user.role !== "owner") return forbidden();
      const target = ctx.db.users.find((u) => u.id === params.id && u.business_id === ctx.user.business_id);
      if (!target) return notFound();
      const body = (await request.json()) as { role?: MockUser["role"]; location_id?: string | null; is_active?: boolean };
      const activeOwners = ctx.db.users.filter(
        (u) => u.business_id === ctx.user.business_id && u.role === "owner" && u.is_active,
      );
      const removesOwner =
        target.role === "owner" &&
        target.is_active &&
        ((body.role && body.role !== "owner") || body.is_active === false);
      if (removesOwner && activeOwners.length <= 1) {
        return error(409, "last_owner", "A business must keep at least one active owner.");
      }
      if (body.role) target.role = body.role;
      if ("location_id" in body) target.location_id = body.location_id ?? null;
      if (body.role === "owner") target.location_id = null;
      if (body.is_active !== undefined) target.is_active = body.is_active;
      persist();
      const { password: _password, business_id: _business, ...user } = target;
      void _password;
      void _business;
      return HttpResponse.json(user);
    }),
  ),

  // ---- Calls ----
  http.get(
    `${API}/calls/stats`,
    authed(({ request, ctx }) => {
      const p = new URL(request.url).searchParams;
      const today = new Date().toISOString().slice(0, 10);
      const fromDate = p.get("from") ?? new Date(Date.now() - 13 * 86_400_000).toISOString().slice(0, 10);
      const toDate = p.get("to") ?? today;
      const calls = ctx.db.calls.filter(
        (c) =>
          c.business_id === ctx.user.business_id &&
          (!p.get("location_id") || c.location_id === p.get("location_id")) &&
          c.started_at.slice(0, 10) >= fromDate &&
          c.started_at.slice(0, 10) <= toDate,
      );
      const byOutcome = Object.fromEntries(
        (["booked", "rescheduled", "cancelled", "info_only", "failed", "abandoned"] as CallOutcome[]).map((o) => [
          o,
          calls.filter((c) => c.outcome === o).length,
        ]),
      ) as Record<CallOutcome, number>;
      const perDay: CallStats["per_day"] = [];
      for (let d = new Date(`${fromDate}T00:00:00Z`); d.toISOString().slice(0, 10) <= toDate; d.setUTCDate(d.getUTCDate() + 1)) {
        const date = d.toISOString().slice(0, 10);
        perDay.push({ date, count: calls.filter((c) => c.started_at.startsWith(date)).length });
      }
      const stats: CallStats = { total: calls.length, by_outcome: byOutcome, per_day: perDay };
      return HttpResponse.json(stats);
    }),
  ),

  http.get(
    `${API}/calls`,
    authed(({ request, ctx }) => {
      const url = new URL(request.url);
      const locationId = url.searchParams.get("location_id");
      const list = ctx.db.calls
        .filter((c) => c.business_id === ctx.user.business_id && (!locationId || c.location_id === locationId))
        .sort((a, b) => b.started_at.localeCompare(a.started_at))
        .map(stripTenant);
      return HttpResponse.json(paginate(list, url));
    }),
  ),

  http.get(
    `${API}/calls/:id`,
    authed<{ id: string }>(({ params, ctx }) => {
      const call = ctx.db.calls.find((c) => c.id === params.id && c.business_id === ctx.user.business_id);
      return call ? HttpResponse.json(stripTenant(call)) : notFound();
    }),
  ),
];
