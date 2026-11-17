import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowUp, Bot, CircleCheck, Eye, Gavel, Hand, History, Lock, PenLine, Plus, RotateCcw, Save, ShieldCheck, Trash2, TriangleAlert, Wrench } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { ErrorNote } from "@/components/data";
import { PageHeader } from "@/components/empty";
import { ProductCards, type ProductCard } from "@/components/product";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { del, get, post, put } from "@/lib/api";
import { num, pct, ago } from "@/lib/format";
import { cn } from "@/lib/utils";

type AgentCfg = { slug: string; name: string; role: string; description: string; instructions: string; goal: string; success_criteria: string;
  tools: string[]; handoff_rules: string[]; temperature: number; max_steps: number; status: "draft" | "live"; version: number; is_builtin: boolean; updated_at: string };
type AgentRow = AgentCfg & { score: { judged: number; success: number; score: number } | null; conversations: number };
type Meta = { tools: { name: string; description: string; writes: boolean }[]; templates: Record<string, AgentCfg>;
  handoff_rules: { key: string; label: string; examples: string }[]; data_access: Record<string, { data: string; access: "reads" | "changes" }> };
type Version = { version: number; note: string | null; created_at: string; changes: string[] };

export function Studio() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["agents"], queryFn: () => get<{ agents: AgentRow[] }>("/api/v1/agents") });
  const meta = useQuery({ queryKey: ["agents-meta"], queryFn: () => get<Meta>("/api/v1/agents/meta") });
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ slug: "", name: "", template: "Blank agent" });
  const create = useMutation({ meta: { inlineError: true }, mutationFn: () => post<{ agent: AgentCfg }>("/api/v1/agents", form),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["agents"] }); navigate(`/app/studio/${r.agent.slug}`); } });
  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6 lg:p-8">
      <PageHeader title="Agent Studio" description="Agents are configuration: instructions, goal, success criteria and tools. Every save is a version you can roll back."
        actions={<Button variant="primary" onClick={() => setCreating(!creating)}><Plus />New agent</Button>} />
      {creating && (
        <Card className="mb-5 p-5 animate-in">
          <div className="grid gap-3 sm:grid-cols-4">
            <Input placeholder="ID, e.g. winback-riya" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-") })} />
            <Input placeholder="Display name, e.g. Riya" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <select value={form.template} onChange={(e) => setForm({ ...form, template: e.target.value })} className="h-9 rounded-xl border bg-card px-3 text-[13px]">
              {Object.keys(meta.data?.templates ?? { "Blank agent": 1 }).map((t) => <option key={t}>{t}</option>)}</select>
            <Button variant="ink" onClick={() => create.mutate()} disabled={!form.slug || !form.name || create.isPending}>Create draft</Button>
          </div>
          {create.isError && <div className="mt-3"><ErrorNote error={create.error} /></div>}
        </Card>)}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {!q.data ? [1, 2, 3].map((i) => <Skeleton key={i} className="h-52 rounded-2xl" />) : q.data.agents.map((a) => (
          <Link key={a.slug} to={`/app/studio/${a.slug}`}>
            <Card className="flex h-full flex-col p-5 transition-shadow hover:shadow-[0_18px_50px_-30px_rgba(60,30,0,0.35)]">
              <div className="flex items-center gap-3"><div className="grid size-11 place-items-center rounded-2xl bg-ink text-primary"><Bot className="size-5" /></div>
                <div className="min-w-0"><div className="truncate font-bold">{a.name}</div><div className="text-[12px] text-muted-foreground">{a.role}</div></div>
                <Badge tone={a.status === "live" ? "good" : "neutral"} className="ml-auto">{a.status === "live" ? "Live" : "Draft"}</Badge></div>
              <p className="mt-3 line-clamp-2 flex-1 text-[13px] text-muted-foreground">{a.description || a.goal}</p>
              <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted-foreground">
                <span>v{a.version}</span><span>{a.tools.length} tools</span><span>{num(a.conversations)} conversations</span>
                {a.score && <span className="font-semibold text-success">{pct(a.score.success, 0)} judged success</span>}
                {a.is_builtin && <span>built-in</span>}</div>
            </Card>
          </Link>))}
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="block"><span className="text-[13px] font-semibold">{label}</span>{hint && <span className="ml-2 text-[12px] text-muted-foreground">{hint}</span>}<div className="mt-1.5">{children}</div></label>;
}

