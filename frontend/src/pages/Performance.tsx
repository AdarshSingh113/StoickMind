import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Activity, Bot, CircleCheck, CircleX, Gauge, IndianRupee, MessagesSquare, ShieldCheck, Timer } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { agentLabel, ChannelIcon, channelLabel } from "@/components/brand";
import { ErrorNote, Stat, StatusBadge, Td, Th } from "@/components/data";
import { EmptyState, PageHeader } from "@/components/empty";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { get, qs, type Channel } from "@/lib/api";
import { inr, num, pct, relativeTime, ago, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

type Perf = {
  summary: { llm_calls: number; tokens: number; cost_inr: number; llm_error_rate: number; fallback_rate: number; agent_turns: number;
    conversations: number; p50_s: number; p95_s: number; guard_rate: number; error_rate: number; escalation_rate: number; cost_per_conversation_inr: number };
  agents: { agent: string; turns: number; conversations: number; p50_s: number; p95_s: number; error_pct: number; guard_pct: number;
    fail_safe_pct: number; escalation_pct: number; tokens_per_turn: number; cost_per_conv_inr: number; judged: number; success_pct: number | null; avg_score: number | null }[];
  daily: { day: string; llm_calls: number; cost_inr: number; errors: number; turns: number; p95_s: number }[];
  cost_by_feature: { feature: string; calls: number; tokens: number; cost_inr: number }[];
  tools: { tool: string; calls: number; error_pct: number; avg_ms: number }[];
  guards: { guard: string; fired: number; last_fired: string }[];
};
const axis = { fontSize: 11.5, fill: "var(--subtle-foreground)" };
type Tab = "conversations" | "agents" | "traces" | "cost" | "evals" | "impact";
type Convs = {
  summary: { conversations: number; automated: number; automation_rate: number | null; handed_over: number; unanswered: number; avg_messages: number; demo: number };
  intents: { intent: string; label: string; conversations: number; share: number; automated_pct: number; handed_over_pct: number; avg_messages: number; example: string }[];
  channels: { channel: Channel; conversations: number; automated_pct: number }[];
  ai_sales: { orders: number; revenue: number; chats_converted: number; chats_shown_products: number; conversion_rate: number | null };
};

export function Performance() {
  const [days, setDays] = useState(30);
  const [tab, setTab] = useState<Tab>("conversations");
  const [includeEval, setIncludeEval] = useState(false);
  const q = useQuery({ queryKey: ["perf", days, includeEval], queryFn: () => get<Perf>(`/api/v1/performance${qs({ days, include_eval: includeEval })}`),
    placeholderData: keepPreviousData });
  const s = q.data?.summary;
  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6 lg:p-8">
      <PageHeader title="AI performance" description="Is the AI fast, safe and good, what does it cost, and what is it worth?"
        actions={<Segmented value={days} onChange={setDays} options={[{ value: 1, label: "24 h" }, { value: 7, label: "7 days" }, { value: 30, label: "30 days" }, { value: 0, label: "All" }]} />} />
      {q.isError && <ErrorNote error={q.error} />}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {!s ? [1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-[106px] rounded-2xl" />) : <>
          <Stat label="Agent replies" value={num(s.agent_turns)} hint={`${num(s.conversations)} conversations`} />
          <Stat label="Reply time p50 / p95" value={`${s.p50_s.toFixed(1)}s / ${s.p95_s.toFixed(1)}s`} hint="median / slowest 5%" />
          <Stat label="Safety checks stepped in" value={pct(s.guard_rate, 0)} hint={`errors ${pct(s.error_rate, 0)} · escalated ${pct(s.escalation_rate, 0)}`} />
          <Stat label="AI cost (est.)" value={inr(s.cost_inr)} hint={`${inr(s.cost_per_conversation_inr)}/conversation · free tier = ₹0`} />
        </>}
      </div>
      <div className="mt-6 mb-4 flex flex-wrap items-center gap-3">
        <Segmented value={tab} onChange={setTab} options={[{ value: "conversations", label: "Conversations" }, { value: "agents", label: "Agents" }, { value: "traces", label: "Traces" },
          { value: "cost", label: "Cost" }, { value: "evals", label: "Evals" }, { value: "impact", label: "Business impact" }]} />
        <label className="ml-auto flex items-center gap-2 text-[13px] text-muted-foreground">
          <input type="checkbox" checked={includeEval} onChange={(e) => setIncludeEval(e.target.checked)} className="accent-[var(--primary)]" />Include eval runs</label>
      </div>
      {tab === "conversations" && <ConversationsTab days={days} />}
      {tab === "agents" && q.data && <AgentsTab d={q.data} />}
      {tab === "traces" && <TracesTab days={days} includeEval={includeEval} />}
      {tab === "cost" && q.data && <CostTab d={q.data} />}
      {tab === "evals" && <EvalsTab />}
      {tab === "impact" && <ImpactTab days={days || 30} />}
    </div>
  );
}

function NoActivity() {
  return <Card><EmptyState icon={Activity} title="No AI activity in this period" body="Chat in the inbox, the agent playground or the demo store: every AI call is traced automatically." /></Card>;
}

/** What customers ask about, and how much of it the AI handles without a person. From the real message log. */
function ConversationsTab({ days }: { days: number }) {
  const q = useQuery({ queryKey: ["perf-convs", days], queryFn: () => get<Convs>(`/api/v1/performance/conversations${qs({ days })}`),
    placeholderData: keepPreviousData });
  if (q.isError) return <ErrorNote error={q.error} />;
  if (!q.data) return <Skeleton className="h-80 rounded-2xl" />;
  const { summary: s, intents, channels, ai_sales: sales } = q.data;
  if (!s.conversations) return <Card><EmptyState icon={MessagesSquare} title="No conversations in this period"
    body="Chat with the Telegram bot or the website widget (or load demo chats in the inbox): every conversation is counted here." /></Card>;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Conversations" value={num(s.conversations)} hint={s.demo ? `${s.demo} of them demo chats` : "from Telegram, WhatsApp and website"} />
        <Stat label="Handled fully by AI" value={s.automation_rate == null ? "–" : pct(s.automation_rate, 0)}
          hint={`${s.automated} by AI · ${s.handed_over} reached a person${s.unanswered ? ` · ${s.unanswered} unanswered` : ""}`} />
        <Stat label="Messages per conversation" value={s.avg_messages.toFixed(1)} hint="customer + replies" />
        <Stat label="Sales from AI chats" value={inr(sales.revenue)}
          hint={`${sales.orders} orders · ${sales.chats_shown_products ? `${sales.chats_converted} of ${sales.chats_shown_products} chats with product cards bought` : "no product cards shown yet"}`} />
      </div>
      <Card>
        <CardHeader title="What customers ask about" description="Each conversation is tagged with its most serious topic (rules, English + Hinglish). Safety topics should reach a person: there, a low AI share is the goal." />
        <div className="overflow-x-auto scroll-thin"><table className="w-full min-w-[640px] text-[13px]">
          <thead className="border-y bg-muted/50"><tr><Th>Topic</Th><Th className="text-right">Conversations</Th><Th className="w-[34%]">Handled fully by AI</Th>
            <Th className="text-right">Reached a person</Th><Th className="text-right">Msgs</Th></tr></thead>
          <tbody className="divide-y">{intents.map((r) => (
            <tr key={r.intent}>
              <Td><div className="font-semibold">{r.label}</div><div className="max-w-[340px] truncate text-[12px] text-muted-foreground" title={r.example}>“{r.example}”</div></Td>
              <Td className="text-right tabular"><b>{r.conversations}</b> <span className="text-muted-foreground">({pct(r.share, 0)})</span></Td>
              <Td><div className="flex items-center gap-2" title={`${Math.round(r.automated_pct * r.conversations / 100)} of ${r.conversations} handled by AI`}>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-[var(--chart-1)]" style={{ width: `${r.automated_pct}%` }} /></div>
                <span className="w-10 text-right font-semibold tabular">{r.automated_pct.toFixed(0)}%</span></div></Td>
              <Td className="text-right tabular">{r.handed_over_pct.toFixed(0)}%{SAFETY.has(r.intent) && r.handed_over_pct === 100 && <ShieldCheck className="ml-1 inline size-3.5 text-success" aria-label="as intended" />}</Td>
              <Td className="text-right tabular text-muted-foreground">{r.avg_messages.toFixed(1)}</Td>
            </tr>))}</tbody></table></div>
      </Card>
      <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted-foreground">
        <span>By channel:</span>
        {channels.map((c) => <span key={c.channel} className="flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-1">
          <ChannelIcon channel={c.channel} className="size-3.5" />{channelLabel(c.channel)} · {c.conversations} · <b className="text-foreground">{c.automated_pct.toFixed(0)}%</b> by AI</span>)}
      </div>
    </div>
  );
}
const SAFETY = new Set(["skin_reaction", "damaged_wrong"]);

