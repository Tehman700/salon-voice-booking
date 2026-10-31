import type { BookingSource, CallOutcome } from "@/lib/api";

export const OUTCOME_LABEL: Record<CallOutcome, string> = {
  booked: "Booked",
  rescheduled: "Rescheduled",
  cancelled: "Cancelled",
  info_only: "Info only",
  failed: "Failed",
  abandoned: "Abandoned",
};

const OUTCOME_STYLE: Record<CallOutcome, string> = {
  booked: "bg-(--status-booked-soft) text-(--status-booked)",
  rescheduled: "bg-(--status-voice-soft) text-(--status-voice)",
  cancelled: "bg-(--status-cancelled-soft) text-(--status-cancelled)",
  info_only: "bg-(--status-completed-soft) text-(--status-completed)",
  failed: "bg-(--status-cancelled-soft) text-(--status-cancelled)",
  abandoned: "bg-(--status-pending-soft) text-(--status-pending)",
};

export const OUTCOME_BAR: Record<CallOutcome, string> = {
  booked: "var(--status-booked)",
  rescheduled: "var(--status-voice)",
  cancelled: "var(--status-cancelled)",
  info_only: "var(--hairline-strong)",
  failed: "var(--status-cancelled)",
  abandoned: "var(--status-pending)",
};

export function OutcomeBadge({ outcome }: { outcome: CallOutcome }) {
  return (
    <span
      data-outcome={outcome}
      className={`inline-flex h-6 items-center rounded-full px-2 text-xs font-medium ${OUTCOME_STYLE[outcome]}`}
    >
      {OUTCOME_LABEL[outcome]}
    </span>
  );
}

export function SourceBadge({ source }: { source: BookingSource }) {
  const voice = source === "voice";
  return (
    <span
      className={`inline-flex h-6 items-center rounded-full px-2 text-xs font-medium ${
        voice ? "bg-(--status-voice-soft) text-(--status-voice)" : "bg-secondary text-muted-foreground"
      }`}
    >
      {voice ? "Voice" : "Dashboard"}
    </span>
  );
}
