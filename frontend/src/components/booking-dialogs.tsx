"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { StatusBadge } from "@/components/status-badge";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, type Booking, type Slot } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { formatDateTime, formatMoney, formatTime, todayKey } from "@/lib/format";
import {
  toastError,
  useInvalidateBookings,
  useServicesQuery,
  useStaffQuery,
} from "@/lib/hooks";
import { useLocationScope } from "@/lib/location-scope";

const ANY = "any";

/** Date + available time slots for one service, as reported by the availability engine. */
function SlotPicker({
  locationId,
  serviceId,
  staffId,
  value,
  onChange,
  timeZone,
}: {
  locationId: string;
  serviceId: string;
  staffId: string | undefined;
  value: Slot | null;
  onChange: (slot: Slot | null) => void;
  timeZone: string;
}) {
  const [date, setDate] = useState(todayKey(timeZone));
  const enabled = !!locationId && !!serviceId && !!date;
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ["slots", locationId, serviceId, staffId ?? ANY, date],
    queryFn: () =>
      api.availability.search({
        location_id: locationId,
        service_id: serviceId,
        staff_id: staffId,
        date_from: date,
        date_to: date,
      }),
    enabled,
    staleTime: 0,
  });

  // Offer each time once; with "any staff" the same time may exist for several people.
  const unique = useMemo(() => {
    const seen = new Set<string>();
    return (data?.slots ?? []).filter((s) => (seen.has(s.starts_at) ? false : (seen.add(s.starts_at), true)));
  }, [data]);

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label htmlFor="slot-date">Date</Label>
        <Input
          id="slot-date"
          type="date"
          min={todayKey(timeZone)}
          value={date}
          onChange={(e) => {
            setDate(e.target.value);
            onChange(null);
          }}
        />
      </div>
      <div className="space-y-1.5">
        <Label>Available times</Label>
        {!serviceId ? (
          <p className="text-sm text-muted-foreground">Choose a service to see times.</p>
        ) : isFetching && !data ? (
          <p className="text-sm text-muted-foreground">Checking availability…</p>
        ) : error ? (
          <p className="text-sm text-destructive">
            Couldn&apos;t load times.{" "}
            <button className="underline" onClick={() => refetch()}>
              Retry
            </button>
          </p>
        ) : unique.length === 0 ? (
          <p className="text-sm text-muted-foreground">No free times on this day. Try another date.</p>
        ) : (
          <div className="grid max-h-44 grid-cols-3 gap-2 overflow-y-auto pr-1 sm:grid-cols-4" role="radiogroup" aria-label="Available times">
            {unique.map((slot) => {
              const selected = value?.starts_at === slot.starts_at;
              return (
                <Button
                  key={slot.starts_at}
                  type="button"
                  size="sm"
                  role="radio"
                  aria-checked={selected}
                  variant={selected ? "default" : "outline"}
                  onClick={() => onChange(slot)}
                >
                  {formatTime(slot.starts_at, timeZone)}
                </Button>
              );
            })}
          </div>
        )}
        {value && (
          <p className="text-xs text-muted-foreground">
            With {value.staff_name} · {formatDateTime(value.starts_at, timeZone)}
          </p>
        )}
      </div>
    </div>
  );
}

/** Turn a failed save into a message, and refresh the times when the slot was just taken. */
function handleBookingError(error: unknown, refreshSlots: () => void) {
  if (error instanceof ApiError && error.code === "slot_unavailable") {
    toast.error("That time was just taken. Please pick another.");
    refreshSlots();
    return;
  }
  toastError(error);
}

export function NewBookingDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        {/* Mounted only while open, so every opening starts with a blank form. */}
        {open && <NewBookingForm onOpenChange={onOpenChange} />}
      </DialogContent>
    </Dialog>
  );
}

