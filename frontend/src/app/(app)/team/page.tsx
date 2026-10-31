"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorNotice, PageHeader, TableSkeleton } from "@/components/page-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError, type Invite, type Role, type User } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { formatDay, ROLE_LABEL } from "@/lib/format";
import { errorMessage, toastError, useUsersQuery } from "@/lib/hooks";
import { useLocationScope } from "@/lib/location-scope";

export default function TeamPage() {
  const me = useMe();
  const scope = useLocationScope();
  const users = useUsersQuery();
  const queryClient = useQueryClient();
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const isOwner = me.role === "owner";

  const toggle = useMutation({
    mutationFn: (u: User) => api.users.update(u.id, { is_active: !u.is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
    onError: toastError,
  });

  const list = users.data ?? [];
  return (
    <>
      <PageHeader
        title="Team"
        description={isOwner ? "Everyone who can sign in to your business." : "People at your location."}
        actions={<Button onClick={() => setInviting(true)}>Invite someone</Button>}
      />
      {users.isError ? (
        <ErrorNotice message="Couldn't load the team." onRetry={() => users.refetch()} />
      ) : users.isLoading ? (
        <TableSkeleton />
      ) : list.length === 0 ? (
        <EmptyState title="Just you so far" description="Invite managers and staff to give them access." />
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card shadow-card">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow>
                {["Name", "Role", "Location", "Last sign-in", "Active", ""].map((h) => (
                  <TableHead key={h || "edit"} className="font-mono text-xs uppercase">
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((u) => (
                <TableRow key={u.id}>
                  <TableCell>
                    <div className="font-medium">
                      {u.full_name} {u.id === me.id && <Badge variant="secondary">You</Badge>}
                    </div>
                    <div className="text-xs text-muted-foreground">{u.email}</div>
                  </TableCell>
                  <TableCell>{ROLE_LABEL[u.role]}</TableCell>
                  <TableCell>{u.location_id ? (scope.getLocation(u.location_id)?.name ?? "—") : "All locations"}</TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {u.last_login_at ? formatDay(u.last_login_at, scope.timeZone) : "Never"}
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={u.is_active}
                      disabled={!isOwner}
                      onCheckedChange={() => toggle.mutate(u)}
                      aria-label={`${u.full_name} active`}
                    />
                  </TableCell>
                  <TableCell>
                    {isOwner && (
                      <Button variant="ghost" size="sm" onClick={() => setEditing(u)}>
                        Edit
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <InviteDialog open={inviting} onOpenChange={setInviting} />
      <EditUserDialog user={editing} onClose={() => setEditing(null)} />
    </>
  );
}

function LocationSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { locations } = useLocationScope();
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-full" aria-label="Location">
        <SelectValue placeholder="Choose a location" />
      </SelectTrigger>
      <SelectContent>
        {locations
          .filter((l) => l.is_active)
          .map((l) => (
            <SelectItem key={l.id} value={l.id}>
              {l.name}
            </SelectItem>
          ))}
      </SelectContent>
    </Select>
  );
}

function InviteDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">{open && <InviteForm onOpenChange={onOpenChange} />}</DialogContent>
    </Dialog>
  );
}

function InviteForm({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  const me = useMe();
  const scope = useLocationScope();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("staff");
  const [pickedLocation, setLocationId] = useState<string | null>(null);
  const locationId =
    pickedLocation ??
    (me.role === "manager" ? (me.location_ids[0] ?? "") : (scope.locationId ?? scope.locations.find((l) => l.is_active)?.id ?? ""));
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Invite | null>(null);

  const invite = useMutation({
    mutationFn: () => api.users.invite({ email: email.trim(), role, location_id: role === "owner" ? null : locationId }),
    onSuccess: (result) => {
      setCreated(result);
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => setError(e instanceof ApiError ? errorMessage(e) : "Couldn't send the invitation."),
  });

  const link = created?.token && typeof window !== "undefined" ? `${window.location.origin}/accept-invite?token=${created.token}` : null;

  return (
    <>
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>Invitation created</DialogTitle>
              <DialogDescription>
                {link ? "Email delivery arrives with notifications. For now, share this link with them:" : `An invitation was sent to ${created.email}.`}
              </DialogDescription>
            </DialogHeader>
            {link && (
              <div className="flex gap-2">
                <Input readOnly value={link} aria-label="Invitation link" onFocus={(e) => e.currentTarget.select()} />
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="Copy link"
                  onClick={() => navigator.clipboard.writeText(link).then(() => toast.success("Link copied"))}
                >
                  <Copy className="size-4" />
                </Button>
              </div>
            )}
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Invite someone</DialogTitle>
              <DialogDescription>They&apos;ll choose their own password.</DialogDescription>
            </DialogHeader>
            <form
              className="space-y-4"
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                if (!/^\S+@\S+\.\S+$/.test(email)) return setError("Enter a valid email address.");
                if (role !== "owner" && !locationId) return setError("Choose a location.");
                setError(null);
                invite.mutate();
              }}
            >
              <div className="space-y-1.5">
                <Label htmlFor="invite-email">Email</Label>
                <Input id="invite-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>Role</Label>
                <Select value={role} onValueChange={(v) => setRole(v as Role)}>
                  <SelectTrigger className="w-full" aria-label="Role">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="staff">Staff: their own calendar and bookings</SelectItem>
                    {me.role === "owner" && <SelectItem value="manager">Manager: runs one location</SelectItem>}
                    {me.role === "owner" && <SelectItem value="owner">Owner: everything</SelectItem>}
                  </SelectContent>
                </Select>
              </div>
              {role !== "owner" && me.role === "owner" && (
                <div className="space-y-1.5">
                  <Label>Location</Label>
                  <LocationSelect value={locationId} onChange={setLocationId} />
                </div>
              )}
              {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={invite.isPending}>
                  {invite.isPending ? "Sending…" : "Send invitation"}
                </Button>
              </DialogFooter>
            </form>
          </>
        )}
    </>
  );
}

function EditUserDialog({ user, onClose }: { user: User | null; onClose: () => void }) {
  return (
    <Dialog open={!!user} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">{user && <EditUserForm key={user.id} user={user} onClose={onClose} />}</DialogContent>
    </Dialog>
  );
}

function EditUserForm({ user, onClose }: { user: User; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [role, setRole] = useState<Role>(user.role);
  const [locationId, setLocationId] = useState(user.location_id ?? "");
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => api.users.update(user.id, role === "owner" ? { role, location_id: null } : { role, location_id: locationId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.success("Updated");
      onClose();
    },
    onError: (e) => setError(errorMessage(e)),
  });

  return (
    <>
      <DialogHeader>
        <DialogTitle>{user.full_name}</DialogTitle>
        <DialogDescription>{user.email}</DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label>Role</Label>
          <Select value={role} onValueChange={(v) => setRole(v as Role)}>
            <SelectTrigger className="w-full" aria-label="Role">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="staff">Staff</SelectItem>
              <SelectItem value="manager">Manager</SelectItem>
              <SelectItem value="owner">Owner</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {role !== "owner" && (
          <div className="space-y-1.5">
            <Label>Location</Label>
            <LocationSelect value={locationId} onChange={setLocationId} />
          </div>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          disabled={save.isPending}
          onClick={() => (role !== "owner" && !locationId ? setError("Choose a location.") : save.mutate())}
        >
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </DialogFooter>
    </>
  );
}