function AgentsTab({ d }: { d: Perf }) {
  if (!d.agents.length) return <NoActivity />;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {d.agents.map((a) => (
          <Card key={a.agent} className="p-5">
            <div className="flex items-center gap-3">
              <div className="grid size-10 place-items-center rounded-xl bg-ink text-primary"><Bot className="size-5" /></div>
              <div><div className="font-bold">{agentLabel(a.agent) || a.agent}</div><div className="text-[12px] text-muted-foreground">{num(a.turns)} replies · {num(a.conversations)} chats</div></div>
              {a.success_pct != null && <Badge tone={a.success_pct >= 80 ? "good" : "warn"} className="ml-auto">{a.success_pct.toFixed(0)}% judged success</Badge>}
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-center">
              {[["p95", `${a.p95_s.toFixed(1)}s`, Timer], ["checks", `${a.guard_pct.toFixed(0)}%`, ShieldCheck], ["errors", `${a.error_pct.toFixed(0)}%`, CircleX],
                ["escalated", `${a.escalation_pct.toFixed(0)}%`, Gauge], ["tokens", num(a.tokens_per_turn), Activity], ["₹/chat", a.cost_per_conv_inr.toFixed(2), IndianRupee]].map(([k, v, I]) => {
                const Icon = I as typeof Timer;
                return <div key={k as string} className="rounded-xl bg-muted/60 p-2"><Icon className="mx-auto size-3.5 text-muted-foreground" /><div className="mt-1 text-[14px] font-bold tabular">{v as string}</div><div className="text-[11px] text-muted-foreground">{k as string}</div></div>;
              })}
            </div>
          </Card>))}
      </div>
      {d.daily.length > 1 && (
        <Card><CardHeader title="Replies and slowest-5% reply time per day" />
          <CardBody className="h-60"><ResponsiveContainer>
            <LineChart data={d.daily} margin={{ top: 8, right: 8, bottom: 0, left: -10 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="day" tick={axis} tickLine={false} axisLine={false} minTickGap={24} />
              <YAxis yAxisId="l" tick={axis} tickLine={false} axisLine={false} /><YAxis yAxisId="r" orientation="right" tick={axis} tickLine={false} axisLine={false} />
              <Tooltip /><Line yAxisId="l" dataKey="turns" name="Replies" stroke="var(--chart-1)" strokeWidth={2} dot={false} />
              <Line yAxisId="r" dataKey="p95_s" name="p95 seconds" stroke="var(--chart-2)" strokeWidth={2} dot={false} />
            </LineChart></ResponsiveContainer></CardBody></Card>)}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardHeader title="Tools" description="How often each runs, fails, and how long it takes" />
          <table className="w-full text-[13px]"><thead className="border-y bg-muted/50"><tr><Th>Tool</Th><Th className="text-right">Calls</Th><Th className="text-right">Errors</Th><Th className="text-right">Avg</Th></tr></thead>
            <tbody className="divide-y">{d.tools.map((t) => <tr key={t.tool}><Td className="font-mono text-[12.5px]">{t.tool}</Td><Td className="text-right tabular">{num(t.calls)}</Td>
              <Td className={cn("text-right tabular", t.error_pct > 20 && "text-danger")}>{t.error_pct}%</Td><Td className="text-right tabular">{num(t.avg_ms)} ms</Td></tr>)}</tbody></table></Card>
        <Card><CardHeader title="Safety checks" description="How often each guard had to step in" />
          {d.guards.length ? <table className="w-full text-[13px]"><thead className="border-y bg-muted/50"><tr><Th>Guard</Th><Th className="text-right">Fired</Th><Th>Last</Th></tr></thead>
            <tbody className="divide-y">{d.guards.map((g) => <tr key={g.guard}><Td>{titleCase(g.guard)}</Td><Td className="text-right tabular">{g.fired}</Td><Td className="text-muted-foreground">{ago(g.last_fired)}</Td></tr>)}</tbody></table>
            : <CardBody className="flex items-center gap-2 text-[13px] text-muted-foreground"><CircleCheck className="size-4 text-success" />No guard had to step in.</CardBody>}</Card>
      </div>
    </div>
  );
}

type TraceRow = { id: number; kind: string; name: string | null; channel: string | null; started_at: string; latency_ms: number | null; status: string; escalated: number; input: string | null };
type TraceDetail = { trace: TraceRow & { output: string | null; error: string | null }; meta: Record<string, unknown>;
  llm_calls: { id: number; model: string; latency_ms: number; prompt_tokens: number; completion_tokens: number; tool_calls: number; status: string; created_at: string; cost_inr: number }[];
  spans: { type: string; name: string; latency_ms: number | null; ok: number; detail: string; created_at: string }[] };

function TracesTab({ days, includeEval }: { days: number; includeEval: boolean }) {
  const [kind, setKind] = useState(""); const [status, setStatus] = useState(""); const [q, setQ] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const list = useQuery({ queryKey: ["traces", days, includeEval, kind, status, q], placeholderData: keepPreviousData,
    queryFn: () => get<{ traces: TraceRow[]; total: number; kinds: string[] }>(`/api/v1/performance/traces${qs({ days, include_eval: includeEval, kind, status, q })}`) });
  const detail = useQuery({ queryKey: ["trace", sel], enabled: sel != null, queryFn: () => get<TraceDetail>(`/api/v1/performance/traces/${sel}`) });
  if (list.data && list.data.total === 0 && !kind && !status && !q) return <NoActivity />;
  const steps = detail.data ? [...detail.data.llm_calls.map((c) => ({ at: c.created_at, label: `LLM · ${c.model}`, ms: c.latency_ms ?? 0, kind: "llm",
    detail: `${c.prompt_tokens}+${c.completion_tokens} tokens · ${c.tool_calls} tool calls · ${c.status}` })),
    ...detail.data.spans.map((s) => ({ at: s.created_at, label: `${s.type} · ${s.name}`, ms: s.latency_ms ?? 0, kind: s.type, detail: (s.ok ? "ok " : "FAILED ") + (s.detail || "") }))]
    .sort((a, b) => a.at.localeCompare(b.at)) : [];
  const max = Math.max(1, ...steps.map((x) => x.ms));
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <Card className="overflow-hidden">
        <div className="flex flex-wrap gap-2 border-b p-3">
          <select value={kind} onChange={(e) => setKind(e.target.value)} className="h-8 rounded-full border bg-card px-3 text-[12.5px]" aria-label="Kind">
            <option value="">All kinds</option>{list.data?.kinds.map((k) => <option key={k}>{k}</option>)}</select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 rounded-full border bg-card px-3 text-[12.5px]" aria-label="Status">
            <option value="">All statuses</option>{["ok", "corrected", "fail_safe", "error", "fallback"].map((k) => <option key={k}>{k}</option>)}</select>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search input" className="h-8 min-w-[120px] flex-1" />
        </div>
        <div className="max-h-[560px] divide-y overflow-y-auto scroll-thin">
          {list.data?.traces.map((t) => (
            <button key={t.id} onClick={() => setSel(t.id)} className={cn("block w-full cursor-pointer px-4 py-2.5 text-left hover:bg-muted/50", sel === t.id && "bg-primary-soft/70")}>
              <div className="flex items-center gap-2 text-[13px]"><span className="font-mono text-[11.5px] text-subtle-foreground">#{t.id}</span><span className="font-semibold">{t.kind}</span>
                <span className="text-muted-foreground">{agentLabel(t.name) || t.name}</span><span className="ml-auto"><StatusBadge value={t.status} /></span></div>
              <div className="mt-0.5 flex gap-2 text-[12px] text-muted-foreground"><span className="truncate">{t.input || "–"}</span>
                <span className="ml-auto shrink-0 tabular">{t.latency_ms != null ? `${(t.latency_ms / 1000).toFixed(1)}s` : ""}</span></div>
            </button>))}
        </div>
      </Card>
      <Card className="p-5">
        {!sel ? <EmptyState icon={Activity} title="Pick a trace" body="See every LLM call, tool call and safety check of one AI task, in order." />
          : !detail.data ? <Skeleton className="h-64" /> : (<>
          <div className="flex flex-wrap items-center gap-2"><h3 className="text-[16px] font-bold">Trace #{detail.data.trace.id} · {detail.data.trace.kind}</h3>
            <StatusBadge value={detail.data.trace.status} />{detail.data.trace.escalated ? <Badge tone="warn">escalated</Badge> : null}</div>
          <div className="mt-1 text-[12px] text-muted-foreground">{detail.data.trace.started_at.slice(0, 19)} · {detail.data.trace.channel ?? "–"}</div>
          {detail.data.trace.input && <p className="mt-3 rounded-xl bg-muted p-3 text-[13px]"><b>In:</b> {detail.data.trace.input}</p>}
          {detail.data.trace.output && <p className="mt-2 rounded-xl border p-3 text-[13px]"><b>Out:</b> {detail.data.trace.output.replace(/\*([^*\n]+)\*/g, "$1")}</p>}
          {detail.data.trace.error && <p className="mt-2 text-[13px] text-danger">{detail.data.trace.error}</p>}
          <div className="mt-4 text-[12px] font-semibold tracking-wide text-muted-foreground uppercase">Timeline</div>
          <div className="mt-2 space-y-2">{steps.map((st, i) => (
            <div key={i} className="text-[12.5px]"><div className="flex justify-between"><span><span className="text-subtle-foreground">{i + 1}.</span> {st.label}</span><span className="tabular text-muted-foreground">{num(st.ms)} ms</span></div>
              <div className="mt-1 h-2 rounded-full bg-muted"><div className={cn("h-full rounded-full", st.kind === "llm" ? "bg-primary" : st.kind === "tool" ? "bg-[var(--chart-4)]" : "bg-danger")} style={{ width: `${Math.max(2, (st.ms / max) * 100)}%` }} /></div>
              <div className="mt-0.5 text-[11.5px] text-subtle-foreground">{st.detail}</div></div>))}</div>
          {Object.keys(detail.data.meta).length > 0 && <details className="mt-4"><summary className="cursor-pointer text-[13px] font-semibold">Metadata</summary>
            <pre className="mt-2 overflow-x-auto rounded-xl bg-muted p-3 text-[11.5px]">{JSON.stringify(detail.data.meta, null, 2)}</pre></details>}
        </>)}
      </Card>
    </div>
  );
}

