import { http, refreshSession, setAccessToken } from "./client";
import type {
  AuthResponse,
  AvailabilityRequest,
  Booking,
  BookingFilters,
  Business,
  BusinessPatch,
  CallLog,
  CallStats,
  CreateBookingRequest,
  Invite,
  InviteRequest,
  Customer,
  CustomerDetail,
  Location,
  LocationInput,
  LocationPatch,
  LoginRequest,
  Me,
  Paginated,
  Service,
  ServiceInput,
  SignupRequest,
  Slot,
  Staff,
  StaffInput,
  TimeOff,
  TimeOffInput,
  UpdateBookingRequest,
  User,
  UserPatch,
  WorkingHours,
} from "./types";

export { ApiError, getAccessToken, onUnauthenticated, setAccessToken } from "./client";
export type * from "./types";

async function authenticate(promise: Promise<AuthResponse>): Promise<AuthResponse> {
  const data = await promise;
  setAccessToken(data.access_token);
  return data;
}

/** Typed client for docs/api-contract.md. Paths are FastAPI paths; the client adds `/api`. */
export const api = {
  auth: {
    login: (body: LoginRequest) =>
      authenticate(http.post<AuthResponse>("/auth/login", body, { skipRefresh: true })),
    signup: (body: SignupRequest) =>
      authenticate(http.post<AuthResponse>("/auth/signup", body, { skipRefresh: true })),
    acceptInvite: (body: { token: string; full_name: string; password: string }) =>
      authenticate(http.post<AuthResponse>("/auth/accept-invite", body, { skipRefresh: true })),
    refresh: refreshSession,
    logout: async () => {
      try {
        await http.post<void>("/auth/logout", undefined, { skipRefresh: true });
      } finally {
        setAccessToken(null);
      }
    },
    me: () => http.get<Me>("/auth/me"),
  },

  business: {
    get: () => http.get<Business>("/business"),
    update: (body: BusinessPatch) => http.patch<Business>("/business", body),
  },

  locations: {
    list: async () => (await http.get<Paginated<Location>>("/locations")).items,
    get: (id: string) => http.get<Location>(`/locations/${id}`),
    create: (body: LocationInput) => http.post<Location>("/locations", body),
    update: (id: string, body: LocationPatch) => http.patch<Location>(`/locations/${id}`, body),
    deactivate: (id: string) => http.delete<void>(`/locations/${id}`),
  },

  users: {
    list: async () => (await http.get<Paginated<User>>("/users", { query: { limit: 200 } })).items,
    invite: (body: InviteRequest) => http.post<Invite>("/users/invite", body),
    update: (id: string, body: UserPatch) => http.patch<User>(`/users/${id}`, body),
  },

  services: {
    list: async () => (await http.get<Paginated<Service>>("/services")).items,
    create: (body: ServiceInput) => http.post<Service>("/services", body),
    update: (id: string, body: Partial<ServiceInput>) => http.patch<Service>(`/services/${id}`, body),
    remove: (id: string) => http.delete<void>(`/services/${id}`),
  },

  staff: {
    list: async (query?: { location_id?: string }) =>
      (await http.get<Paginated<Staff>>("/staff", { query })).items,
    create: (body: StaffInput) => http.post<Staff>("/staff", body),
    update: (id: string, body: Partial<StaffInput>) => http.patch<Staff>(`/staff/${id}`, body),
    remove: (id: string) => http.delete<void>(`/staff/${id}`),
    hours: (id: string) => http.get<WorkingHours>(`/staff/${id}/hours`),
    setHours: (id: string, body: WorkingHours) => http.put<WorkingHours>(`/staff/${id}/hours`, body),
    timeOff: (id: string) => http.get<TimeOff[]>(`/staff/${id}/time-off`),
    addTimeOff: (id: string, body: TimeOffInput) =>
      http.post<TimeOff>(`/staff/${id}/time-off`, body),
  },

  availability: {
    search: (body: AvailabilityRequest) => http.post<{ slots: Slot[] }>("/availability", body),
  },

  bookings: {
    list: (filters: BookingFilters & { limit?: number; cursor?: string } = {}) =>
      http.get<Paginated<Booking>>("/bookings", { query: filters }),
    get: (id: string) => http.get<Booking>(`/bookings/${id}`),
    create: (body: CreateBookingRequest, idempotencyKey: string = crypto.randomUUID()) =>
      http.post<Booking>("/bookings", body, { headers: { "Idempotency-Key": idempotencyKey } }),
    update: (id: string, body: UpdateBookingRequest) => http.patch<Booking>(`/bookings/${id}`, body),
    cancel: (id: string, options: { force?: boolean } = {}) =>
      http.delete<Booking>(`/bookings/${id}`, { query: { force: options.force || undefined } }),
  },

  customers: {
    list: (query: { q?: string; limit?: number; cursor?: string } = {}) =>
      http.get<Paginated<Customer>>("/customers", { query }),
    get: (id: string) => http.get<CustomerDetail>(`/customers/${id}`),
  },

  calls: {
    list: (query: { location_id?: string; limit?: number; cursor?: string } = {}) =>
      http.get<Paginated<CallLog>>("/calls", { query }),
    get: (id: string) => http.get<CallLog>(`/calls/${id}`),
    stats: (query: { from?: string; to?: string; location_id?: string } = {}) =>
      http.get<CallStats>("/calls/stats", { query }),
  },
};
