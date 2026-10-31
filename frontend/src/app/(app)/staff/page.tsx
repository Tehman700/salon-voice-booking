"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Dot, EmptyState, ErrorNotice, PageHeader, TableSkeleton } from "@/components/page-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api, type Staff, type Weekday, type WorkingHours } from "@/lib/api";
import { addDays, formatDateTime, todayKey, WEEKDAYS, zonedToIso } from "@/lib/format";
import { toastError, useServicesQuery, useStaffQuery } from "@/lib/hooks";
import { useLocationScope } from "@/lib/location-scope";

const COLORS = ["#0070f3", "#7928ca", "#ff0080", "#f5a623", "#29bc9b", "#ee0000", "#171717"];

export default function StaffPage() {
  const scope = useLocationScope();
  const staff = useStaffQuery(scope.locationId);
  const services = useServicesQuery();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Staff | "new" | null>(null);
  const [hoursFor, setHoursFor] = useState<Staff | null>(null);
  const [timeOffFor, setTimeOffFor] = useState<Staff | null>(null);

  const toggle = useMutation({
    mutationFn: (s: Staff) => api.staff.update(s.id, { is_active: !s.is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["staff"] }),
    onError: toastError,
  });

  const list = staff.data ?? [];
  const groups = scope.locations
    .filter((l) => list.some((s) => s.location_id === l.id))
    .map((l) => ({ location: l, members: list.filter((s) => s.location_id === l.id) }));

  return (
    <>
      <PageHeader
        title="Staff"
        description="Who works where, what they do, and when they are available."
        actions={<Button onClick={() => setEditing("new")}>Add staff member</Button>}
      />
      {staff.isError ? (
        <ErrorNotice message="Couldn't load staff." onRetry={() => staff.refetch()} />
      ) : staff.isLoading ? (
        <TableSkeleton rows={4} />
      ) : list.length === 0 ? (
        <EmptyState title="No staff yet" description="Add the people who take appointments." action={<Button onClick={() => setEditing("new")}>Add staff member</Button>} />
      ) : (
        <div className="space-y-8">
          {groups.map(({ location, members }) => (
            <section key={location.id} aria-label={location.name}>
              {scope.isMulti && <h2 className="mb-3 font-mono text-xs uppercase text-muted-foreground">{location.name}</h2>}
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {members.map((s) => (
                  <Card key={s.id} className={s.is_active ? "" : "opacity-60"}>
                    <CardHeader className="flex-row items-start justify-between gap-2">
                      <div className="min-w-0">
                        <CardTitle className="flex items-center gap-2">
                          <Dot color={s.color} className="size-3" /> <span className="truncate">{s.full_name}</span>
                        </CardTitle>
                        <p className="text-sm text-muted-foreground">{s.title ?? "—"}</p>
                      </div>
                      <Switch checked={s.is_active} onCheckedChange={() => toggle.mutate(s)} aria-label={`${s.full_name} active`} />
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="flex flex-wrap gap-1.5">
                        {s.service_ids.length === 0 && <span className="text-xs text-muted-foreground">No services assigned</span>}
                        {s.service_ids.map((id) => (
                          <Badge key={id} variant="secondary">
                            {services.data?.find((x) => x.id === id)?.name ?? "…"}
                          </Badge>
                        ))}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button size="sm" variant="outline" onClick={() => setHoursFor(s)}>
                          Working hours
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setTimeOffFor(s)}>
                          Time off
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing(s)}>
                          Edit
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <StaffDialog editing={editing} onClose={() => setEditing(null)} />
      <HoursDialog member={hoursFor} onClose={() => setHoursFor(null)} />
      <TimeOffDialog member={timeOffFor} onClose={() => setTimeOffFor(null)} />
    </>
  );
}

function StaffDialog({ editing, onClose }: { editing: Staff | "new" | null; onClose: () => void }) {
  return (
    <Dialog open={!!editing} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-md">
        {editing && <StaffForm key={editing === "new" ? "new" : editing.id} editing={editing} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function StaffForm({ editing, onClose }: { editing: Staff | "new"; onClose: () => void }) {
  const scope = useLocationScope();
  const services = useServicesQuery();
  const queryClient = useQueryClient();
  const existing = editing === "new" ? null : editing;
  const active = scope.locations.filter((l) => l.is_active);
  const [name, setName] = useState(existing?.full_name ?? "");
  const [title, setTitle] = useState(existing?.title ?? "");
  const [pickedLocation, setLocationId] = useState<string | null>(null);
  const locationId = pickedLocation ?? existing?.location_id ?? scope.locationId ?? active[0]?.id ?? "";
  const [color, setColor] = useState(existing?.color ?? COLORS[0]!);
  const [serviceIds, setServiceIds] = useState<string[]>(existing?.service_ids ?? []);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const body = { location_id: locationId, full_name: name.trim(), title: title.trim() || null, color, service_ids: serviceIds, is_active: existing?.is_active ?? true };
      return existing ? api.staff.update(existing.id, body) : api.staff.create(body);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["staff"] });
      toast.success(existing ? "Staff member updated" : "Staff member added");
      onClose();
    },
    onError: toastError,
  });

  return (
    <>
        <DialogHeader>
          <DialogTitle>{existing ? "Edit staff member" : "Add staff member"}</DialogTitle>
          <DialogDescription>Only the services ticked below will be offered with this person.</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return setError("Enter a name");
            if (!locationId) return setError("Choose a location");
            setError(null);
            save.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="staff-name">Name</Label>
            <Input id="staff-name" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!error} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="staff-title">Title</Label>
            <Input id="staff-title" placeholder="Senior stylist" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          {active.length > 1 && (
            <div className="space-y-1.5">
              <Label>Location</Label>
              <Select value={locationId} onValueChange={setLocationId}>
                <SelectTrigger className="w-full" aria-label="Location">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {active.map((l) => (
                    <SelectItem key={l.id} value={l.id}>
                      {l.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Calendar color</legend>
            <div className="flex gap-2" role="radiogroup" aria-label="Calendar color">
              {COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  role="radio"
                  aria-checked={color === c}
                  aria-label={c}
                  onClick={() => setColor(c)}
                  className={`size-7 rounded-full border-2 ${color === c ? "border-foreground" : "border-transparent"}`}
                  style={{ background: c }}
                />
              ))}
            </div>
          </fieldset>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Services</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {(services.data ?? []).filter((s) => s.is_active).map((s) => (
                <label key={s.id} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={serviceIds.includes(s.id)}
                    onCheckedChange={(v) => setServiceIds((c) => (v ? [...c, s.id] : c.filter((id) => id !== s.id)))}
                  />
                  {s.name}
                </label>
              ))}
            </div>
          </fieldset>
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

type DayRow = { enabled: boolean; start: string; end: string; locked?: string };

function HoursDialog({ member, onClose }: { member: Staff | null; onClose: () => void }) {
  const hours = useQuery({ queryKey: ["hours", member?.id], queryFn: () => api.staff.hours(member!.id), enabled: !!member });
  return (
    <Dialog open={!!member} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Working hours{member ? ` · ${member.full_name}` : ""}</DialogTitle>
          <DialogDescription>Customers can only book inside these hours.</DialogDescription>
        </DialogHeader>
        {member && hours.data ? (
          <HoursEditor key={member.id} member={member} original={hours.data} onClose={onClose} />
        ) : (
          <TableSkeleton rows={4} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function HoursEditor({ member, original, onClose }: { member: Staff; original: WorkingHours; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<DayRow[]>(() =>
    WEEKDAYS.map((_, weekday) => {
      const blocks = original.filter((h) => h.weekday === weekday);
      if (blocks.length > 1) {
        return { enabled: true, start: "", end: "", locked: blocks.map((b) => `${b.start}–${b.end}`).join(", ") };
      }
      return { enabled: blocks.length === 1, start: blocks[0]?.start ?? "10:00", end: blocks[0]?.end ?? "19:00" };
    }),
  );
  const [error, setError] = useState<string | null>(null);
  const patch = (i: number, change: Partial<DayRow>) => setRows((c) => c.map((r, idx) => (idx === i ? { ...r, ...change } : r)));

  const save = useMutation({
    mutationFn: () => {
      const body: WorkingHours = rows.flatMap((row, i) =>
        row.locked
          ? original.filter((h) => h.weekday === i)
          : row.enabled
            ? [{ weekday: i as Weekday, start: row.start, end: row.end }]
            : [],
      );
      return api.staff.setHours(member.id, body);
    },
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["hours"] }), queryClient.invalidateQueries({ queryKey: ["slots"] })]);
      toast.success("Working hours saved");
      onClose();
    },
    onError: toastError,
  });

  function submit() {
    const bad = rows.findIndex((r) => !r.locked && r.enabled && (!r.start || !r.end || r.start >= r.end));
    if (bad >= 0) return setError(`${WEEKDAYS[bad]}: the end time must be after the start time.`);
    setError(null);
    save.mutate();
  }

  return (
    <>
      <ul className="space-y-2">
        {rows.map((row, i) => (
          <li key={WEEKDAYS[i]} className="grid grid-cols-[110px_auto_1fr] items-center gap-3">
            <Label htmlFor={`day-${i}`}>{WEEKDAYS[i]}</Label>
            <Switch id={`day-${i}`} checked={row.enabled} disabled={!!row.locked} onCheckedChange={(v) => patch(i, { enabled: v })} />
            {row.locked ? (
              <span className="text-xs text-muted-foreground">Split shift {row.locked}</span>
            ) : row.enabled ? (
              <div className="flex items-center gap-2">
                <Input type="time" aria-label={`${WEEKDAYS[i]} start`} className="w-[110px]" value={row.start} onChange={(e) => patch(i, { start: e.target.value })} />
                <span className="text-muted-foreground">–</span>
                <Input type="time" aria-label={`${WEEKDAYS[i]} end`} className="w-[110px]" value={row.end} onChange={(e) => patch(i, { end: e.target.value })} />
              </div>
            ) : (
              <span className="text-sm text-muted-foreground">Day off</span>
            )}
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save hours"}
        </Button>
      </DialogFooter>
    </>
  );
}

function TimeOffDialog({ member, onClose }: { member: Staff | null; onClose: () => void }) {
  return (
    <Dialog open={!!member} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        {member && <TimeOffBody key={member.id} member={member} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function TimeOffBody({ member, onClose }: { member: Staff; onClose: () => void }) {
  const scope = useLocationScope();
  const queryClient = useQueryClient();
  const timeZone = scope.getLocation(member.location_id)?.timezone ?? scope.timeZone;
  const entries = useQuery({ queryKey: ["time-off", member.id], queryFn: () => api.staff.timeOff(member.id) });
  const today = todayKey(timeZone);
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(today);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const add = useMutation({
    mutationFn: () =>
      api.staff.addTimeOff(member.id, {
        starts_at: zonedToIso(from, "00:00", timeZone),
        ends_at: zonedToIso(addDays(to, 1), "00:00", timeZone),
        reason: reason.trim() || null,
      }),
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["time-off"] }), queryClient.invalidateQueries({ queryKey: ["slots"] })]);
      toast.success("Time off added");
      setReason("");
    },
    onError: toastError,
  });

  return (
    <>
      <DialogHeader>
        <DialogTitle>Time off · {member.full_name}</DialogTitle>
        <DialogDescription>No bookings are offered on these days.</DialogDescription>
      </DialogHeader>
      <ul className="divide-y text-sm">
        {(entries.data ?? []).length === 0 && <li className="py-2 text-muted-foreground">No time off scheduled.</li>}
        {(entries.data ?? []).map((t) => (
          <li key={t.id} className="py-2">
            {formatDateTime(t.starts_at, timeZone)} → {formatDateTime(t.ends_at, timeZone)}
            {t.reason && <span className="text-muted-foreground"> · {t.reason}</span>}
          </li>
        ))}
      </ul>
      <form
        className="space-y-3 border-t pt-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (!from || !to || to < from) return setError("The last day can not be before the first day.");
          setError(null);
          add.mutate();
        }}
      >
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="off-from">First day</Label>
            <Input id="off-from" type="date" min={today} value={from} onChange={(e) => setFrom(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="off-to">Last day</Label>
            <Input id="off-to" type="date" min={from} value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="off-reason">Reason (optional)</Label>
          <Input id="off-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button type="submit" disabled={add.isPending}>
            {add.isPending ? "Adding…" : "Add time off"}
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
