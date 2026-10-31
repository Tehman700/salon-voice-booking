/**
 * Types mirroring docs/api-contract.md. JSON field names stay snake_case so these map 1:1 onto
 * FastAPI responses; do not add shapes here that are not in the contract.
 */

export type Role = "platform_admin" | "owner" | "manager" | "staff";
export type LocationMode = "single" | "multiple";

export type Paginated<T> = { items: T[]; next_cursor: string | null };

export type ApiErrorBody = {
  error: { code: string; message: string; details?: Record<string, unknown> };
};

// ---- Auth (M1) ----

export type Me = {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  business: { id: string; name: string; location_mode: LocationMode } | null;
  location_ids: string[];
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: Me;
};

export type LoginRequest = { email: string; password: string };

export type SignupRequest = {
  business_name: string;
  owner_full_name: string;
  email: string;
  password: string;
  location_mode: LocationMode;
  locations: LocationInput[];
};

// ---- Business, locations, users (M1) ----

export type LocationInput = {
  name: string;
  timezone: string;
  phone?: string;
  address_line1?: string;
  city?: string;
  country?: string;
};

export type Location = LocationInput & {
  id: string;
  slug: string;
  is_active: boolean;
  cancellation_window_minutes: number | null;
  effective_cancellation_window_minutes: number;
};

export type LocationPatch = Partial<LocationInput> & {
  is_active?: boolean;
  cancellation_window_minutes?: number | null;
};

export type Business = {
  id: string;
  name: string;
  slug: string;
  location_mode: LocationMode;
  default_timezone: string;
  cancellation_window_minutes: number;
};

export type BusinessPatch = Partial<
  Pick<Business, "name" | "default_timezone" | "cancellation_window_minutes">
>;

export type User = {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  location_id: string | null;
  is_active: boolean;
  last_login_at: string | null;
};

export type UserPatch = { role?: Role; location_id?: string | null; is_active?: boolean };

export type InviteRequest = { email: string; role: Role; location_id?: string | null };

export type Invite = {
  id: string;
  email: string;
  role: Role;
  location_id: string | null;
  expires_at: string;
  /** Only returned while emails aren't wired up (local/test). */
  token?: string;
};

// ---- Catalog and schedules (M2, draft) ----

export type LocationOverride = {
  location_id: string;
  price_minor: number | null;
  duration_minutes: number | null;
  is_offered: boolean;
};

export type Service = {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  duration_minutes: number;
  buffer_minutes: number;
  price_minor: number;
  currency: string;
  is_active: boolean;
  location_overrides: LocationOverride[];
};

export type ServiceInput = Omit<Service, "id">;

export type Staff = {
  id: string;
  location_id: string;
  user_id: string | null;
  full_name: string;
  title: string | null;
  color: string;
  service_ids: string[];
  is_active: boolean;
};

export type StaffInput = Omit<Staff, "id" | "user_id">;

export type Weekday = 0 | 1 | 2 | 3 | 4 | 5 | 6;
/** 0 = Monday, local time. */
export type WorkingHours = { weekday: Weekday; start: string; end: string }[];

export type TimeOff = {
  id: string;
  staff_id: string;
  starts_at: string;
  ends_at: string;
  reason: string | null;
};

export type TimeOffInput = Omit<TimeOff, "id" | "staff_id">;

// ---- Availability and bookings (M3–M4, draft) ----

export type AvailabilityRequest = {
  location_id: string;
  service_id: string;
  staff_id?: string;
  date_from: string;
  date_to: string;
};

export type Slot = { starts_at: string; ends_at: string; staff_id: string; staff_name: string };

export type BookingStatus = "booked" | "completed" | "cancelled" | "no_show";
export type BookingSource = "voice" | "dashboard";

export type BookingCustomer = {
  id: string;
  full_name: string;
  phone: string;
  email: string | null;
};

export type Booking = {
  id: string;
  reference: string;
  location_id: string;
  service_id: string;
  staff_id: string;
  customer: BookingCustomer;
  starts_at: string;
  ends_at: string;
  status: BookingStatus;
  source: BookingSource;
  call_id: string | null;
  price_minor: number;
  currency: string;
  notes: string | null;
  created_at: string;
  cancelled_at: string | null;
  cancellation_reason: string | null;
};

export type BookingFilters = {
  location_id?: string;
  staff_id?: string;
  status?: BookingStatus;
  source?: BookingSource;
  from?: string;
  to?: string;
  q?: string;
};

export type CreateBookingRequest = {
  location_id: string;
  service_id: string;
  staff_id: string;
  starts_at: string;
  customer: { full_name: string; phone: string; email?: string | null };
  notes?: string | null;
};

export type UpdateBookingRequest = {
  starts_at?: string;
  staff_id?: string;
  notes?: string | null;
};

export type Customer = {
  id: string;
  full_name: string;
  phone: string;
  email: string | null;
  notes: string | null;
  created_at: string;
  booking_count: number;
  last_visit_at: string | null;
};

export type CustomerDetail = Customer & { bookings: Booking[] };

// ---- Calls (M6, draft) ----

export type CallOutcome =
  | "booked"
  | "rescheduled"
  | "cancelled"
  | "info_only"
  | "failed"
  | "abandoned";

export type CallLog = {
  id: string;
  retell_call_id: string;
  location_id: string;
  from_number: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  outcome: CallOutcome;
  summary: string | null;
  transcript: { role: "agent" | "user"; text: string }[] | null;
  booking_id: string | null;
};

export type CallStats = {
  total: number;
  by_outcome: Record<CallOutcome, number>;
  per_day: { date: string; count: number }[];
};