function CostTab({ d }: { d: Perf }) {
  if (!d.cost_by_feature.length) return <NoActivity />;
  return (
    <Card><CardHeader title="Where the tokens go" description="Estimated at list price · on Gemini's free tier you pay ₹0" />
      <CardBody className="h-72"><ResponsiveContainer>
        <BarChart data={d.cost_by_feature} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 24 }}>
          <XAxis type="number" tick={axis} tickLine={false} axisLine={false} tickFormatter={(v) => `₹${Number(v).toFixed(2)}`} />
          <YAxis type="category" dataKey="feature" tick={axis} tickLine={false} axisLine={false} width={120} />
          <Tooltip formatter={(v) => `₹${Number(v).toFixed(3)}`} cursor={{ fill: "var(--muted)" }} />
          <Bar dataKey="cost_inr" name="Cost" fill="var(--chart-1)" radius={[0, 6, 6, 0]} maxBarSize={28} />
        </BarChart></ResponsiveContainer></CardBody>
      <p className="px-5 pb-5 text-[12.5px] text-muted-foreground">1,000 conversations ≈ {inr(d.summary.cost_per_conversation_inr * 1000)} at list prices. Prices are assumptions in kotler/config.py.</p>
    </Card>
  );
}

type Run = { id: number; suite: string; model: string; started_at: string; cases: number; passed: number; pass_pct: number; full: boolean };
type Cmp = { previous: number; latest: number; regressions: string[]; fixed: string[]; still_failing: string[]; compared: number } | null;

