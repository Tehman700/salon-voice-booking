"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorNotice, PageHeader, TableSkeleton } from "@/components/page-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, ApiError, type Business, type Location } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatWindow } from "@/lib/format";
import { errorMessage, toastError, useBusinessQuery, useLocationsQuery } from "@/lib/hooks";

const WINDOWS = [0, 30, 60, 120, 240, 720, 1440, 2880];
const INHERIT = "inherit";

function WindowSelect({ value, onChange, allowInherit }: { value: string; onChange: (v: string) => void; allowInherit?: boolean }) {
  const numeric = value !== INHERIT ? Number(value) : null;
  const options = numeric !== null && !WINDOWS.includes(numeric) ? [...WINDOWS, numeric].sort((a, b) => a - b) : WINDOWS;
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-full" aria-label="Cancellation notice">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {allowInherit && <SelectItem value={INHERIT}>Use the business default</SelectItem>}
        {options.map((m) => (
          <SelectItem key={m} value={String(m)}>
            {formatWindow(m)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export default function SettingsPage() {
  const business = useBusinessQuery();
  const locations = useLocationsQuery();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Location | "new" | null>(null);

  const setActive = useMutation({
    mutationFn: async (l: Location) => {
      if (l.is_active) await api.locations.deactivate(l.id);
      else await api.locations.update(l.id, { is_active: true });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["locations"] }),
    onError: (e) =>
      e instanceof ApiError && e.code === "last_active_location" ? toast.error("You need at least one active location.") : toastError(e),
  });

  return (
    <>
      <PageHeader title="Settings" description="Your business, its locations and the cancellation policy." />
      {business.isError ? (
        <ErrorNotice message="Couldn't load settings." onRetry={() => business.refetch()} />
      ) : !business.data ? (
        <TableSkeleton rows={3} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <BusinessCard key={business.data.id} business={business.data} />

          <Card>
            <CardHeader className="flex-row items-start justify-between gap-2">
              <div>
                <CardTitle>Locations</CardTitle>
                <CardDescription>Each salon has its own staff, hours, timezone and phone number.</CardDescription>
              </div>
              <Button size="sm" onClick={() => setEditing("new")}>
                Add location
              </Button>
            </CardHeader>
            <CardContent>
              <ul className="divide-y">
                {(locations.data ?? []).map((l) => (
                  <li key={l.id} className="flex items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="flex items-center gap-2 font-medium">
                        <span className="truncate">{l.name}</span>
                        {!l.is_active && <Badge variant="secondary">Inactive</Badge>}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {[l.city, l.timezone, l.phone].filter(Boolean).join(" · ")} · notice: {formatWindow(l.effective_cancellation_window_minutes)}
                        {l.cancellation_window_minutes === null ? "" : " (custom)"}
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button variant="ghost" size="sm" onClick={() => setEditing(l)}>
                        Edit
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setActive.mutate(l)}>
                        {l.is_active ? "Deactivate" : "Reactivate"}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      )}
      <LocationDialog editing={editing} onClose={() => setEditing(null)} />
    </>
  );
}

function BusinessCard({ business }: { business: Business }) {
  const { reload } = useAuth();
  const queryClient = useQueryClient();
  const [name, setName] = useState(business.name);
  const [windowMinutes, setWindowMinutes] = useState(String(business.cancellation_window_minutes));

  const save = useMutation({
    mutationFn: () => api.business.update({ name: name.trim(), cancellation_window_minutes: Number(windowMinutes) }),
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["business"] }), queryClient.invalidateQueries({ queryKey: ["locations"] }), reload()]);
      toast.success("Settings saved");
    },
    onError: toastError,
  });

  const dirty = name.trim() !== business.name || Number(windowMinutes) !== business.cancellation_window_minutes;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Business</CardTitle>
        <CardDescription>Shown on the dashboard and used by the voice agent.</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return toast.error("Enter a business name.");
            save.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="biz-name">Business name</Label>
            <Input id="biz-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Cancellation notice</Label>
            <WindowSelect value={windowMinutes} onChange={setWindowMinutes} />
            <p className="text-xs text-muted-foreground">
              Customers can not cancel by phone closer to the appointment than this. Managers can still override it.
            </p>
          </div>
          <Button type="submit" disabled={!dirty || save.isPending}>
            {save.isPending ? "Saving…" : "Save changes"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function LocationDialog({ editing, onClose }: { editing: Location | "new" | null; onClose: () => void }) {
  return (
    <Dialog open={!!editing} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        {editing && <LocationForm key={editing === "new" ? "new" : editing.id} editing={editing} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function LocationForm({ editing, onClose }: { editing: Location | "new"; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { reload } = useAuth();
  const existing = editing === "new" ? null : editing;
  const [name, setName] = useState(existing?.name ?? "");
  const [timezone, setTimezone] = useState(existing?.timezone ?? "Asia/Karachi");
  const [phone, setPhone] = useState(existing?.phone ?? "");
  const [city, setCity] = useState(existing?.city ?? "");
  const [windowValue, setWindowValue] = useState(
    existing?.cancellation_window_minutes == null ? INHERIT : String(existing.cancellation_window_minutes),
  );
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      const base = { name: name.trim(), timezone, phone: phone.trim() || undefined, city: city.trim() || undefined };
      if (!existing) return api.locations.create(base);
      return api.locations.update(existing.id, {
        ...base,
        cancellation_window_minutes: windowValue === INHERIT ? null : Number(windowValue),
      });
    },
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["locations"] }), reload()]);
      toast.success(existing ? "Location updated" : "Location added");
      onClose();
    },
    onError: (e) => setError(errorMessage(e)),
  });

  return (
    <>
      <DialogHeader>
        <DialogTitle>{existing ? "Edit location" : "Add location"}</DialogTitle>
        <DialogDescription>{existing ? "Changes apply to new bookings straight away." : "Adding a second salon turns on the location switcher."}</DialogDescription>
      </DialogHeader>
      <form
        className="space-y-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (!name.trim()) return setError("Enter a name.");
          if (phone.trim() && !/^\+[1-9]\d{6,14}$/.test(phone.trim())) return setError("Use international format, e.g. +923001234567.");
          setError(null);
          save.mutate();
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="loc-name">Name</Label>
          <Input id="loc-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="loc-city">City</Label>
            <Input id="loc-city" value={city} onChange={(e) => setCity(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-phone">Phone</Label>
            <Input id="loc-phone" type="tel" placeholder="+923001234567" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="loc-tz">Timezone</Label>
          <Input id="loc-tz" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
          <p className="text-xs text-muted-foreground">IANA name, e.g. Asia/Karachi or Europe/London.</p>
        </div>
        {existing && (
          <div className="space-y-1.5">
            <Label>Cancellation notice</Label>
            <WindowSelect value={windowValue} onChange={setWindowValue} allowInherit />
          </div>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
