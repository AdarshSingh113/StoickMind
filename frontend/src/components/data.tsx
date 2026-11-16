import { CircleAlert, KeyRound } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Card } from "./ui/card";

type Tone = "good" | "primary" | "bad" | "neutral" | "warn" | "outline";
const STATUS: Record<string, Tone> = {
  delivered: "good", resolved: "good", done: "good", approved: "good", measured: "good", live: "good", ok: "good",
  shipped: "primary", out_for_delivery: "primary", placed: "primary", open: "primary", sent: "primary",
  rto: "bad", escalated: "bad", rejected: "bad", error: "bad", fail_safe: "bad", high: "bad",
  returned: "warn", pending_approval: "warn", corrected: "warn", medium: "warn", fallback: "warn", draft: "neutral",
  cancelled: "neutral", low: "neutral",
};
const LABEL: Record<string, string> = { rto: "RTO (refused)", pending_approval: "Needs approval", fail_safe: "Fail-safe",
  out_for_delivery: "Out for delivery" };

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  return <Badge tone={STATUS[value] ?? "neutral"}>{LABEL[value] ?? titleCase(value)}</Badge>;
}

export function Stat({ label, value, hint, className }: { label: string; value: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <Card className={cn("p-4", className)}>
      <div className="text-[12.5px] text-muted-foreground">{label}</div>
      <div className="mt-1 font-display text-[24px] font-extrabold tracking-tight tabular">{value}</div>
      {hint && <div className="mt-0.5 text-[12px] text-subtle-foreground">{hint}</div>}
    </Card>
  );
}

/** Shows API errors helpfully. 503 = the AI key isn't configured: explain instead of looking broken. */
export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as Error;
  if (e instanceof ApiError && e.status === 503) {
    return (
      <div className="flex gap-3 rounded-2xl border border-warning/30 bg-warning-soft p-4 text-[13.5px] text-warning">
        <KeyRound className="mt-0.5 size-4 shrink-0" />
        <div><b>AI isn't configured on the server.</b> Add a free Gemini key as <code>GEMINI_API_KEY</code> (see README).
          Everything else keeps working without it.</div>
      </div>
    );
  }
  return (
    <div className="flex gap-3 rounded-2xl border border-danger/30 bg-danger-soft p-4 text-[13.5px] text-danger">
      <CircleAlert className="mt-0.5 size-4 shrink-0" />{e.message}
    </div>
  );
}

export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return <th className={cn("px-4 py-2.5 text-left text-[12px] font-semibold text-muted-foreground", className)}>{children}</th>;
}
export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cn("px-4 py-3", className)}>{children}</td>;
}
