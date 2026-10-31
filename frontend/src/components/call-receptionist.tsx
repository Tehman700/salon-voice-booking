"use client";

import { useQueryClient } from "@tanstack/react-query";
import type { Call, Device } from "@twilio/voice-sdk";
import { Mic, MicOff, Phone, PhoneOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { MOCKS_ENABLED } from "@/lib/demo";

type Status = "idle" | "connecting" | "ringing" | "in-call";

const LABEL: Record<Status, string> = {
  idle: "Call the receptionist",
  connecting: "Connecting…",
  ringing: "Ringing…",
  "in-call": "On the call",
};

function clock(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/**
 * Talk to the AI receptionist from the browser: Twilio connects the call to the salon's line,
 * exactly as if a customer had dialled it. The call and any booking show up here afterwards.
 */
export function CallReceptionist() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>("idle");
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const device = useRef<Device | null>(null);
  const call = useRef<Call | null>(null);

  useEffect(() => {
    if (status !== "in-call") return;
    const timer = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(timer);
  }, [status]);

  // Hang up and release the microphone if the page is left mid-call.
  useEffect(() => () => device.current?.destroy(), []);

  if (MOCKS_ENABLED) return null; // sample data only: there is no line to call

  function finished() {
    setStatus("idle");
    setMuted(false);
    call.current = null;
    device.current?.destroy();
    device.current = null;
    // The call log and any booking are written by webhooks a moment after hang-up.
    window.setTimeout(() => {
      for (const key of ["calls", "call-stats", "bookings"]) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
    }, 4000);
  }

  async function start() {
    setStatus("connecting");
    setSeconds(0);
    try {
      const [{ token }, { Device }] = await Promise.all([api.twilio.token(), import("@twilio/voice-sdk")]);
      const phone = new Device(token, { closeProtection: true });
      device.current = phone;
      const active = await phone.connect();
      call.current = active;
      active.on("ringing", () => setStatus("ringing"));
      active.on("accept", () => setStatus("in-call"));
      active.on("disconnect", finished);
      active.on("cancel", finished);
      active.on("reject", finished);
      active.on("error", (error: { message?: string }) => {
        toast.error(`The call dropped: ${error.message ?? "unknown error"}`);
        finished();
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 503) {
        toast.error("Browser calling isn't set up on the server yet.");
      } else if (error instanceof DOMException && error.name === "NotAllowedError") {
        toast.error("Allow microphone access to talk to the receptionist.");
      } else {
        toast.error(error instanceof Error ? error.message : "Couldn't start the call.");
      }
      finished();
    }
  }

  function toggleMute() {
    if (!call.current) return;
    call.current.mute(!muted);
    setMuted(!muted);
  }

  if (status === "idle") {
    return (
      <Button onClick={start}>
        <Phone aria-hidden className="size-4" />
        {LABEL.idle}
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-2" role="status" aria-live="polite">
      <span className="font-mono text-xs text-muted-foreground">
        {status === "in-call" ? `${LABEL[status]} · ${clock(seconds)}` : LABEL[status]}
      </span>
      <Button
        variant="outline"
        size="icon"
        onClick={toggleMute}
        disabled={status !== "in-call"}
        aria-label={muted ? "Unmute" : "Mute"}
        aria-pressed={muted}
      >
        {muted ? <MicOff aria-hidden className="size-4" /> : <Mic aria-hidden className="size-4" />}
      </Button>
      <Button variant="destructive" onClick={() => (call.current ? call.current.disconnect() : finished())}>
        <PhoneOff aria-hidden className="size-4" />
        Hang up
      </Button>
    </div>
  );
}
