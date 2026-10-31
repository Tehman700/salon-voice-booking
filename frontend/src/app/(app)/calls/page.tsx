"use client";

import { useState } from "react";

import { BarChart, SplitBars } from "@/components/bars";
import { OUTCOME_BAR, OUTCOME_LABEL, OutcomeBadge } from "@/components/outcome-badge";
import { EmptyState, ErrorNotice, PageHeader, StatCard, TableSkeleton } from "@/components/page-bits";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { CallLog, CallOutcome } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useCallsQuery, useCallStatsQuery } from "@/lib/hooks";
import { useLocationScope } from "@/lib/location-scope";

const OUTCOMES = Object.keys(OUTCOME_LABEL) as CallOutcome[];

function duration(seconds: number | null) {
  if (seconds === null) return "—";
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export default function CallsPage() {
  const scope = useLocationScope();
  const calls = useCallsQuery(scope.locationId);
  const stats = useCallStatsQuery(scope.locationId);
  const [open, setOpen] = useState<CallLog | null>(null);
  const list = calls.data ?? [];
  const tz = (c: CallLog) => scope.getLocation(c.location_id)?.timezone ?? scope.timeZone;
  const handled = stats.data ? stats.data.by_outcome.booked + stats.data.by_outcome.rescheduled + stats.data.by_outcome.cancelled : 0;

  return (
    <>
      <PageHeader title="Voice calls" description="Every call the AI receptionist took, with what it did about it." />

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Calls" value={stats.data?.total ?? 0} hint="last 14 days" loading={stats.isLoading} />
        <StatCard label="Booking actions" value={handled} hint="booked, moved or cancelled" loading={stats.isLoading} />
        <StatCard
          label="Resolved by the agent"
          value={stats.data && stats.data.total ? `${Math.round(((stats.data.total - stats.data.by_outcome.failed - stats.data.by_outcome.abandoned) / stats.data.total) * 100)}%` : "—"}
          hint="not failed or abandoned"
          loading={stats.isLoading}
        />
      </div>

      {stats.data && (
        <div className="mt-6 grid gap-6 lg:grid-cols-5">
          <Card className="lg:col-span-3">
            <CardHeader>
              <CardTitle>Calls per day</CardTitle>
            </CardHeader>
            <CardContent>
              <BarChart ariaLabel="Calls per day" data={stats.data.per_day.map((d) => ({ label: d.date.slice(8), value: d.count }))} />
            </CardContent>
          </Card>
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Outcomes</CardTitle>
              <CardDescription>What happened on each call</CardDescription>
            </CardHeader>
            <CardContent>
              <SplitBars
                total={stats.data.total}
                rows={OUTCOMES.map((o) => ({ label: OUTCOME_LABEL[o], value: stats.data!.by_outcome[o], color: OUTCOME_BAR[o] }))}
              />
            </CardContent>
          </Card>
        </div>
      )}

      <h2 className="mb-3 mt-8 text-lg font-semibold tracking-[-0.6px]">Call log</h2>
      {calls.isError ? (
        <ErrorNotice message="Couldn't load calls." onRetry={() => calls.refetch()} />
      ) : calls.isLoading ? (
        <TableSkeleton />
      ) : list.length === 0 ? (
        <EmptyState title="No calls yet" description="Calls will appear here once the phone line is connected." />
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card shadow-card">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow>
                {["When", "Caller", "Location", "Length", "Outcome", "Summary"].map((h) => (
                  <TableHead key={h} className="font-mono text-xs uppercase">
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((c) => (
                <TableRow key={c.id} className="cursor-pointer" onClick={() => setOpen(c)}>
                  <TableCell className="whitespace-nowrap">{formatDateTime(c.started_at, tz(c))}</TableCell>
                  <TableCell className="font-mono text-xs">{c.from_number}</TableCell>
                  <TableCell>{scope.getLocation(c.location_id)?.name ?? "—"}</TableCell>
                  <TableCell className="font-mono text-xs">{duration(c.duration_seconds)}</TableCell>
                  <TableCell>
                    <OutcomeBadge outcome={c.outcome} />
                  </TableCell>
                  <TableCell className="max-w-xs truncate text-muted-foreground">{c.summary ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
          {open && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  {open.from_number} <OutcomeBadge outcome={open.outcome} />
                </DialogTitle>
                <DialogDescription>
                  {formatDateTime(open.started_at, tz(open))} · {duration(open.duration_seconds)}
                </DialogDescription>
              </DialogHeader>
              {open.summary && <p className="rounded-md bg-muted p-3 text-sm">{open.summary}</p>}
              <p className="font-mono text-xs uppercase text-muted-foreground">Transcript</p>
              {open.transcript?.length ? (
                <ul className="space-y-2">
                  {open.transcript.map((line, i) => (
                    <li key={i} className={`flex ${line.role === "agent" ? "justify-start" : "justify-end"}`}>
                      <span
                        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                          line.role === "agent" ? "bg-muted" : "bg-primary text-primary-foreground"
                        }`}
                      >
                        <span className="sr-only">{line.role === "agent" ? "Agent: " : "Caller: "}</span>
                        {line.text}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No transcript was recorded for this call.</p>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
