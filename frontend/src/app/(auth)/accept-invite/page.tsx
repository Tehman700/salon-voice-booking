"use client";

import { useRouter } from "next/navigation";
import { Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/hooks";
import { useSearchParams } from "next/navigation";

function AcceptInviteForm() {
  const token = useSearchParams().get("token") ?? "";
  const { reload } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return setError("Enter your name.");
    if (password.length < 10) return setError("Use at least 10 characters for your password.");
    setError(null);
    setSubmitting(true);
    try {
      const { user } = await api.auth.acceptInvite({ token, full_name: name.trim(), password });
      await reload();
      router.replace(user.role === "staff" ? "/calendar" : "/");
    } catch (e) {
      setError(errorMessage(e));
      setSubmitting(false);
    }
  }

  return (
    <Card className="shadow-lg">
      <CardHeader>
        <p className="font-mono text-xs uppercase text-muted-foreground">Salon Voice</p>
        <CardTitle className="text-2xl tracking-[-0.96px]">Join your team.</CardTitle>
        <CardDescription>Choose a password to finish setting up your account.</CardDescription>
      </CardHeader>
      <CardContent>
        {!token ? (
          <p role="alert" className="text-sm text-destructive">
            This invitation link is incomplete. Ask for a new one.
          </p>
        ) : (
          <form onSubmit={submit} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="invite-name">Your name</Label>
              <Input id="invite-name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="invite-password">Password</Label>
              <Input id="invite-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              <p className="text-xs text-muted-foreground">At least 10 characters</p>
            </div>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Creating account…" : "Create my account"}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={null}>
      <AcceptInviteForm />
    </Suspense>
  );
}
