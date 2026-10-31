"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

import type { Location } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { useLocationsQuery } from "@/lib/hooks";

const STORAGE_KEY = "salon-location";
export const ALL = "all";

type LocationScope = {
  /** Locations this user may see, active ones first. */
  locations: Location[];
  /** The selected location id, or "all". */
  selected: string;
  /** Undefined when viewing every location; pass this straight to API filters. */
  locationId: string | undefined;
  select: (id: string) => void;
  /** The selected location, or the first one when viewing all. */
  current: Location | null;
  /** Timezone used to display times: the selected location's, else the first location's. */
  timeZone: string;
  getLocation: (id: string) => Location | undefined;
  isMulti: boolean;
};

const LocationScopeContext = createContext<LocationScope | null>(null);

export function LocationScopeProvider({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const { data } = useLocationsQuery();
  // The last explicit choice, restored from this browser. This provider only renders after sign-in,
  // on the client, so reading storage in the initializer is safe.
  const [choice, setChoice] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? ALL;
    } catch {
      return ALL;
    }
  });

  const locations = useMemo(
    () =>
      [...(data ?? [])]
        .filter((l) => me.role === "platform_admin" || me.location_ids.includes(l.id))
        .sort((a, b) => Number(b.is_active) - Number(a.is_active) || a.name.localeCompare(b.name)),
    [data, me.location_ids, me.role],
  );

  // A saved choice only counts while it is still valid; with one salon there is nothing to choose.
  const selected =
    locations.length === 1
      ? locations[0]!.id
      : choice === ALL || locations.some((l) => l.id === choice)
        ? choice
        : ALL;

  const select = useCallback((id: string) => {
    setChoice(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // ignore
    }
  }, []);

  const value = useMemo<LocationScope>(() => {
    const current = locations.find((l) => l.id === selected) ?? locations[0] ?? null;
    return {
      locations,
      selected,
      locationId: selected === ALL ? undefined : selected,
      select,
      current,
      timeZone: current?.timezone ?? "Asia/Karachi",
      getLocation: (id) => locations.find((l) => l.id === id),
      isMulti: locations.length > 1,
    };
  }, [locations, selected, select]);

  return <LocationScopeContext value={value}>{children}</LocationScopeContext>;
}

export function useLocationScope() {
  const context = useContext(LocationScopeContext);
  if (!context) throw new Error("useLocationScope must be used inside the app shell");
  return context;
}
