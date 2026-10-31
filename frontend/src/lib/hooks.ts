"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, type BookingFilters } from "@/lib/api";
import { toast } from "sonner";

export const useLocationsQuery = () => useQuery({ queryKey: ["locations"], queryFn: api.locations.list });
export const useBusinessQuery = () => useQuery({ queryKey: ["business"], queryFn: api.business.get });
export const useServicesQuery = () => useQuery({ queryKey: ["services"], queryFn: api.services.list });
export const useUsersQuery = (enabled = true) =>
  useQuery({ queryKey: ["users"], queryFn: api.users.list, enabled });

export const useStaffQuery = (locationId?: string) =>
  useQuery({
    queryKey: ["staff", locationId ?? "all"],
    queryFn: () => api.staff.list(locationId ? { location_id: locationId } : undefined),
  });

export const useBookingsQuery = (filters: BookingFilters, enabled = true) =>
  useQuery({
    queryKey: ["bookings", filters],
    queryFn: async () => (await api.bookings.list({ ...filters, limit: 500 })).items,
    placeholderData: keepPreviousData,
    enabled,
  });

export const useCustomersQuery = (q: string) =>
  useQuery({
    queryKey: ["customers", q],
    queryFn: async () => (await api.customers.list({ q: q || undefined, limit: 200 })).items,
    placeholderData: keepPreviousData,
  });

export const useCustomerQuery = (id: string | null) =>
  useQuery({ queryKey: ["customer", id], queryFn: () => api.customers.get(id!), enabled: !!id });

export const useCallsQuery = (locationId?: string) =>
  useQuery({
    queryKey: ["calls", locationId ?? "all"],
    queryFn: async () => (await api.calls.list({ location_id: locationId, limit: 200 })).items,
  });

export const useCallStatsQuery = (locationId?: string) =>
  useQuery({
    queryKey: ["call-stats", locationId ?? "all"],
    queryFn: () => api.calls.stats({ location_id: locationId }),
  });

/** Refresh everything that a booking change can affect. */
export function useInvalidateBookings() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all(
      ["bookings", "customers", "customer", "calls", "call-stats"].map((key) =>
        queryClient.invalidateQueries({ queryKey: [key] }),
      ),
    );
}

/** A user-facing message for any thrown error. */
export function errorMessage(error: unknown) {
  if (error instanceof ApiError) {
    const fields = Object.values(error.fieldErrors).flat();
    return fields.length ? fields.join(" ") : error.message;
  }
  return "Something went wrong. Please try again.";
}

export function toastError(error: unknown) {
  toast.error(errorMessage(error));
}
