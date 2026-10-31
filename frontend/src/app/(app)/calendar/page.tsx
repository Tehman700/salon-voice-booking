"use client";

import { useState } from "react";

import { BookingCalendar } from "@/components/booking-calendar";
import {
  BookingDetailsDialog,
  CancelBookingDialog,
  NewBookingDialog,
  RescheduleDialog,
} from "@/components/booking-dialogs";
import { Dot, ErrorNotice, PageHeader } from "@/components/page-bits";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Booking } from "@/lib/api";
import { useBookingsQuery, useServicesQuery, useStaffQuery } from "@/lib/hooks";
import { useLocationScope } from "@/lib/location-scope";

export default function CalendarPage() {
  const { locationId, timeZone, current, isMulti } = useLocationScope();
  // A calendar only makes sense for one salon (two would overlap), so "all" shows the first.
  const calendarLocationId = locationId ?? current?.id;
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);
  const [stylist, setStylist] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [rescheduling, setRescheduling] = useState<Booking | null>(null);
  const [cancelling, setCancelling] = useState<Booking | null>(null);

  const staff = useStaffQuery(calendarLocationId);
  const services = useServicesQuery();
  const bookings = useBookingsQuery(
    {
      location_id: calendarLocationId,
      staff_id: stylist === "all" ? undefined : stylist,
      from: range?.from,
      to: range?.to,
    },
    !!range && !!calendarLocationId,
  );

  const selected = bookings.data?.find((b) => b.id === selectedId) ?? null;
  const activeStaff = (staff.data ?? []).filter((s) => s.is_active);

  return (
    <>
      <PageHeader
        title="Calendar"
        description={
          isMulti && current
            ? `${current.name}. Click a booking to see it, move it or cancel it. Change salon with the location switcher.`
            : "Day, week and month views. Click a booking to see it, move it or cancel it."
        }
        actions={
          <>
            {activeStaff.length > 1 && (
              <Select value={stylist} onValueChange={setStylist}>
                <SelectTrigger className="w-[180px]" aria-label="Filter by stylist">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All stylists</SelectItem>
                  {activeStaff.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.full_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <Button onClick={() => setCreating(true)}>New booking</Button>
          </>
        }
      />
      {bookings.isError && (
        <div className="mb-4">
          <ErrorNotice message="Couldn't load bookings for this period." onRetry={() => bookings.refetch()} />
        </div>
      )}

      {activeStaff.length > 0 && (
        <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Stylist colors">
          {activeStaff.map((s) => (
            <li key={s.id} className="flex items-center gap-1.5">
              <Dot color={s.color} /> {s.full_name}
            </li>
          ))}
        </ul>
      )}

      <BookingCalendar
        bookings={bookings.data ?? []}
        staff={staff.data ?? []}
        services={services.data ?? []}
        timeZone={timeZone}
        onSelect={setSelectedId}
        onRangeChange={setRange}
      />

      <BookingDetailsDialog
        booking={selected && !rescheduling && !cancelling ? selected : null}
        onClose={() => setSelectedId(null)}
        onReschedule={setRescheduling}
        onCancel={setCancelling}
      />
      <RescheduleDialog booking={rescheduling} onOpenChange={(open) => !open && setRescheduling(null)} />
      <CancelBookingDialog booking={cancelling} onOpenChange={(open) => !open && setCancelling(null)} />
      <NewBookingDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}
