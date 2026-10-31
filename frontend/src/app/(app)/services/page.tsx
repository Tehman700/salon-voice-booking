"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorNotice, PageHeader, TableSkeleton } from "@/components/page-bits";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, type Service, type ServiceInput } from "@/lib/api";
import { formatDuration, formatMoney } from "@/lib/format";
import { toastError, useServicesQuery } from "@/lib/hooks";

type Draft = {
  name: string;
  category: string;
  description: string;
  duration: string;
  buffer: string;
  price: string;
  is_active: boolean;
};

const empty: Draft = { name: "", category: "", description: "", duration: "45", buffer: "0", price: "", is_active: true };

export default function ServicesPage() {
  const services = useServicesQuery();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Service | "new" | null>(null);

  const toggle = useMutation({
    mutationFn: (s: Service) => api.services.update(s.id, { is_active: !s.is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["services"] }),
    onError: toastError,
  });

  const list = services.data ?? [];
  return (
    <>
      <PageHeader
        title="Services"
        description="What you offer, how long it takes and what it costs. Durations decide which time slots are offered."
        actions={<Button onClick={() => setEditing("new")}>Add service</Button>}
      />
      {services.isError ? (
        <ErrorNotice message="Couldn't load services." onRetry={() => services.refetch()} />
      ) : services.isLoading ? (
        <TableSkeleton />
      ) : list.length === 0 ? (
        <EmptyState title="No services yet" description="Add what you offer so customers can book it." action={<Button onClick={() => setEditing("new")}>Add service</Button>} />
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card shadow-card">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow>
                {["Service", "Category", "Duration", "Price", "Active", ""].map((h) => (
                  <TableHead key={h || "edit"} className="font-mono text-xs uppercase">
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((s) => (
                <TableRow key={s.id}>
                  <TableCell>
                    <div className="font-medium">{s.name}</div>
                    {s.description && <div className="max-w-sm truncate text-xs text-muted-foreground">{s.description}</div>}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{s.category ?? "—"}</TableCell>
                  <TableCell className="whitespace-nowrap">
                    {formatDuration(s.duration_minutes)}
                    {s.buffer_minutes > 0 && <span className="text-xs text-muted-foreground"> + {s.buffer_minutes} min buffer</span>}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{formatMoney(s.price_minor, s.currency)}</TableCell>
                  <TableCell>
                    <Switch checked={s.is_active} onCheckedChange={() => toggle.mutate(s)} aria-label={`${s.name} active`} />
                  </TableCell>
                  <TableCell>
                    <Button variant="ghost" size="sm" onClick={() => setEditing(s)}>
                      Edit
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <ServiceDialog editing={editing} onClose={() => setEditing(null)} />
    </>
  );
}

function ServiceDialog({ editing, onClose }: { editing: Service | "new" | null; onClose: () => void }) {
  return (
    <Dialog open={!!editing} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        {editing && <ServiceForm key={editing === "new" ? "new" : editing.id} editing={editing} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function ServiceForm({ editing, onClose }: { editing: Service | "new"; onClose: () => void }) {
  const queryClient = useQueryClient();
  const existing = editing === "new" ? null : editing;
  const [draft, setDraft] = useState<Draft>(() =>
    existing
      ? {
          name: existing.name,
          category: existing.category ?? "",
          description: existing.description ?? "",
          duration: String(existing.duration_minutes),
          buffer: String(existing.buffer_minutes),
          price: String(existing.price_minor / 100),
          is_active: existing.is_active,
        }
      : empty,
  );
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: (body: ServiceInput) => (existing ? api.services.update(existing.id, body) : api.services.create(body)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["services"] });
      toast.success(existing ? "Service updated" : "Service added");
      onClose();
    },
    onError: toastError,
  });

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    const duration = Number(draft.duration);
    const buffer = Number(draft.buffer);
    const price = Number(draft.price);
    if (!draft.name.trim()) next.name = "Enter a name";
    if (!Number.isInteger(duration) || duration < 5 || duration > 480) next.duration = "Between 5 and 480 minutes";
    if (!Number.isInteger(buffer) || buffer < 0 || buffer > 120) next.buffer = "Between 0 and 120 minutes";
    if (draft.price === "" || Number.isNaN(price) || price < 0) next.price = "Enter a price";
    setErrors(next);
    if (Object.keys(next).length) return;
    save.mutate({
      name: draft.name.trim(),
      description: draft.description.trim() || null,
      category: draft.category.trim() || null,
      duration_minutes: duration,
      buffer_minutes: buffer,
      price_minor: Math.round(price * 100),
      currency: existing?.currency ?? "PKR",
      is_active: draft.is_active,
      location_overrides: existing?.location_overrides ?? [],
    });
  }

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  return (
    <>
        <DialogHeader>
          <DialogTitle>{existing ? "Edit service" : "Add service"}</DialogTitle>
          <DialogDescription>Prices are in PKR.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="svc-name">Name</Label>
            <Input id="svc-name" value={draft.name} onChange={(e) => set({ name: e.target.value })} aria-invalid={!!errors.name} />
            {errors.name && <p className="text-xs text-destructive">{errors.name}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="svc-category">Category</Label>
            <Input id="svc-category" placeholder="Hair, Nails, Skin…" value={draft.category} onChange={(e) => set({ category: e.target.value })} />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="svc-duration">Minutes</Label>
              <Input id="svc-duration" inputMode="numeric" value={draft.duration} onChange={(e) => set({ duration: e.target.value })} aria-invalid={!!errors.duration} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="svc-buffer">Buffer</Label>
              <Input id="svc-buffer" inputMode="numeric" value={draft.buffer} onChange={(e) => set({ buffer: e.target.value })} aria-invalid={!!errors.buffer} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="svc-price">Price</Label>
              <Input id="svc-price" inputMode="decimal" value={draft.price} onChange={(e) => set({ price: e.target.value })} aria-invalid={!!errors.price} />
            </div>
          </div>
          {(errors.duration || errors.buffer || errors.price) && (
            <p className="-mt-2 text-xs text-destructive">{errors.duration ?? errors.buffer ?? errors.price}</p>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="svc-desc">Description</Label>
            <Textarea id="svc-desc" rows={2} value={draft.description} onChange={(e) => set({ description: e.target.value })} />
          </div>
          <div className="flex items-center justify-between rounded-md border p-3">
            <Label htmlFor="svc-active">Available to book</Label>
            <Switch id="svc-active" checked={draft.is_active} onCheckedChange={(v) => set({ is_active: v })} />
          </div>
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
