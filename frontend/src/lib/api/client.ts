import type { ApiErrorBody, AuthResponse } from "./types";

/** Browser requests go to /api/* on the Next.js origin, which proxies them to FastAPI. */
export const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Field → messages map for `validation_error` responses. */
  get fieldErrors(): Record<string, string[]> {
    if (this.code !== "validation_error") return {};
    const out: Record<string, string[]> = {};
    for (const [field, value] of Object.entries(this.details)) {
      if (Array.isArray(value)) out[field] = value.map(String);
      else if (typeof value === "string") out[field] = [value];
    }
    return out;
  }
}

// The access token lives in memory only; the refresh token is an httpOnly cookie.
let accessToken: string | null = null;
let unauthenticatedHandler: (() => void) | null = null;
let refreshInFlight: Promise<AuthResponse | null> | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

/** Called when a request is still 401 after one refresh attempt (session is gone). */
export function onUnauthenticated(handler: (() => void) | null) {
  unauthenticatedHandler = handler;
}

let mocksReady: Promise<void> | null = null;

/** In mock mode, wait for the MSW worker before the first request leaves the page. */
function waitForMocks(): Promise<void> {
  if (process.env.NEXT_PUBLIC_API_MOCKS !== "true" || typeof window === "undefined") {
    return Promise.resolve();
  }
  mocksReady ??= import("@/mocks/browser").then(({ startMockWorker }) => startMockWorker());
  return mocksReady;
}

type Query = Record<string, string | number | boolean | null | undefined>;

export type RequestOptions = {
  query?: Query;
  body?: unknown;
  headers?: Record<string, string>;
  /** Skip the refresh-and-retry on 401 (used by the auth endpoints themselves). */
  skipRefresh?: boolean;
  signal?: AbortSignal;
};

function buildUrl(path: string, query?: Query): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
  const url = new URL(`${API_BASE}${path}`, origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  return url.toString();
}

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // Non-JSON error (proxy failure, HTML error page): fall through to a generic error.
  }
  const error = (body as ApiErrorBody | null)?.error;
  if (error && typeof error.code === "string") {
    return new ApiError(res.status, error.code, error.message ?? res.statusText, error.details ?? {});
  }
  return new ApiError(res.status, "unknown_error", res.statusText || "Request failed");
}

async function send(method: string, path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  return fetch(buildUrl(path, options.query), {
    method,
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    credentials: "same-origin",
    signal: options.signal,
  });
}

/**
 * Exchange the refresh cookie for a new access token. Concurrent callers share one request, so a
 * burst of 401s triggers a single refresh (the backend rotates the cookie on every call).
 */
export function refreshSession(): Promise<AuthResponse | null> {
  refreshInFlight ??= (async () => {
    try {
      await waitForMocks();
      const res = await send("POST", "/auth/refresh", { skipRefresh: true });
      if (!res.ok) {
        setAccessToken(null);
        return null;
      }
      const data = (await res.json()) as AuthResponse;
      setAccessToken(data.access_token);
      return data;
    } catch {
      setAccessToken(null);
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  await waitForMocks();
  let res = await send(method, path, options);

  if (res.status === 401 && !options.skipRefresh) {
    const refreshed = await refreshSession();
    if (refreshed) {
      res = await send(method, path, options);
    }
    if (res.status === 401) {
      unauthenticatedHandler?.();
    }
  }

  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const http = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PUT", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, { ...options, body }),
  delete: <T>(path: string, options?: RequestOptions) => request<T>("DELETE", path, options),
};