function NewBookingForm({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  const scope = useLocationScope();
  const invalidate = useInvalidateBookings();
  const { data: services = [] } = useServicesQuery();
  const activeLocations = scope.locations.filter((l) => l.is_active);
  // Derived until the user picks one, so it is right even if locations finish loading after opening.
  const [pickedLocation, setLocationId] = useState<string | null>(null);
  const locationId = pickedLocation ?? scope.locationId ?? activeLocations[0]?.id ?? "";
  const [serviceId, setServiceId] = useState("");
  const [staffChoice, setStaffChoice] = useState(ANY);
  const [slot, setSlot] = useState<Slot | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [slotsVersion, setSlotsVersion] = useState(0);

  const location = scope.getLocation(locationId);
  const timeZone = location?.timezone ?? scope.timeZone;
  const { data: staff = [] } = useStaffQuery(locationId || undefined);

  const offered = services.filter(
    (s) =>
      s.is_active &&
      s.location_overrides.find((o) => o.location_id === locationId)?.is_offered !== false,
  );
  const capableStaff = staff.filter(
    (s) => s.is_active && (!serviceId || s.service_ids.includes(serviceId)),
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!serviceId) next.service = "Choose a service";
    if (!slot) next.slot = "Choose a time";
    if (!name.trim()) next.name = "Enter the customer's name";
    if (!/^\+?[0-9 ()-]{7,20}$/.test(phone.trim())) next.phone = "Enter a valid phone number";
    setErrors(next);
    if (Object.keys(next).length || !slot) return;

    setSaving(true);
    try {
      const booking = await api.bookings.create({
        location_id: locationId,
        service_id: serviceId,
        staff_id: slot.staff_id,
        starts_at: slot.starts_at,
        customer: { full_name: name.trim(), phone: phone.trim(), email: email.trim() || null },
        notes: notes.trim() || null,
      });
      void invalidate(); // refresh the lists in the background; confirm to the user straight away
      toast.success(`Booked ${booking.customer.full_name} · ${formatDateTime(booking.starts_at, timeZone)}`);
      onOpenChange(false);
    } catch (error) {
      handleBookingError(error, () => {
        setSlot(null);
        setSlotsVersion((v) => v + 1);
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
        <DialogHeader>
          <DialogTitle>New booking</DialogTitle>
          <DialogDescription>Only times that are really free are offered, so double bookings can&apos;t happen.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" noValidate>
          {activeLocations.length > 1 && (
            <div className="space-y-1.5">
              <Label>Location</Label>
              <Select
                value={locationId}
                onValueChange={(v) => {
                  setLocationId(v);
                  setServiceId("");
                  setStaffChoice(ANY);
                  setSlot(null);
                }}
              >
                <SelectTrigger className="w-full" aria-label="Location">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {activeLocations.map((l) => (
                    <SelectItem key={l.id} value={l.id}>
                      {l.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Service</Label>
              <Select
                value={serviceId}
                onValueChange={(v) => {
                  setServiceId(v);
                  setStaffChoice(ANY);
                  setSlot(null);
                }}
              >
                <SelectTrigger className="w-full" aria-label="Service" aria-invalid={!!errors.service}>
                  <SelectValue placeholder="Choose a service" />
                </SelectTrigger>
                <SelectContent>
                  {offered.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name} · {formatMoney(s.price_minor, s.currency)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.service && <p className="text-xs text-destructive">{errors.service}</p>}
            </div>
            <div className="space-y-1.5">
              <Label>Stylist</Label>
              <Select
                value={staffChoice}
                onValueChange={(v) => {
                  setStaffChoice(v);
                  setSlot(null);
                }}
              >
                <SelectTrigger className="w-full" aria-label="Stylist">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY}>Any available</SelectItem>
                  {capableStaff.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.full_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <SlotPicker
            key={`${locationId}-${serviceId}-${staffChoice}-${slotsVersion}`}
            locationId={locationId}
            serviceId={serviceId}
            staffId={staffChoice === ANY ? undefined : staffChoice}
            value={slot}
            onChange={setSlot}
            timeZone={timeZone}
          />
          {errors.slot && <p className="-mt-2 text-xs text-destructive">{errors.slot}</p>}

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="customer-name">Customer name</Label>
              <Input id="customer-name" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!errors.name} />
              {errors.name && <p className="text-xs text-destructive">{errors.name}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="customer-phone">Phone</Label>
              <Input
                id="customer-phone"
                type="tel"
                placeholder="+92 300 1234567"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                aria-invalid={!!errors.phone}
              />
              {errors.phone && <p className="text-xs text-destructive">{errors.phone}</p>}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="customer-email">Email (optional)</Label>
            <Input id="customer-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="booking-notes">Notes (optional)</Label>
            <Textarea id="booking-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Booking…" : "Create booking"}
            </Button>
          </DialogFooter>
        </form>
    </>
  );
}

export function RescheduleDialog({
  booking,
  onOpenChange,
}: {
  booking: Booking | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={!!booking} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {booking && <RescheduleBody key={booking.id} booking={booking} onOpenChange={onOpenChange} />}
      </DialogContent>
    </Dialog>
  );
}

function RescheduleBody({
  booking,
  onOpenChange,
}: {
  booking: Booking;
  onOpenChange: (open: boolean) => void;
}) {
  const scope = useLocationScope();
  const invalidate = useInvalidateBookings();
  const [slot, setSlot] = useState<Slot | null>(null);
  const [saving, setSaving] = useState(false);
  const [version, setVersion] = useState(0);
  const timeZone = scope.getLocation(booking.location_id)?.timezone ?? scope.timeZone;

  async function save() {
    if (!slot) return;
    setSaving(true);
    try {
      await api.bookings.update(booking.id, { starts_at: slot.starts_at, staff_id: slot.staff_id });
      void invalidate(); // refresh the lists in the background; confirm to the user straight away
      toast.success(`Moved to ${formatDateTime(slot.starts_at, timeZone)}`);
      onOpenChange(false);
    } catch (error) {
      handleBookingError(error, () => {
        setSlot(null);
        setVersion((v) => v + 1);
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Reschedule booking</DialogTitle>
        <DialogDescription>
          {booking.customer.full_name} · currently {formatDateTime(booking.starts_at, timeZone)}
        </DialogDescription>
      </DialogHeader>
      <SlotPicker
        key={version}
        locationId={booking.location_id}
        serviceId={booking.service_id}
        staffId={undefined}
        value={slot}
        onChange={setSlot}
        timeZone={timeZone}
      />
      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          Keep current time
        </Button>
        <Button onClick={save} disabled={!slot || saving}>
          {saving ? "Saving…" : "Move booking"}
        </Button>
      </DialogFooter>
    </>
  );
}

export function CancelBookingDialog({
  booking,
  onOpenChange,
}: {
  booking: Booking | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <AlertDialog open={!!booking} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        {booking && <CancelBody key={booking.id} booking={booking} onOpenChange={onOpenChange} />}
      </AlertDialogContent>
    </AlertDialog>
  );
}

function CancelBody({
  booking,
  onOpenChange,
}: {
  booking: Booking;
  onOpenChange: (open: boolean) => void;
}) {
  const me = useMe();
  const scope = useLocationScope();
  const invalidate = useInvalidateBookings();
  const [saving, setSaving] = useState(false);
  const [windowMessage, setWindowMessage] = useState<string | null>(null);
  const canOverride = me.role !== "staff";
  const timeZone = scope.getLocation(booking.location_id)?.timezone ?? scope.timeZone;

  async function cancel(force: boolean) {
    setSaving(true);
    try {
      await api.bookings.cancel(booking.id, { force });
      void invalidate(); // refresh the lists in the background; confirm to the user straight away
      toast.success("Booking cancelled");
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.code === "cancellation_window_passed") {
        setWindowMessage(error.message);
      } else {
        toastError(error);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <AlertDialogHeader>
        <AlertDialogTitle>{windowMessage ? "Inside the cancellation window" : "Cancel this booking?"}</AlertDialogTitle>
        <AlertDialogDescription>
          {windowMessage
            ? canOverride
              ? `${windowMessage} As a manager you can still cancel it.`
              : `${windowMessage} Ask a manager to cancel it.`
            : `${booking.customer.full_name} · ${formatDateTime(booking.starts_at, timeZone)}. This frees the time for other customers.`}
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>Keep booking</AlertDialogCancel>
        {(!windowMessage || canOverride) && (
          <Button variant="destructive" disabled={saving} onClick={() => cancel(!!windowMessage)}>
            {saving ? "Cancelling…" : windowMessage ? "Cancel anyway" : "Cancel booking"}
          </Button>
        )}
      </AlertDialogFooter>
    </>
  );
}

export function BookingDetailsDialog({
  booking,
  onClose,
  onReschedule,
  onCancel,
}: {
  booking: Booking | null;
  onClose: () => void;
  onReschedule: (booking: Booking) => void;
  onCancel: (booking: Booking) => void;
}) {
  const scope = useLocationScope();
  const { data: services = [] } = useServicesQuery();
  const { data: staff = [] } = useStaffQuery();
  const timeZone = booking ? (scope.getLocation(booking.location_id)?.timezone ?? scope.timeZone) : scope.timeZone;
  const service = services.find((s) => s.id === booking?.service_id);
  const stylist = staff.find((s) => s.id === booking?.staff_id);
  const active = booking?.status === "booked";

  return (
    <Dialog open={!!booking} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        {booking && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {booking.customer.full_name}
                <StatusBadge status={booking.status} />
              </DialogTitle>
              <DialogDescription className="font-mono text-xs uppercase">Ref {booking.reference}</DialogDescription>
            </DialogHeader>
            <dl className="grid grid-cols-[110px_1fr] gap-y-2 text-sm">
              <dt className="text-muted-foreground">When</dt>
              <dd>{formatDateTime(booking.starts_at, timeZone)}</dd>
              <dt className="text-muted-foreground">Service</dt>
              <dd>
                {service?.name ?? "—"} · {formatMoney(booking.price_minor, booking.currency)}
              </dd>
              <dt className="text-muted-foreground">Stylist</dt>
              <dd>{stylist?.full_name ?? "—"}</dd>
              <dt className="text-muted-foreground">Location</dt>
              <dd>{scope.getLocation(booking.location_id)?.name ?? "—"}</dd>
              <dt className="text-muted-foreground">Phone</dt>
              <dd>{booking.customer.phone}</dd>
              <dt className="text-muted-foreground">Booked via</dt>
              <dd>
                <Badge variant="secondary">{booking.source === "voice" ? "Voice agent" : "Dashboard"}</Badge>
              </dd>
              {booking.notes && (
                <>
                  <dt className="text-muted-foreground">Notes</dt>
                  <dd>{booking.notes}</dd>
                </>
              )}
              {booking.cancellation_reason && (
                <>
                  <dt className="text-muted-foreground">Cancelled</dt>
                  <dd>{booking.cancellation_reason}</dd>
                </>
              )}
            </dl>
            {active && (
              <DialogFooter>
                <Button variant="destructive" onClick={() => onCancel(booking)}>
                  Cancel booking
                </Button>
                <Button onClick={() => onReschedule(booking)}>Reschedule</Button>
              </DialogFooter>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
