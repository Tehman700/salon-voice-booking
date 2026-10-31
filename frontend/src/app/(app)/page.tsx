"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { BarChart } from "@/components/bars";
import { NewBookingDialog } from "@/components/booking-dialogs";
import { OutcomeBadge } from "@/components/outcome-badge";
import { EmptyState, ErrorNotice, PageHeader, StatCard, TableSkeleton } from "@/components/page-bits";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { addDays, dateKey, formatDateTime, formatTime, todayKey } from "@/lib/format";
import {
  useBookingsQuery,
  useCallsQuery,
  useCallStatsQuery,
  useServicesQuery,
  useStaffQuery,
} from "@/lib/hooks";
import { useLocationScope } from "@/lib/location-scope";

export default function OverviewPage() {
  const { locationId, timeZone, current, getLocation } = useLocationScope();
  const [creating, setCreating] = useState(false);
  const today = todayKey(timeZone);

  // One query covers today, the coming week and the last week, so the cards agree with each other.
  const range = { location_id: locationId, from: addDays(today, -7), to: addDays(today, 7) };
  const bookings = useBookingsQuery(range);
  const services = useServicesQuery();
  const staff = useStaffQuery(locationId);
  const calls = useCallsQuery(locationId);
  const stats = useCallStatsQuery(locationId);

  const summary = useMemo(() => {
    const all = bookings.data ?? [];
    const day = (iso: string) => dateKey(iso, timeZone);
    const todays = all.filter((b) => day(b.starts_at) === today && b.status !== "cancelled");
    const upcoming = all.filter((b) => day(b.starts_at) > today && b.status === "booked");
    const cancelled = all.filter((b) => b.status === "cancelled");
    const recent = all.filter((b) => b.status !== "cancelled");
    const voice = recent.filter((b) => b.source === "voice").length;
    return {
      todays,
      upcoming: upcoming.length,
      cancelled: cancelled.length,
      voiceShare: recent.length ? Math.round((voice / recent.length) * 100) : 0,
    };
  }, [bookings.data, timeZone, today]);

  const serviceName = (id: string) => services.data?.find((s) => s.id === id)?.name ?? "—";
  const staffName = (id: string) => staff.data?.find((s) => s.id === id)?.full_name ?? "—";
  const loading = bookings.isLoading;

  return (
    <>
      <PageHeader
        title="Overview"
        description={current && !locationId ? "All locations" : current?.name}
        actions={<Button onClick={() => setCreating(true)}>New booking</Button>}
      />
      {bookings.isError && (
        <div className="mb-4">
          <ErrorNotice message="Couldn't load bookings." onRetry={() => bookings.refetch()} />
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Today" value={summary.todays.length} hint="appointments" loading={loading} />
        <StatCard label="Upcoming" value={summary.upcoming} hint="booked in the next 7 days" loading={loading} />
        <StatCard label="Cancellations" value={summary.cancelled} hint="in the last 7 days" loading={loading} />
        <StatCard label="Booked by voice" value={`${summary.voiceShare}%`} hint="of recent bookings" loading={loading} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Today&apos;s schedule</CardTitle>
            <CardDescription>
              {new Intl.DateTimeFormat("en-GB", { dateStyle: "full", timeZone }).format(new Date())}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <TableSkeleton rows={4} />
            ) : summary.todays.length === 0 ? (
              <EmptyState
                title="Nothing booked today"
                description="New bookings from the phone line and the dashboard will show up here."
                action={<Button variant="outline" onClick={() => setCreating(true)}>Add a booking</Button>}
              />
            ) : (
              <ul className="divide-y">
                {summary.todays.map((b) => (
                  <li key={b.id} className="flex items-center gap-3 py-3">
                    <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground">
                      {formatTime(b.starts_at, getLocation(b.location_id)?.timezone ?? timeZone)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{b.customer.full_name}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {serviceName(b.service_id)} · {staffName(b.staff_id)}
                      </p>
                    </div>
                    <StatusBadge status={b.status} />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Voice agent</CardTitle>
            <CardDescription>Calls per day, last two weeks</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {stats.data ? (
              <>
                <p className="text-3xl font-semibold tracking-[-1.28px]">
                  {stats.data.total}
                  <span className="ml-2 text-sm font-normal tracking-normal text-muted-foreground">calls</span>
                </p>
                <BarChart
                  ariaLabel="Calls per day"
                  data={stats.data.per_day.map((d) => ({ label: d.date.slice(8), value: d.count }))}
                />
              </>
            ) : (
              <TableSkeleton rows={3} />
            )}
            <div className="border-t pt-4">
              <p className="mb-2 font-mono text-xs uppercase text-muted-foreground">Recent calls</p>
              {calls.data?.slice(0, 4).map((c) => (
                <div key={c.id} className="flex items-center justify-between gap-2 py-1.5 text-sm">
                  <span className="min-w-0 truncate text-muted-foreground">
                    {c.from_number} · {formatDateTime(c.started_at, getLocation(c.location_id)?.timezone ?? timeZone)}
                  </span>
                  <OutcomeBadge outcome={c.outcome} />
                </div>
              ))}
              <Button asChild variant="link" className="mt-1 px-0">
                <Link href="/calls">All calls</Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <NewBookingDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}
