import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, CircleCheck, Search, ShieldCheck, Sparkles, Ticket, Wrench, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { ErrorNote, Stat, StatusBadge } from "@/components/data";
import { EmptyState, PageHeader } from "@/components/empty";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { get, post, qs } from "@/lib/api";
import { inr, num, pct, relativeTime, ago, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

type TicketRow = { id: number; created_at: string; customer: string; channel: string; category: string; priority: string; status: string;
  message: string; order_number: string | null; resolved_by: string | null; hours_to_resolve: number | null };
type HelpResp = { tickets: TicketRow[]; counts: Record<string, number>; pending_approvals: number;
  summary: { avg_hours: number; ai_share: number }; ai: { runs: number; resolved_rate: number; escalated_rate: number; actions: number } };
type Line = { role: string; content: string | null; tool_name: string | null; tool_args: string | null };
type TicketDetail = { ticket: TicketRow & { customer_id: number; order_status: string | null; order_total: number | null; payment_method: string | null };
  runs: { id: number; outcome: string; actions: number; latency_ms: number; created_at: string }[]; transcript: Line[] };
type Approval = { id: number; action: string; amount: number | null; reason: string | null; details: Record<string, unknown>; created_at: string;
  agent_slug: string; order_number: string | null; payment_method: string | null; customer: string | null };

export function Helpdesk() {
  const [tab, setTab] = useState<"tickets" | "approvals">("tickets");
  const [status, setStatus] = useState("open");
  const [q, setQ] = useState(""); const [debounced, setDebounced] = useState("");
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 250); return () => clearTimeout(t); }, [q]);
  const [sel, setSel] = useState<number | null>(null);
  const data = useQuery({ queryKey: ["helpdesk", status, debounced], placeholderData: keepPreviousData,
    queryFn: () => get<HelpResp>(`/api/v1/helpdesk${qs({ status: status === "all" ? null : status, q: debounced })}`) });
  const d = data.data;
  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6 lg:p-8">
      <PageHeader title="Helpdesk" description="Asha, the AI copilot, works the ticket queue within your policy limits. Anything above a limit waits for you."
        actions={<Segmented value={tab} onChange={setTab} options={[{ value: "tickets", label: "Tickets", count: d?.counts.open },
          { value: "approvals", label: "Approvals", count: d?.pending_approvals }]} />} />
      {data.isError && <ErrorNote error={data.error} />}
      <div className="mb-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {!d ? [1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-[100px] rounded-2xl" />) : <>
          <Stat label="Open tickets" value={num(d.counts.open)} hint={`${num(d.counts.escalated)} escalated`} />
          <Stat label="Avg resolution" value={`${d.summary.avg_hours.toFixed(0)} h`} hint="all resolved tickets" />
          <Stat label="AI copilot runs" value={num(d.ai.runs)} hint={d.ai.runs ? `${pct(d.ai.resolved_rate, 0)} resolved · ${pct(d.ai.escalated_rate, 0)} escalated` : "run it on a ticket"} />
          <Stat label="Waiting for approval" value={num(d.pending_approvals)} hint="refunds / replacements above limits" />
        </>}
      </div>
      {tab === "approvals" ? <Approvals /> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <Card className="overflow-hidden">
            <div className="space-y-3 border-b p-3">
              <Segmented className="w-full [&>button]:flex-1 [&>button]:justify-center" value={status} onChange={(v) => { setStatus(v); setSel(null); }}
                options={[{ value: "open", label: "Open", count: d?.counts.open }, { value: "escalated", label: "Escalated", count: d?.counts.escalated },
                  { value: "resolved", label: "Resolved" }, { value: "all", label: "All" }]} />
              <div className="relative"><Search className="pointer-events-none absolute top-2.5 left-3.5 size-4 text-subtle-foreground" />
                <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search message or customer" className="pl-10" /></div>
            </div>
            <div className="max-h-[620px] divide-y overflow-y-auto scroll-thin">
              {d?.tickets.length === 0 && <EmptyState icon={CircleCheck} title="Nothing here" body="No tickets match." />}
              {d?.tickets.map((t) => (
                <button key={t.id} onClick={() => setSel(t.id)} className={cn("block w-full cursor-pointer px-4 py-3 text-left hover:bg-muted/50", sel === t.id && "bg-primary-soft/70")}>
                  <div className="flex items-center gap-2 text-[13px]"><span className="font-semibold">{t.customer}</span><span className="text-muted-foreground">· {titleCase(t.category)}</span>
                    <span className="ml-auto text-[11.5px] text-subtle-foreground">{relativeTime(t.created_at)}</span></div>
                  <p className="mt-0.5 line-clamp-2 text-[12.5px] text-muted-foreground">{t.message}</p>
                  <div className="mt-1.5 flex gap-1.5"><StatusBadge value={t.status} /><StatusBadge value={t.priority} />{t.resolved_by === "ai" && <Badge tone="primary"><Bot />AI</Badge>}</div>
                </button>))}
            </div>
          </Card>
          <Card className="p-5">{sel ? <TicketPanel id={sel} /> : <EmptyState icon={Ticket} title="Pick a ticket" body="Read it, or let the AI copilot handle it: it checks the order, the policy and your limits." />}</Card>
        </div>)}
    </div>
  );
}

