"use client";

import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/react/daygrid";
import interactionPlugin from "@fullcalendar/react/interaction";
import classicTheme from "@fullcalendar/react/themes/classic";
import timeGridPlugin from "@fullcalendar/react/timegrid";
import { useMemo } from "react";

import "@fullcalendar/react/themes/classic/theme.css";
import "@fullcalendar/react/themes/classic/palette.css";

import type { Booking, Service, Staff } from "@/lib/api";

const FALLBACK_COLOR = "#737373";

export function BookingCalendar({
  bookings,
  staff,
  services,
  timeZone,
  onSelect,
  onRangeChange,
}: {
  bookings: Booking[];
  staff: Staff[];
  services: Service[];
  timeZone: string;
  onSelect: (bookingId: string) => void;
  onRangeChange: (range: { from: string; to: string }) => void;
}) {
  const events = useMemo(
    () =>
      bookings
        .filter((b) => b.status !== "cancelled")
        .map((b) => {
          const stylist = staff.find((s) => s.id === b.staff_id);
          const service = services.find((s) => s.id === b.service_id);
          return {
            id: b.id,
            title: `${b.customer.full_name} · ${service?.name ?? "Booking"}`,
            start: b.starts_at,
            end: b.ends_at,
            color: stylist?.color ?? FALLBACK_COLOR,
            contrastColor: "#ffffff",
            classNames: b.status === "completed" || b.status === "no_show" ? ["opacity-60"] : [],
          };
        }),
    [bookings, staff, services],
  );

  return (
    <div className="salon-calendar rounded-lg border bg-card p-2 shadow-card sm:p-4">
      <FullCalendar
        plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin, classicTheme]}
        initialView="timeGridWeek"
        timeZone={timeZone}
        headerToolbar={{
          left: "prev,next today",
          center: "title",
          right: "dayGridMonth,timeGridWeek,timeGridDay",
        }}
        slotMinTime="08:00:00"
        slotMaxTime="21:00:00"
        nowIndicator
        height={720}
        events={events}
        eventClick={(info) => onSelect(String(info.event.id))}
        datesSet={(info) => onRangeChange({ from: info.startStr.slice(0, 10), to: info.endStr.slice(0, 10) })}
      />
    </div>
  );
}
