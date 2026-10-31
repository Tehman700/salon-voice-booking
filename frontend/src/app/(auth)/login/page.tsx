"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/lib/auth";
import { DEMO_LOGINS } from "@/lib/demo";
import { errorMessage } from "@/lib/hooks";

export default function LoginPage() {
  const { status, user, login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (status === "authenticated" && user) router.replace(user.role === "staff" ? "/calendar" : "/");
  }, [status, user, router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setSubmitting(true);
    try {
      const me = await login({ email: email.trim(), password });
      router.replace(me.role === "staff" ? "/calendar" : "/");
    } catch (e) {
      setError(errorMessage(e));
      setSubmitting(false);
    }
  }

  return (
    <Card className="shadow-lg">
      <CardHeader>
        <p className="font-mono text-xs uppercase text-muted-foreground">Salon Voice</p>
        <CardTitle className="text-2xl tracking-[-0.96px]">Sign in.</CardTitle>
        <CardDescription>Manage bookings, staff and your AI receptionist.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        {DEMO_LOGINS.length > 0 && (
          <div className="space-y-2 border-t pt-4">
            <p className="font-mono text-xs uppercase text-muted-foreground">Demo accounts</p>
            <div className="flex flex-wrap gap-2">
              {DEMO_LOGINS.map((demo) => (
                <Button
                  key={demo.email}
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setEmail(demo.email);
                    setPassword(demo.password);
                    setError(null);
                  }}
                >
                  {demo.label}
                </Button>
              ))}
            </div>
          </div>
        )}

        <p className="text-center text-sm text-muted-foreground">
          New salon?{" "}
          <Link href="/signup" className="font-medium text-foreground underline underline-offset-4">
            Create an account
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
