export type AppointmentStatus = "booked" | "pending" | "completed" | "cancelled" | "no_show";

const STYLES: Record<AppointmentStatus, { label: string; className: string }> = {
  booked: {
    label: "Booked",
    className: "bg-(--status-booked-soft) text-(--status-booked)",
  },
  pending: {
    label: "Pending",
    className: "bg-(--status-pending-soft) text-(--status-pending)",
  },
  completed: {
    label: "Completed",
    className: "bg-(--status-completed-soft) text-(--status-completed)",
  },
  cancelled: {
    label: "Cancelled",
    className: "bg-(--status-cancelled-soft) text-(--status-cancelled)",
  },
  no_show: {
    label: "No-show",
    className: "bg-(--status-cancelled-soft) text-(--status-cancelled)",
  },
};

export function StatusBadge({ status }: { status: AppointmentStatus }) {
  const { label, className } = STYLES[status];
  return (
    <span
      data-status={status}
      className={`inline-flex h-6 items-center rounded-full px-2 text-xs font-medium ${className}`}
    >
      {label}
    </span>
  );
}
