"use client";

import { Search } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { EmptyState, ErrorNotice, PageHeader, TableSkeleton } from "@/components/page-bits";
import { StatusBadge } from "@/components/status-badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime, formatDay, formatMoney } from "@/lib/format";
import { useCustomerQuery, useCustomersQuery, useServicesQuery } from "@/lib/hooks";
import { useLocationScope } from "@/lib/location-scope";

export default function CustomersPage() {
  const { timeZone } = useLocationScope();
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const customers = useCustomersQuery(q);
  const [openId, setOpenId] = useState<string | null>(null);
  const detail = useCustomerQuery(openId);
  const services = useServicesQuery();
  const list = customers.data ?? [];

  return (
    <>
      <PageHeader title="Customers" description="Shared across all of your locations, with their full appointment history." />
      <div className="relative mb-4 max-w-md">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
        <Input
          className="pl-8"
          placeholder="Search by name or phone"
          aria-label="Search customers"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {customers.isError ? (
        <ErrorNotice message="Couldn't load customers." onRetry={() => customers.refetch()} />
      ) : customers.isLoading ? (
        <TableSkeleton />
      ) : list.length === 0 ? (
        <EmptyState title={q ? "No customers match" : "No customers yet"} description="Customers are created automatically when they book." />
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card shadow-card">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow>
                {["Customer", "Phone", "Email", "Visits", "Last visit"].map((h) => (
                  <TableHead key={h} className="font-mono text-xs uppercase">
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((c) => (
                <TableRow key={c.id} className="cursor-pointer" onClick={() => setOpenId(c.id)}>
                  <TableCell className="font-medium">{c.full_name}</TableCell>
                  <TableCell>{c.phone}</TableCell>
                  <TableCell className="text-muted-foreground">{c.email ?? "—"}</TableCell>
                  <TableCell>{c.booking_count}</TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {c.last_visit_at ? formatDay(c.last_visit_at, timeZone) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="border-t px-4 py-2 text-xs text-muted-foreground">{list.length} customers</p>
        </div>
      )}

      <Dialog open={!!openId} onOpenChange={(open) => !open && setOpenId(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{detail.data?.full_name ?? "Customer"}</DialogTitle>
            <DialogDescription>
              {detail.data ? `${detail.data.phone}${detail.data.email ? ` · ${detail.data.email}` : ""}` : "Loading…"}
            </DialogDescription>
          </DialogHeader>
          {detail.isLoading ? (
            <TableSkeleton rows={3} />
          ) : (
            <>
              {detail.data?.notes && <p className="rounded-md bg-muted p-3 text-sm">{detail.data.notes}</p>}
              <p className="font-mono text-xs uppercase text-muted-foreground">Appointment history</p>
              <ul className="divide-y">
                {[...(detail.data?.bookings ?? [])]
                  .sort((a, b) => b.starts_at.localeCompare(a.starts_at))
                  .map((b) => (
                    <li key={b.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                      <div className="min-w-0">
                        <p className="truncate font-medium">{services.data?.find((s) => s.id === b.service_id)?.name ?? "Booking"}</p>
                        <p className="text-xs text-muted-foreground">
                          {formatDateTime(b.starts_at, timeZone)} · {formatMoney(b.price_minor, b.currency)}
                        </p>
                      </div>
                      <StatusBadge status={b.status} />
                    </li>
                  ))}
              </ul>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
