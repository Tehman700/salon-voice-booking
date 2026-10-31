import { describe, expect, it } from "vitest";

import {
  addDays,
  dateKey,
  formatDuration,
  formatMoney,
  formatTime,
  formatWindow,
  initials,
  zonedToIso,
} from "./format";

describe("formatting", () => {
  it("formats prices from minor units", () => {
    expect(formatMoney(250_000, "PKR")).toMatch(/2,500/);
    expect(formatMoney(0, "PKR")).toMatch(/0/);
  });

  it("describes durations", () => {
    expect(formatDuration(45)).toBe("45 min");
    expect(formatDuration(60)).toBe("1 h");
    expect(formatDuration(90)).toBe("1 h 30 min");
  });

  it("describes cancellation windows", () => {
    expect(formatWindow(0)).toBe("No notice needed");
    expect(formatWindow(30)).toBe("30 minutes");
    expect(formatWindow(60)).toBe("1 hour");
    expect(formatWindow(120)).toBe("2 hours");
    expect(formatWindow(1440)).toBe("1 day");
    expect(formatWindow(2880)).toBe("2 days");
  });

  it("makes initials", () => {
    expect(initials("Olivia Owner")).toBe("OO");
    expect(initials("sana")).toBe("S");
    expect(initials("  ")).toBe("");
  });
});

describe("dates are read in the salon's timezone, not the browser's", () => {
  // 22:30 UTC on the 3rd is already the 4th in Karachi (UTC+5) but still the 3rd in London (UTC+0).
  const instant = "2026-11-03T22:30:00Z";

  it("rolls the calendar day over per timezone", () => {
    expect(dateKey(instant, "Asia/Karachi")).toBe("2026-11-04");
    expect(dateKey(instant, "Europe/London")).toBe("2026-11-03");
  });

  it("shows the local clock time", () => {
    expect(formatTime(instant, "Asia/Karachi")).toMatch(/3:30/);
    expect(formatTime(instant, "Europe/London")).toMatch(/10:30/);
  });

  it("adds days across month and year ends", () => {
    expect(addDays("2026-11-30", 1)).toBe("2026-12-01");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
  });
});

describe("zonedToIso", () => {
  it("converts a wall-clock time to UTC", () => {
    expect(zonedToIso("2026-11-03", "09:00", "Asia/Karachi")).toBe("2026-11-03T04:00:00Z");
    expect(zonedToIso("2026-11-03", "00:00", "Asia/Karachi")).toBe("2026-11-02T19:00:00Z");
  });

  it("follows daylight saving time", () => {
    // London is UTC+0 in winter and UTC+1 in summer.
    expect(zonedToIso("2026-01-15", "12:00", "Europe/London")).toBe("2026-01-15T12:00:00Z");
    expect(zonedToIso("2026-07-15", "12:00", "Europe/London")).toBe("2026-07-15T11:00:00Z");
  });

  it("round-trips through dateKey", () => {
    const iso = zonedToIso("2026-11-03", "23:30", "Asia/Karachi");
    expect(dateKey(iso, "Asia/Karachi")).toBe("2026-11-03");
  });
});
