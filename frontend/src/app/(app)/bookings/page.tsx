"use client";

import { MoreHorizontal, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";

import {
  BookingDetailsDialog,
  CancelBookingDialog,
  NewBookingDialog,
  RescheduleDialog,
} from "@/components/booking-dialogs";
import { SourceBadge } from "@/components/outcome-badge";
import { EmptyState, ErrorNotice, PageHeader, TableSkeleton } from "@/components/page-bits";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Booking, BookingSource, BookingStatus } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import { useBookingsQuery, useServicesQuery, useStaffQuery } from "@/lib/hooks";
import { useLocationScope } from "@/lib/location-scope";

const PAGE_SIZE = 100;

export default function BookingsPage() {
  const scope = useLocationScope();
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const [status, setStatus] = useState<"all" | BookingStatus>("all");
  const [source, setSource] = useState<"all" | BookingSource>("all");
  const [stylist, setStylist] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [creating, setCreating] = useState(false);
  const [viewing, setViewing] = useState<Booking | null>(null);
  const [rescheduling, setRescheduling] = useState<Booking | null>(null);
  const [cancelling, setCancelling] = useState<Booking | null>(null);

  const staff = useStaffQuery(scope.locationId);
  const services = useServicesQuery();
  const bookings = useBookingsQuery({
    location_id: scope.locationId,
    q: q || undefined,
    status: status === "all" ? undefined : status,
    source: source === "all" ? undefined : source,
    staff_id: stylist === "all" ? undefined : stylist,
    from: from || undefined,
    to: to || undefined,
  });

  const list = [...(bookings.data ?? [])].sort((a, b) => b.starts_at.localeCompare(a.starts_at));
  const filtered = status !== "all" || source !== "all" || stylist !== "all" || !!from || !!to || !!q;
  const tz = (b: Booking) => scope.getLocation(b.location_id)?.timezone ?? scope.timeZone;

  function clearFilters() {
    setSearch("");
    setStatus("all");
    setSource("all");
    setStylist("all");
    setFrom("");
    setTo("");
    setVisible(PAGE_SIZE);
  }

  return (
    <>
      <PageHeader
        title="Bookings"
        description="Every appointment, whether it came from the phone line or the dashboard."
        actions={<Button onClick={() => setCreating(true)}>New booking</Button>}
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
          <Input
            className="pl-8"
            placeholder="Search name, phone or reference"
            aria-label="Search bookings"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Select value={status} onValueChange={(v) => setStatus(v as typeof status)}>
          <SelectTrigger className="w-[140px]" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="booked">Booked</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
            <SelectItem value="cancelled">Cancelled</SelectItem>
            <SelectItem value="no_show">No-show</SelectItem>
          </SelectContent>
        </Select>
        <Select value={source} onValueChange={(v) => setSource(v as typeof source)}>
          <SelectTrigger className="w-[140px]" aria-label="Source">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any source</SelectItem>
            <SelectItem value="voice">Voice agent</SelectItem>
            <SelectItem value="dashboard">Dashboard</SelectItem>
          </SelectContent>
        </Select>
        <Select value={stylist} onValueChange={setStylist}>
          <SelectTrigger className="w-[160px]" aria-label="Stylist">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All stylists</SelectItem>
            {(staff.data ?? []).map((s) => (
              <SelectItem key={s.id} value={s.id}>
                {s.full_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex items-center gap-2">
          <Input type="date" className="w-[150px]" aria-label="From date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <span className="text-muted-foreground">–</span>
          <Input type="date" className="w-[150px]" aria-label="To date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        {filtered && (
          <Button variant="ghost" onClick={clearFilters}>
            Clear
          </Button>
        )}
      </div>

      {bookings.isError ? (
        <ErrorNotice message="Couldn't load bookings." onRetry={() => bookings.refetch()} />
      ) : bookings.isLoading ? (
        <TableSkeleton />
      ) : list.length === 0 ? (
        <EmptyState
          title={filtered ? "No bookings match these filters" : "No bookings yet"}
          description={filtered ? "Try widening the date range or clearing the filters." : "Create the first one, or wait for a call."}
          action={filtered ? <Button variant="outline" onClick={clearFilters}>Clear filters</Button> : <Button onClick={() => setCreating(true)}>New booking</Button>}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card shadow-card">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow>
                {["When", "Customer", "Service", "Stylist", "Source", "Status", "Price", ""].map((h) => (
                  <TableHead key={h || "actions"} className="font-mono text-xs uppercase">
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.slice(0, visible).map((b) => (
                <TableRow key={b.id} className="cursor-pointer" onClick={() => setViewing(b)}>
                  <TableCell className="whitespace-nowrap">{formatDateTime(b.starts_at, tz(b))}</TableCell>
                  <TableCell>
                    <div className="font-medium">{b.customer.full_name}</div>
                    <div className="text-xs text-muted-foreground">{b.customer.phone}</div>
                  </TableCell>
                  <TableCell>{services.data?.find((s) => s.id === b.service_id)?.name ?? "—"}</TableCell>
                  <TableCell>{staff.data?.find((s) => s.id === b.staff_id)?.full_name ?? "—"}</TableCell>
                  <TableCell>
                    <SourceBadge source={b.source} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={b.status} />
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{formatMoney(b.price_minor, b.currency)}</TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${b.customer.full_name}`}>
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setViewing(b)}>View details</DropdownMenuItem>
                        {b.status === "booked" && (
                          <>
                            <DropdownMenuItem onClick={() => setRescheduling(b)}>Reschedule</DropdownMenuItem>
                            <DropdownMenuItem variant="destructive" onClick={() => setCancelling(b)}>
                              Cancel booking
                            </DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="flex items-center justify-between border-t px-4 py-2 text-xs text-muted-foreground">
            <span>
              Showing {Math.min(visible, list.length)} of {list.length} bookings
            </span>
            {list.length > visible && (
              <Button variant="ghost" size="sm" onClick={() => setVisible((v) => v + PAGE_SIZE)}>
                Show more
              </Button>
            )}
          </div>
        </div>
      )}

      <BookingDetailsDialog
        booking={viewing && !rescheduling && !cancelling ? viewing : null}
        onClose={() => setViewing(null)}
        onReschedule={setRescheduling}
        onCancel={setCancelling}
      />
      <RescheduleDialog
        booking={rescheduling}
        onOpenChange={(open) => {
          if (!open) {
            setRescheduling(null);
            setViewing(null);
          }
        }}
      />
      <CancelBookingDialog
        booking={cancelling}
        onOpenChange={(open) => {
          if (!open) {
            setCancelling(null);
            setViewing(null);
          }
        }}
      />
      <NewBookingDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}
