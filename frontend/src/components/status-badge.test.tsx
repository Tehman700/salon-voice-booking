import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type AppointmentStatus, StatusBadge } from "./status-badge";

describe("StatusBadge", () => {
  it.each<[AppointmentStatus, string]>([
    ["booked", "Booked"],
    ["pending", "Pending"],
    ["completed", "Completed"],
    ["cancelled", "Cancelled"],
    ["no_show", "No-show"],
  ])("renders %s as %s", (status, label) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(label);
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("data-status", status);
  });

  it("uses the status color tokens", () => {
    render(<StatusBadge status="cancelled" />);
    expect(screen.getByText("Cancelled").className).toContain("--status-cancelled");
  });
});