export function AgentEditor() {
  const { slug = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["agent", slug], queryFn: () => get<{ agent: AgentCfg; versions: Version[]; scorecard: { version: number; judged: number; success_pct: number; avg_score: number }[] }>(`/api/v1/agents/${slug}`) });
  const meta = useQuery({ queryKey: ["agents-meta"], queryFn: () => get<Meta>("/api/v1/agents/meta") });
  const [cfg, setCfg] = useState<AgentCfg | null>(null);
  const [note, setNote] = useState("");
  useEffect(() => { if (q.data) setCfg(q.data.agent); }, [q.data]);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["agent", slug] }); qc.invalidateQueries({ queryKey: ["agents"] }); };
  const save = useMutation({ meta: { inlineError: true }, mutationFn: () => put<{ agent: AgentCfg }>(`/api/v1/agents/${slug}`, { ...cfg, note }),
    onSuccess: (r) => { toast.success(`Saved as version ${r.agent.version}.`); setNote(""); refresh(); } });
  const status = useMutation({ mutationFn: (s: string) => post(`/api/v1/agents/${slug}/status`, { status: s }), onSuccess: () => { toast.success("Status updated."); refresh(); } });
  const restore = useMutation({ mutationFn: (v: number) => post<{ agent: AgentCfg }>(`/api/v1/agents/${slug}/restore`, { version: v }),
    onSuccess: (r) => { toast.success(`Restored as version ${r.agent.version}.`); refresh(); } });
  const remove = useMutation({ mutationFn: () => del(`/api/v1/agents/${slug}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["agents"] }); navigate("/app/studio"); } });
  if (q.isError) return <div className="p-8"><ErrorNote error={q.error} /></div>;
  if (!cfg || !q.data) return <div className="p-8"><Skeleton className="h-[600px] rounded-2xl" /></div>;
  const dirty = JSON.stringify(cfg) !== JSON.stringify(q.data.agent);
  const set = <K extends keyof AgentCfg>(k: K, v: AgentCfg[K]) => setCfg({ ...cfg, [k]: v });
  return (
    <div className="mx-auto max-w-[1500px] p-4 sm:p-6 lg:p-8">
      <Link to="/app/studio" className="mb-3 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />All agents</Link>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="grid size-12 place-items-center rounded-2xl bg-ink text-primary"><Bot className="size-6" /></div>
        <div><h1 className="text-[26px] font-extrabold tracking-tight">{q.data.agent.name}</h1><p className="text-[13px] text-muted-foreground">{slug} · version {q.data.agent.version} · updated {ago(q.data.agent.updated_at)}</p></div>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button onClick={() => status.mutate(cfg.status === "live" ? "draft" : "live")} disabled={status.isPending || dirty}>{q.data.agent.status === "live" ? "Set to draft" : "Go live"}</Button>
          {!q.data.agent.is_builtin && <Button variant="ghost" onClick={() => confirm(`Delete ${q.data.agent.name}? This can't be undone.`) && remove.mutate()}><Trash2 />Delete</Button>}
        </div>
      </div>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Card><CardHeader title="Configuration" description="What the agent is told. Permissions and safety checks are enforced in code on top of this." />
            <CardBody className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2"><Field label="Name"><Input value={cfg.name} onChange={(e) => set("name", e.target.value)} /></Field>
                <Field label="Role"><Input value={cfg.role} onChange={(e) => set("role", e.target.value)} /></Field></div>
              <Field label="Description" hint="shown in lists"><Input value={cfg.description} onChange={(e) => set("description", e.target.value)} /></Field>
              <Field label="Instructions" hint={`${cfg.instructions.length}/6000`}><Textarea rows={12} value={cfg.instructions} onChange={(e) => set("instructions", e.target.value)} className="font-mono text-[12.5px]" /></Field>
              <Field label="Goal"><Textarea rows={2} value={cfg.goal} onChange={(e) => set("goal", e.target.value)} /></Field>
              <Field label="Success criteria" hint="what the LLM judge checks"><Textarea rows={2} value={cfg.success_criteria} onChange={(e) => set("success_criteria", e.target.value)} /></Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={`Temperature: ${cfg.temperature.toFixed(1)}`} hint="lower = more predictable"><input type="range" min={0} max={1} step={0.1} value={cfg.temperature} onChange={(e) => set("temperature", Number(e.target.value))} className="w-full accent-[var(--primary)]" /></Field>
                <Field label={`Max steps: ${cfg.max_steps}`} hint="tool calls per reply"><input type="range" min={1} max={8} value={cfg.max_steps} onChange={(e) => set("max_steps", Number(e.target.value))} className="w-full accent-[var(--primary)]" /></Field>
              </div>
            </CardBody></Card>
          <Card><CardHeader title="Tools" description="The agent only sees the tools ticked here. Tools that change orders are marked." />
            <CardBody className="grid gap-2 sm:grid-cols-2">{meta.data?.tools.map((t) => {
              const on = cfg.tools.includes(t.name);
              return (
                <label key={t.name} className={cn("flex cursor-pointer gap-3 rounded-xl border p-3 transition-colors", on ? "border-primary/50 bg-primary-soft/50" : "hover:bg-muted/50")}>
                  <input type="checkbox" checked={on} onChange={() => set("tools", on ? cfg.tools.filter((x) => x !== t.name) : [...cfg.tools, t.name])} className="mt-0.5 accent-[var(--primary)]" />
                  <div className="min-w-0"><div className="flex items-center gap-1.5 font-mono text-[12.5px] font-semibold">{t.name}{t.writes && <Badge tone="warn">acts</Badge>}</div>
                    <p className="mt-0.5 line-clamp-2 text-[12px] text-muted-foreground">{t.description}</p></div>
                </label>);
            })}</CardBody></Card>
          {meta.data && <Handoff cfg={cfg} meta={meta.data} onChange={(r) => set("handoff_rules", r)} />}
          {meta.data && <DataAccess tools={cfg.tools} meta={meta.data} />}
          <div className="sticky bottom-3 z-10 flex items-center gap-2 rounded-2xl border bg-card/95 p-3 shadow-lg backdrop-blur">
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed? (version note)" maxLength={200} className="flex-1" />
            <Button variant="ghost" disabled={!dirty} onClick={() => setCfg(q.data.agent)}>Discard</Button>
            <Button variant="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}><Save />Save version</Button>
          </div>
          {save.isError && <ErrorNote error={save.error} />}
        </div>
        <div className="space-y-5">
          <Playground slug={slug} dirty={dirty} />
          <Card><CardHeader title="Versions" description="Restoring saves the old version as a new one: history is never rewritten" action={<History className="size-4 text-muted-foreground" />} />
            <CardBody className="max-h-96 space-y-2 overflow-y-auto scroll-thin">{q.data.versions.map((v) => {
              const sc = q.data.scorecard.find((s) => s.version === v.version);
              return (
                <div key={v.version} className="rounded-xl border p-3">
                  <div className="flex items-center gap-2 text-[13px]"><span className="rounded-md bg-muted px-1.5 font-mono text-[12px]">v{v.version}</span><span className="font-medium">{v.note || "Saved"}</span>
                    {v.version === q.data.agent.version ? <Badge tone="primary" className="ml-auto">current</Badge>
                      : <Button size="sm" variant="ghost" className="ml-auto" onClick={() => restore.mutate(v.version)} disabled={restore.isPending}><RotateCcw />Restore</Button>}</div>
                  <div className="mt-1 text-[11.5px] text-muted-foreground">{ago(v.created_at)}{sc && ` · ${sc.success_pct}% success over ${sc.judged} judged`}</div>
                  {v.changes.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1">{v.changes.map((c) => <Badge key={c} tone="outline">{c}</Badge>)}</div>}
                </div>);
            })}</CardBody></Card>
        </div>
      </div>
    </div>
  );
}

/** Situations where a person must take over. Enforced in code (kotler/agent/handoff.py), not just asked for. */
function Handoff({ cfg, meta, onChange }: { cfg: AgentCfg; meta: Meta; onChange: (rules: string[]) => void }) {
  const canEscalate = cfg.tools.includes("escalate_to_human");
  return (
    <Card><CardHeader title="Hand over to a person when…" description="Checked in code on every customer message. If one matches and the agent didn't escalate by itself, it is escalated anyway and the customer is told a person will reply." />
      <CardBody className="space-y-2">
        {meta.handoff_rules.map((r) => {
          const on = cfg.handoff_rules.includes(r.key);
          return (
            <label key={r.key} className="flex cursor-pointer items-center gap-3 rounded-xl border p-3 hover:bg-muted/40">
              <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-semibold">{r.label}</span>
                <span className="block text-[12px] text-muted-foreground">{r.examples}</span></span>
              <input type="checkbox" role="switch" aria-label={r.label} checked={on} className="peer sr-only"
                onChange={() => onChange(on ? cfg.handoff_rules.filter((x) => x !== r.key) : [...cfg.handoff_rules, r.key])} />
              <span aria-hidden className={cn("relative h-5 w-9 shrink-0 rounded-full transition-colors peer-focus-visible:ring-3 peer-focus-visible:ring-ring/30", on ? "bg-primary" : "bg-muted-foreground/30")}>
                <span className={cn("absolute top-0.5 size-4 rounded-full bg-white shadow transition-all", on ? "left-[18px]" : "left-0.5")} /></span>
            </label>);
        })}
        <p className="flex items-start gap-1.5 pt-1 text-[12px] text-muted-foreground"><Hand className="mt-0.5 size-3.5 shrink-0" />
          {canEscalate ? "This agent can create a care ticket, so matching chats get a ticket and show as “Needs you” in the inbox."
            : "This agent has no escalate_to_human tool: matching chats are flagged “Needs you” in the inbox."}</p>
      </CardBody></Card>
  );
}

/** Derived from the ticked tools, so it can never drift from what the agent can really do. */
function DataAccess({ tools, meta }: { tools: string[]; meta: Meta }) {
  const pick = (a: "reads" | "changes") => [...new Set(tools.map((t) => meta.data_access[t]).filter((d) => d?.access === a).map((d) => d.data))];
  const reads = pick("reads"), changes = pick("changes");
  return (
    <Card><CardHeader title="What this agent can see and change" description="Worked out from its tools. Limits are enforced inside the tools, whatever the prompt says." />
      <CardBody className="grid gap-4 sm:grid-cols-2">
        <div><div className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground"><Eye className="size-3.5" />Can read</div>
          <ul className="space-y-1.5 text-[13px]">{reads.length ? reads.map((d) => <li key={d} className="flex gap-2"><CircleCheck className="mt-0.5 size-3.5 shrink-0 text-success" />{d}</li>)
            : <li className="text-muted-foreground">Nothing: tick a tool</li>}</ul></div>
        <div><div className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground"><PenLine className="size-3.5" />Can change</div>
          <ul className="space-y-1.5 text-[13px]">{changes.length ? changes.map((d) => <li key={d} className="flex gap-2"><TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" />{d}</li>)
            : <li className="flex gap-2 text-muted-foreground"><Lock className="mt-0.5 size-3.5 shrink-0" />Nothing: read-only agent</li>}</ul></div>
        <p className="flex gap-2 rounded-xl bg-muted/60 p-3 text-[12.5px] text-muted-foreground sm:col-span-2"><Lock className="mt-0.5 size-3.5 shrink-0" />
          No agent can see other customers' orders or profiles (every order tool checks ownership), run database queries, or see payment details (none are stored).</p>
      </CardBody></Card>
  );
}

type ChatTurn = { me: string; reply?: string; tools?: { name: string; arguments: Record<string, unknown>; result: Record<string, unknown> }[]; guard?: string[]; handoff?: string[]; latency_ms?: number; error?: string | null; cards?: ProductCard[] };

function Playground({ slug, dirty }: { slug: string; dirty: boolean }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [conv, setConv] = useState<number | null>(null);
  const [customer, setCustomer] = useState("");
  const [text, setText] = useState("");
  const send = useMutation({
    meta: { inlineError: true },
    mutationFn: (m: string) => post<ChatTurn & { conversation_id: number }>(`/api/v1/agents/${slug}/chat`, { message: m, conversation_id: conv, customer_id: customer ? Number(customer) : null }),
    onMutate: (m) => { setTurns((t) => [...t, { me: m }]); setText(""); },
    onSuccess: (r) => { setConv(r.conversation_id); setTurns((t) => [...t.slice(0, -1), { ...t.at(-1)!, ...r }]); },
    onError: () => setTurns((t) => t.slice(0, -1)),
  });
  const judge = useMutation({ meta: { inlineError: true }, mutationFn: () => post<{ achieved: boolean; score: number; reason: string }>(`/api/v1/agents/${slug}/judge`, { conversation_id: conv }) });
  return (
    <Card>
      <CardHeader title="Playground" description={dirty ? "Save first: the playground runs the saved version" : "Chat with the saved version (drafts too)"}
        action={<div className="flex gap-1.5">{conv && <Button size="sm" onClick={() => judge.mutate()} disabled={judge.isPending}><Gavel />Judge</Button>}
          <Button size="sm" variant="ghost" onClick={() => { setTurns([]); setConv(null); judge.reset(); }}><RotateCcw />Reset</Button></div>} />
      <CardBody>
        <div className="mb-3 flex items-center gap-2 text-[12.5px]"><span className="text-muted-foreground">As customer #</span>
          <Input value={customer} onChange={(e) => setCustomer(e.target.value.replace(/\D/g, ""))} placeholder="guest" className="h-8 w-24" disabled={!!conv} /></div>
        <div className="h-[340px] space-y-3 overflow-y-auto rounded-2xl bg-background p-3 scroll-thin">
          {turns.length === 0 && <p className="pt-24 text-center text-[13px] text-muted-foreground">Say hi, or try a tricky request.</p>}
          {turns.map((t, i) => (
            <div key={i} className="space-y-2">
              <div className="flex justify-end"><div className="max-w-[85%] rounded-2xl rounded-br-md bg-ink px-3.5 py-2 text-[13.5px] text-ink-foreground">{t.me}</div></div>
              {t.tools?.map((x, j) => <details key={j} className="rounded-xl border border-dashed px-3 py-1.5 text-[12px]"><summary className="cursor-pointer text-muted-foreground"><Wrench className="mr-1 inline size-3.5" />{x.name}</summary>
                <pre className="mt-1 overflow-x-auto text-[11px] whitespace-pre-wrap">{JSON.stringify(x.arguments)}{"\n→ "}{JSON.stringify(x.result).slice(0, 600)}</pre></details>)}
              {t.guard?.length ? <p className="text-[11.5px] text-warning"><ShieldCheck className="mr-1 inline size-3.5" />{t.guard.join("; ")}</p> : null}
              {t.handoff?.length ? <p className="text-[11.5px] text-danger"><Hand className="mr-1 inline size-3.5" />Handoff rule: {t.handoff.map((h) => h.replace(/_/g, " ")).join(", ")}. A person will join.</p> : null}
              {t.reply !== undefined && <ProductCards cards={t.cards} />}
              {t.reply !== undefined ? <div className="flex"><div className="max-w-[85%] rounded-2xl rounded-bl-md border bg-card px-3.5 py-2 text-[13.5px] whitespace-pre-wrap">{t.reply}
                <div className="mt-1 text-[10.5px] text-subtle-foreground">{((t.latency_ms ?? 0) / 1000).toFixed(1)}s</div></div></div>
                : <Skeleton className="h-10 w-2/3 rounded-2xl" />}
            </div>))}
        </div>
        {send.isError && <div className="mt-3"><ErrorNote error={send.error} /></div>}
        {judge.data && <div className={cn("mt-3 rounded-xl p-3 text-[13px]", judge.data.achieved ? "bg-success-soft text-success" : "bg-warning-soft text-warning")}>
          <b>{judge.data.achieved ? "Goal achieved" : "Goal not achieved"} · {judge.data.score}/5.</b> {judge.data.reason}</div>}
        {judge.isError && <div className="mt-3"><ErrorNote error={judge.error} /></div>}
        <div className="mt-3 flex items-end gap-2 rounded-2xl border bg-card p-1.5">
          <Textarea rows={1} value={text} onChange={(e) => setText(e.target.value)} placeholder="Message the agent…" className="border-0 bg-transparent shadow-none focus:ring-0"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (text.trim()) send.mutate(text.trim()); } }} maxLength={1000} />
          <Button size="icon" variant="primary" aria-label="Send" disabled={!text.trim() || send.isPending} onClick={() => send.mutate(text.trim())}><ArrowUp /></Button>
        </div>
      </CardBody>
    </Card>
  );
}
