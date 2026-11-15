/** Number formatting the Indian way: lakh (1,00,000) and crore (1,00,00,000), not million. */

const grouped = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function inr(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "–";
  return (value < 0 ? "-₹" : "₹") + grouped.format(Math.abs(value));
}

/** ₹4.4 L, ₹1.2 Cr, ₹45.3 K: short enough for a KPI card or a chart axis. */
export function inrCompact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "–";
  const sign = value < 0 ? "-₹" : "₹";
  const v = Math.abs(value);
  const short = (n: number, unit: string) => `${sign}${trim(n)} ${unit}`;
  if (v >= 1e7) return short(v / 1e7, "Cr");
  if (v >= 1e5) return short(v / 1e5, "L");
  if (v >= 1e3) return short(v / 1e3, "K");
  return sign + grouped.format(v);
}

function trim(n: number): string {
  return n >= 100 ? n.toFixed(0) : n.toFixed(1).replace(/\.0$/, "");
}

export function num(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? "–" : grouped.format(value);
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "–";
  return `${(value * 100).toFixed(digits).replace(/\.0$/, "")}%`;
}

/** "+12.4%" / "−3%" for period-over-period changes. */
export function delta(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "–";
  const s = Math.abs(value * 100).toFixed(1).replace(/\.0$/, "");
  return `${value >= 0 ? "+" : "−"}${s}%`;
}

/** Timestamps from the API are local "YYYY-MM-DD HH:MM:SS". */
export function parseTs(ts: string): Date {
  return new Date(ts.replace(" ", "T"));
}

export function relativeTime(ts: string | null | undefined, now: Date = new Date()): string {
  if (!ts) return "";
  const s = Math.round((now.getTime() - parseTs(ts).getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  if (s < 7 * 86400) return `${Math.round(s / 86400)}d`;
  return parseTs(ts).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function clock(ts: string): string {
  return parseTs(ts).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

export function dayLabel(ts: string, now: Date = new Date()): string {
  const d = parseTs(ts);
  const days = Math.floor((startOfDay(now) - startOfDay(d)) / 86400000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function shortDate(day: string): string {
  return new Date(day + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function monthLabel(month: string): string {
  return new Date(month + "-01T00:00:00").toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