function EvalsTab() {
  const q = useQuery({ queryKey: ["evals"], queryFn: () => get<{ runs: Run[]; compare: Record<string, Cmp> }>("/api/v1/performance/evals") });
  const [run, setRun] = useState<number | null>(null);
  const res = useQuery({ queryKey: ["eval", run], enabled: run != null,
    queryFn: () => get<{ results: { case_id: string; passed: number; failed_checks: string; latency_ms: number; reply: string; error: string | null }[] }>(`/api/v1/performance/evals/${run}`) });
  if (!q.data) return <Skeleton className="h-64 rounded-2xl" />;
  if (!q.data.runs.length) return <Card><EmptyState icon={CircleCheck} title="No eval runs yet" body="Run python -m kotler.evals.shopping (or helpdesk, ask_data) with a Gemini key." /></Card>;
  const suites = Object.keys(q.data.compare);
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">{suites.map((s) => {
        const c = q.data!.compare[s]; const full = q.data!.runs.filter((r) => r.suite === s && r.full); const last = full.at(-1);
        return (
          <Card key={s} className="p-5"><div className="flex items-center justify-between"><h3 className="font-bold">{titleCase(s)}</h3>
            {last && <span className="font-display text-[22px] font-extrabold tabular">{last.passed}/{last.cases}</span>}</div>
            <div className="mt-1 text-[12px] text-muted-foreground">Latest full run {last ? relativeTime(last.started_at) + " ago" : "–"}</div>
            {c ? <div className="mt-3 space-y-2 text-[13px]">
              <div className="flex gap-2"><Badge tone={c.regressions.length ? "bad" : "good"}>{c.regressions.length} broke</Badge><Badge tone={c.fixed.length ? "good" : "neutral"}>{c.fixed.length} fixed</Badge></div>
              {c.regressions.length > 0 && <p><b>Broke:</b> {c.regressions.join(", ")}</p>}
              {c.fixed.length > 0 && <p className="text-muted-foreground"><b>Fixed:</b> {c.fixed.join(", ")}</p>}
            </div> : <p className="mt-3 text-[12.5px] text-muted-foreground">Needs two full runs to compare.</p>}
          </Card>);
      })}</div>
      <Card><CardHeader title="Pass rate per full run" description="Partial re-runs (checking one fix) are left out" />
        <CardBody className="h-56"><ResponsiveContainer>
          <LineChart margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="started_at" type="category" allowDuplicatedCategory={false} tick={axis} tickLine={false} axisLine={false} tickFormatter={(v) => String(v).slice(5, 16)} />
            <YAxis domain={[0, 100]} tick={axis} tickLine={false} axisLine={false} /><Tooltip />
            {suites.map((s, i) => <Line key={s} data={q.data!.runs.filter((r) => r.suite === s && r.full)} dataKey="pass_pct" name={s} stroke={`var(--chart-${i + 1})`} strokeWidth={2} />)}
          </LineChart></ResponsiveContainer></CardBody></Card>
      <Card><CardHeader title="All runs" />
        <div className="max-h-80 overflow-auto scroll-thin"><table className="w-full text-[13px]"><thead className="sticky top-0 border-y bg-muted"><tr><Th>Run</Th><Th>Suite</Th><Th>When</Th><Th className="text-right">Passed</Th></tr></thead>
          <tbody className="divide-y">{[...q.data.runs].reverse().map((r) => (
            <tr key={r.id} onClick={() => setRun(r.id)} className={cn("cursor-pointer hover:bg-muted/50", run === r.id && "bg-primary-soft/60")}>
              <Td className="font-mono">#{r.id}</Td><Td>{r.suite}{!r.full && <Badge tone="outline" className="ml-2">partial</Badge>}</Td>
              <Td className="text-muted-foreground">{r.started_at}</Td><Td className="text-right font-semibold tabular">{r.passed}/{r.cases}</Td></tr>))}</tbody></table></div>
        {res.data && <div className="border-t p-4"><div className="mb-2 text-[13px] font-semibold">Run #{run}</div><div className="space-y-1.5">
          {res.data.results.map((x) => <div key={x.case_id} className="flex items-start gap-2 text-[12.5px]">{x.passed ? <CircleCheck className="size-4 shrink-0 text-success" /> : <CircleX className="size-4 shrink-0 text-danger" />}
            <span className="font-mono">{x.case_id}</span>{x.failed_checks && <span className="text-danger">({x.failed_checks})</span>}<span className="ml-auto line-clamp-1 max-w-[50%] text-muted-foreground">{x.error || x.reply}</span></div>)}</div></div>}
      </Card>
    </div>
  );
}