function Transcript({ lines }: { lines: Line[] }) {
  return (
    <div className="space-y-2">{lines.map((l, i) => l.role === "tool" ? (
      <details key={i} className="rounded-xl border border-dashed px-3 py-2 text-[12px]"><summary className="cursor-pointer text-muted-foreground"><Wrench className="mr-1 inline size-3.5" />{l.tool_name}</summary>
        <pre className="mt-2 overflow-x-auto text-[11.5px] whitespace-pre-wrap">{l.tool_args}{"\n→ "}{l.content}</pre></details>
    ) : (
      <div key={i} className={cn("flex", l.role === "user" ? "justify-start" : "justify-end")}>
        <div className={cn("max-w-[85%] rounded-2xl px-3.5 py-2 text-[13.5px] whitespace-pre-wrap", l.role === "user" ? "rounded-bl-md border bg-card" : "rounded-br-md bg-primary-soft")}>{l.content}</div>
      </div>))}</div>
  );
}

function TicketPanel({ id }: { id: number }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ticket", id], queryFn: () => get<TicketDetail>(`/api/v1/helpdesk/tickets/${id}`) });
  const run = useMutation({ meta: { inlineError: true }, mutationFn: () => post<{ outcome: string; transcript: Line[]; guard: string[] }>(`/api/v1/helpdesk/tickets/${id}/ai`),
    onSuccess: (r) => { toast.success(r.outcome === "resolved" ? "The AI resolved this ticket." : r.outcome === "escalated" ? "The AI escalated this to a person." : "The AI couldn't finish."); qc.invalidateQueries({ queryKey: ["ticket", id] }); qc.invalidateQueries({ queryKey: ["helpdesk"] }); } });
  if (!q.data) return <Skeleton className="h-64" />;
  const { ticket: t } = q.data;
  const transcript = run.data?.transcript ?? q.data.transcript;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-3">
        <div><h3 className="text-[17px] font-bold">{titleCase(t.category)} · #{t.id}</h3>
          <p className="text-[12.5px] text-muted-foreground"><Link to={`/app/customers/${t.customer_id}`} className="font-medium text-foreground hover:text-primary">{t.customer}</Link> · {titleCase(t.channel)} · {ago(t.created_at)}</p></div>
        <div className="ml-auto flex gap-1.5"><StatusBadge value={t.status} /><StatusBadge value={t.priority} /></div>
      </div>
      <div className="rounded-2xl bg-muted p-4 text-[14px]">{t.message}</div>
      {t.order_number && <div className="flex flex-wrap gap-2 text-[13px]"><Badge tone="outline">{t.order_number}</Badge><StatusBadge value={t.order_status} /><span className="text-muted-foreground">{inr(t.order_total)} · {t.payment_method?.toUpperCase()}</span></div>}
      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-primary/25 bg-primary-soft/50 p-3">
        <Sparkles className="size-4 text-primary" /><span className="flex-1 text-[13px]">Let Asha handle it: she verifies the order, searches the policy and acts within limits.</span>
        <Button size="sm" variant="primary" onClick={() => run.mutate()} disabled={run.isPending}><Bot />{run.isPending ? "Working…" : q.data.runs.length ? "Run again" : "Let AI handle it"}</Button>
      </div>
      {run.isError && <ErrorNote error={run.error} />}
      {run.data?.guard?.length ? <p className="text-[12px] text-warning"><ShieldCheck className="mr-1 inline size-3.5" />Safety checks stepped in: {run.data.guard.join("; ")}</p> : null}
      {q.data.runs.length > 0 && <div className="flex flex-wrap gap-2 text-[12px] text-muted-foreground">{q.data.runs.slice(0, 3).map((r) => <span key={r.id}>AI run {ago(r.created_at)}: <StatusBadge value={r.outcome} /> · {r.actions} actions · {(r.latency_ms / 1000).toFixed(1)}s</span>)}</div>}
      {transcript.length > 0 && <div><div className="mb-2 text-[12px] font-semibold tracking-wide text-muted-foreground uppercase">Latest AI conversation</div><Transcript lines={transcript} /></div>}
    </div>
  );
}

function Approvals() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["approvals"], queryFn: () => get<{ approvals: Approval[] }>("/api/v1/helpdesk/approvals") });
  const decide = useMutation({ mutationFn: ({ id, approve }: { id: number; approve: boolean }) => post(`/api/v1/helpdesk/approvals/${id}`, { approve }),
    onSuccess: (_, v) => { toast.success(v.approve ? "Approved." : "Rejected."); qc.invalidateQueries({ queryKey: ["approvals"] }); qc.invalidateQueries({ queryKey: ["helpdesk"] }); } });
  if (!q.data) return <Skeleton className="h-48 rounded-2xl" />;
  if (!q.data.approvals.length) return <Card><EmptyState icon={ShieldCheck} title="Nothing waiting for approval" body="When the AI wants to refund or replace above its limit, or escalates, it lands here for a person to decide." /></Card>;
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{q.data.approvals.map((a) => (
      <Card key={a.id} className="flex flex-col p-5">
        <div className="flex items-center gap-2"><Badge tone="warn">{titleCase(a.action)}</Badge><span className="ml-auto text-[12px] text-muted-foreground">{ago(a.created_at)}</span></div>
        {a.amount != null && <div className="mt-3 font-display text-[28px] font-extrabold tabular">{inr(a.amount)}</div>}
        <div className="mt-1 text-[13px]"><b>{a.customer ?? "Guest"}</b>{a.order_number && <span className="text-muted-foreground"> · {a.order_number} · {a.payment_method?.toUpperCase()}</span>}</div>
        {a.reason && <p className="mt-2 flex-1 text-[13px] text-muted-foreground">{a.reason}</p>}
        <div className="mt-4 flex gap-2"><Button variant="primary" className="flex-1" onClick={() => decide.mutate({ id: a.id, approve: true })} disabled={decide.isPending}><Check />{a.action === "escalation" ? "Resolve" : "Approve"}</Button>
          <Button className="flex-1" onClick={() => decide.mutate({ id: a.id, approve: false })} disabled={decide.isPending}><X />Reject</Button></div>
      </Card>))}</div>
  );
}
