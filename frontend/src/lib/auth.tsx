"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, onUnauthenticated, type LoginRequest, type Me, type Role, type SignupRequest } from "@/lib/api";

type AuthState =
  | { status: "loading"; user: null }
  | { status: "authenticated"; user: Me }
  | { status: "unauthenticated"; user: null };

type AuthContextValue = AuthState & {
  login: (body: LoginRequest) => Promise<Me>;
  signup: (body: SignupRequest) => Promise<Me>;
  logout: () => Promise<void>;
  /** Re-read the current user, e.g. after the business name or location mode changes. */
  reload: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Session bootstrap: the access token is kept in memory only, so on every page load we exchange
 * the refresh cookie (POST /auth/refresh) for a new one before showing the app shell.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<AuthState>({ status: "loading", user: null });

  useEffect(() => {
    let cancelled = false;
    api.auth.refresh().then((session) => {
      if (cancelled) return;
      setState(session ? { status: "authenticated", user: session.user } : { status: "unauthenticated", user: null });
    });
    onUnauthenticated(() => {
      queryClient.clear();
      setState({ status: "unauthenticated", user: null });
    });
    return () => {
      cancelled = true;
      onUnauthenticated(null);
    };
  }, [queryClient]);

  const login = useCallback(async (body: LoginRequest) => {
    const { user } = await api.auth.login(body);
    setState({ status: "authenticated", user });
    return user;
  }, []);

  const signup = useCallback(async (body: SignupRequest) => {
    const { user } = await api.auth.signup(body);
    setState({ status: "authenticated", user });
    return user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } finally {
      queryClient.clear();
      setState({ status: "unauthenticated", user: null });
    }
  }, [queryClient]);

  const reload = useCallback(async () => {
    const user = await api.auth.me();
    setState({ status: "authenticated", user });
  }, []);

  const value = useMemo(() => ({ ...state, login, signup, logout, reload }), [state, login, signup, logout, reload]);
  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}

/** The signed-in user; only call below the app shell's auth gate. */
export function useMe(): Me {
  const { user } = useAuth();
  if (!user) throw new Error("useMe called outside an authenticated area");
  return user;
}

export function isStaffRole(role: Role) {
  return role === "staff";
}

export function canManage(role: Role) {
  return role === "owner" || role === "manager" || role === "platform_admin";
}
