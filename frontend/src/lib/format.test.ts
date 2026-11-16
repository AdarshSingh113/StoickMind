import { describe, expect, it } from "vitest";
import { delta, dayLabel, inr, inrCompact, initials, pct, relativeTime } from "./format";

describe("Indian number formatting", () => {
  it("groups in lakh and crore", () => {
    expect(inr(439774)).toBe("₹4,39,774");
    expect(inr(12345678)).toBe("₹1,23,45,678");
    expect(inr(-54321.4)).toBe("-₹54,321");
    expect(inr(null)).toBe("–");
  });
  it("compacts for cards and axes", () => {
    expect(inrCompact(439774)).toBe("₹4.4 L");
    expect(inrCompact(12345678)).toBe("₹1.2 Cr");
    expect(inrCompact(45300)).toBe("₹45.3 K");
    expect(inrCompact(100000)).toBe("₹1 L");
    expect(inrCompact(853)).toBe("₹853");
  });
  it("formats percentages and deltas", () => {
    expect(pct(0.2112)).toBe("21.1%");
    expect(pct(0.5)).toBe("50%");
    expect(delta(0.248)).toBe("+24.8%");
    expect(delta(-0.03)).toBe("−3%");
  });
});

describe("time", () => {
  const now = new Date("2026-11-15T12:00:00");
  it("is relative for recent messages", () => {
    expect(relativeTime("2026-11-15 11:59:50", now)).toBe("just now");
    expect(relativeTime("2026-11-15 11:30:00", now)).toBe("30m");
    expect(relativeTime("2026-11-15 07:00:00", now)).toBe("5h");
    expect(relativeTime("2026-11-13 12:00:00", now)).toBe("2d");
  });
  it("labels days", () => {
    expect(dayLabel("2026-11-15 08:00:00", now)).toBe("Today");
    expect(dayLabel("2026-11-14 23:00:00", now)).toBe("Yesterday");
  });
});

it("makes initials", () => {
  expect(initials("Priya Sharma")).toBe("PS");
  expect(initials(null)).toBe("?");
});

describe("ago", async () => {
  const { ago, langLabel } = await import("./format");
  const now = new Date("2026-11-15T12:00:00");
  it("never says '22 Nov ago'", () => {
    expect(ago("2026-11-15 11:30:00", now)).toBe("30m ago");
    expect(ago("2026-11-12 12:00:00", now)).toBe("3d ago");
    expect(ago("2025-11-22 10:00:00", now)).toBe("on 22 Nov 2025");
    expect(ago(null, now)).toBe("");
  });
  it("labels languages", () => {
    expect(langLabel("hi")).toBe("Hindi");
    expect(langLabel("hinglish")).toBe("Hinglish");
  });
});
