"use client";

import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ApiError, type LocationInput, type LocationMode } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/hooks";

const TIMEZONES = [
  ["Asia/Karachi", "Pakistan (Karachi)"],
  ["Asia/Dubai", "UAE (Dubai)"],
  ["Asia/Kolkata", "India (Kolkata)"],
  ["Europe/London", "United Kingdom (London)"],
  ["America/New_York", "US East (New York)"],
  ["America/Los_Angeles", "US West (Los Angeles)"],
] as const;

type Draft = { name: string; timezone: string; phone: string };
const blank = (): Draft => ({ name: "", timezone: "Asia/Karachi", phone: "" });

export default function SignupPage() {
  const { signup } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState<1 | 2>(1);
  const [businessName, setBusinessName] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<LocationMode>("single");
  const [locations, setLocations] = useState<Draft[]>([blank()]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function validateStep1() {
    const next: Record<string, string> = {};
    if (!businessName.trim()) next.businessName = "Enter your business name";
    if (!ownerName.trim()) next.ownerName = "Enter your name";
    if (!/^\S+@\S+\.\S+$/.test(email)) next.email = "Enter a valid email";
    if (password.length < 10) next.password = "Use at least 10 characters";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  function chooseMode(next: LocationMode) {
    setMode(next);
    setLocations((current) => (next === "single" ? current.slice(0, 1) : current));
  }

  function update(index: number, patch: Partial<Draft>) {
    setLocations((current) => current.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    locations.forEach((l, i) => {
      if (!l.name.trim()) next[`location-${i}`] = "Name this salon";
      if (l.phone.trim() && !/^\+[1-9]\d{6,14}$/.test(l.phone.trim())) next[`phone-${i}`] = "Use international format, e.g. +923001234567";
    });
    setErrors(next);
    if (Object.keys(next).length) return;

    setSubmitting(true);
    setFormError(null);
    try {
      await signup({
        business_name: businessName.trim(),
        owner_full_name: ownerName.trim(),
        email: email.trim(),
        password,
        location_mode: mode,
        locations: locations.map<LocationInput>((l) => ({
          name: l.name.trim(),
          timezone: l.timezone,
          ...(l.phone.trim() ? { phone: l.phone.trim() } : {}),
        })),
      });
      router.replace("/");
    } catch (e) {
      if (e instanceof ApiError && e.code === "email_taken") {
        setStep(1);
        setErrors({ email: "An account with this email already exists" });
      } else {
        setFormError(errorMessage(e));
      }
      setSubmitting(false);
    }
  }

  return (
    <Card className="shadow-lg">
      <CardHeader>
        <p className="font-mono text-xs uppercase text-muted-foreground">Step {step} of 2</p>
        <CardTitle className="text-2xl tracking-[-0.96px]">{step === 1 ? "Create your account." : "Your salons."}</CardTitle>
        <CardDescription>
          {step === 1 ? "Start with you and your business." : "One salon or several? You can add more later."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {step === 1 ? (
          <form
            className="space-y-4"
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              if (validateStep1()) setStep(2);
            }}
          >
            <Field label="Business name" id="business" error={errors.businessName}>
              <Input id="business" value={businessName} onChange={(e) => setBusinessName(e.target.value)} />
            </Field>
            <Field label="Your name" id="owner" error={errors.ownerName}>
              <Input id="owner" autoComplete="name" value={ownerName} onChange={(e) => setOwnerName(e.target.value)} />
            </Field>
            <Field label="Email" id="signup-email" error={errors.email}>
              <Input id="signup-email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Password" id="signup-password" error={errors.password} hint="At least 10 characters">
              <Input id="signup-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Button type="submit" className="w-full">
              Continue
            </Button>
          </form>
        ) : (
          <form onSubmit={submit} className="space-y-5" noValidate>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">How many salons do you run?</legend>
              <div className="grid grid-cols-2 gap-2" role="radiogroup">
                {(
                  [
                    ["single", "Just one"],
                    ["multiple", "More than one"],
                  ] as const
                ).map(([value, label]) => (
                  <Button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={mode === value}
                    variant={mode === value ? "default" : "outline"}
                    onClick={() => chooseMode(value)}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            </fieldset>

            <div className="space-y-4">
              {locations.map((l, i) => (
                <div key={i} className="space-y-3 rounded-lg border bg-card p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs uppercase text-muted-foreground">
                      {mode === "single" ? "Your salon" : `Salon ${i + 1}`}
                    </span>
                    {locations.length > 1 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Remove salon ${i + 1}`}
                        onClick={() => setLocations((c) => c.filter((_, idx) => idx !== i))}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    )}
                  </div>
                  <Field label="Salon name" id={`loc-name-${i}`} error={errors[`location-${i}`]}>
                    <Input id={`loc-name-${i}`} placeholder="e.g. Gulberg" value={l.name} onChange={(e) => update(i, { name: e.target.value })} />
                  </Field>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label>Timezone</Label>
                      <Select value={l.timezone} onValueChange={(v) => update(i, { timezone: v })}>
                        <SelectTrigger className="w-full" aria-label={`Timezone for salon ${i + 1}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {TIMEZONES.map(([value, label]) => (
                            <SelectItem key={value} value={value}>
                              {label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <Field label="Phone (optional)" id={`loc-phone-${i}`} error={errors[`phone-${i}`]}>
                      <Input id={`loc-phone-${i}`} type="tel" placeholder="+923001234567" value={l.phone} onChange={(e) => update(i, { phone: e.target.value })} />
                    </Field>
                  </div>
                </div>
              ))}
              {mode === "multiple" && (
                <Button type="button" variant="outline" size="sm" onClick={() => setLocations((c) => [...c, blank()])}>
                  <Plus className="size-4" /> Add another salon
                </Button>
              )}
            </div>

            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => setStep(1)}>
                Back
              </Button>
              <Button type="submit" className="flex-1" disabled={submitting}>
                {submitting ? "Creating…" : "Create account"}
              </Button>
            </div>
          </form>
        )}

        <p className="text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-foreground underline underline-offset-4">
            Sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  id,
  error,
  hint,
  children,
}: {
  label: string;
  id: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? <p className="text-xs text-destructive">{error}</p> : hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