function ImpactTab({ days }: { days: number }) {
  const q = useQuery({ queryKey: ["impact", days], queryFn: () => get<{ levers: { lever: string; inr: number; period: string; evidence: string; how: string }[]; measured_total: number; assumptions: { human_cost_per_conversation: number } }>(`/api/v1/performance/impact?days=${days}`) });
  if (!q.data) return <Skeleton className="h-64 rounded-2xl" />;
  const tone = { measured: "good", modelled: "primary", simulated: "warn" } as const;
  return (
    <div className="space-y-4">
      <div className="rounded-3xl bg-ink p-6 text-ink-foreground"><div className="text-[13px] opacity-70">Measured net value · last {days} days</div>
        <div className="mt-1 font-display text-[40px] font-extrabold tracking-tight text-primary">{inr(q.data.measured_total)}</div>
        <p className="text-[13px] opacity-70">Only measured values are added up. Modelled and simulated values are shown separately, never mixed in.</p></div>
      <div className="grid gap-4 md:grid-cols-2">{q.data.levers.map((l) => (
        <Card key={l.lever} className="p-5"><div className="flex items-start justify-between gap-3"><h3 className="font-bold">{l.lever}</h3><Badge tone={tone[l.evidence as keyof typeof tone] ?? "neutral"}>{l.evidence}</Badge></div>
          <div className={cn("mt-2 font-display text-[28px] font-extrabold tabular", l.inr < 0 && "text-danger")}>{inr(l.inr)}</div>
          <div className="text-[12px] text-muted-foreground">{l.period}</div><p className="mt-2 text-[13px] text-muted-foreground">{l.how}</p></Card>))}</div>
      <p className="text-[12.5px] text-muted-foreground">Assumption: a human-handled support conversation costs ₹{q.data.assumptions.human_cost_per_conversation} (₹25,000/month ÷ 22 days × 25 conversations).</p>
    </div>
  );
}
