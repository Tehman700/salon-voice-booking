import { StatusBadge } from "@/components/status-badge";

// Placeholder until the dashboard shell lands in M8.
export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-6 px-4 py-16 sm:px-6">
      <p className="font-mono text-xs uppercase text-body">Salon Voice</p>
      <h1 className="text-3xl font-semibold tracking-[-1.28px] text-ink sm:text-5xl sm:tracking-[-2.4px]">
        Your salon&apos;s receptionist, always on.
      </h1>
      <p className="max-w-xl text-lg text-body">
        An AI voice agent that answers questions and books, reschedules, and cancels
        appointments, with a dashboard for your whole team.
      </p>
      <div className="flex flex-wrap gap-2" aria-label="Appointment statuses">
        <StatusBadge status="booked" />
        <StatusBadge status="pending" />
        <StatusBadge status="completed" />
        <StatusBadge status="cancelled" />
      </div>
    </main>
  );
}
