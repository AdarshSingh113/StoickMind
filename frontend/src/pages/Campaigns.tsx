import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, BarChart3, FlaskConical, Megaphone, Plus, RefreshCcw, Send, Sparkles, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { ErrorNote, Stat, StatusBadge, Td, Th } from "@/components/data";
import { EmptyState, PageHeader } from "@/components/empty";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { get, post } from "@/lib/api";
import { inr, inrCompact, num, pct, ago, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

type Journey = { journey: string; description: string; customers: number; avg_churn_risk: number | null; value_12m: number };
type CampaignRow = { id: number; name: string; journey: string; channel: string; offer_pct: number; holdout_pct: number; status: string;
  created_at: string; audience: number; messaged: number; control: number; excluded: number; template_source: string };
type Templates = Record<"A" | "B", { angle: string; en: string; hinglish: string }>;

const CHANNEL: Record<string, string> = { whatsapp: "WhatsApp", telegram: "Telegram" };
const JOURNEY_LABEL: Record<string, string> = { replenishment: "Replenishment", win_back: "Win-back", cross_sell: "Complete the routine", second_order: "Second order" };

export function Campaigns() {
  const journeys = useQuery({ queryKey: ["journeys"], queryFn: () => get<{ journeys: Journey[] }>("/api/v1/journeys") });
  const list = useQuery({ queryKey: ["campaigns"], queryFn: () => get<{ campaigns: CampaignRow[] }>("/api/v1/campaigns") });
  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6 lg:p-8">
      <PageHeader title="Campaigns" description="Retention journeys pick who to message today. Every campaign keeps a holdout group, so you see what it really caused."
        actions={<Link to="/app/campaigns/new"><Button variant="primary"><Plus />New campaign</Button></Link>} />
      {journeys.isError && <ErrorNote error={journeys.error} />}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {!journeys.data ? [1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-44 rounded-2xl" />) : journeys.data.journeys.map((j) => (
          <Card key={j.journey} className="flex flex-col p-5">
            <div className="flex items-center gap-2"><div className="grid size-9 place-items-center rounded-xl bg-primary-soft text-primary"><Users className="size-4" /></div>
              <h3 className="font-bold">{JOURNEY_LABEL[j.journey] ?? j.journey}</h3></div>
            <p className="mt-2 flex-1 text-[13px] text-muted-foreground">{j.description}</p>
            <div className="mt-3 flex items-end justify-between"><div><div className="font-display text-[26px] font-extrabold tabular">{num(j.customers)}</div>
              <div className="text-[11.5px] text-muted-foreground">customers today · {inrCompact(j.value_12m)} predicted value</div></div>
              <Link to={`/app/campaigns/new?journey=${j.journey}`}><Button size="sm" variant="ink">Create<ArrowRight /></Button></Link></div>
          </Card>))}
      </div>
      <Card className="mt-6">
        <CardHeader title="All campaigns" />
        {list.data && list.data.campaigns.length === 0 ? <EmptyState icon={Megaphone} title="No campaigns yet" body="Pick a journey above to create your first one." /> : (
          <div className="overflow-x-auto"><table className="w-full text-[13.5px]">
            <thead className="border-y bg-muted/50"><tr><Th>Campaign</Th><Th>Journey</Th><Th>Status</Th><Th className="text-right">Messaged</Th><Th className="text-right">Holdout</Th><Th className="text-right">Offer</Th><Th>Created</Th></tr></thead>
            <tbody className="divide-y">{list.data?.campaigns.map((c) => (
              <tr key={c.id} className="hover:bg-muted/50"><Td><Link to={`/app/campaigns/${c.id}`} className="font-semibold hover:text-primary">{c.name}</Link></Td>
                <Td>{JOURNEY_LABEL[c.journey] ?? c.journey}</Td><Td><StatusBadge value={c.status} /></Td><Td className="text-right tabular">{num(c.messaged)}</Td>
                <Td className="text-right tabular">{num(c.control)}</Td><Td className="text-right tabular">{c.offer_pct ? `${c.offer_pct}%` : "–"}</Td>
                <Td className="text-muted-foreground">{ago(c.created_at)}</Td></tr>))}</tbody></table></div>)}
      </Card>
    </div>
  );
}

export function NewCampaign() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [journey, setJourney] = useState(params.get("journey") || "replenishment");
  const [name, setName] = useState("");
  const [offer, setOffer] = useState(10);
  const [holdout, setHoldout] = useState(20);
  const [channel, setChannel] = useState("whatsapp");
  const [templates, setTemplates] = useState<Templates | null>(null);
  const [source, setSource] = useState("manual");
  useEffect(() => { setName(`${JOURNEY_LABEL[journey]} · ${new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`); setTemplates(null); }, [journey]);
  const audience = useQuery({ queryKey: ["audience", journey], queryFn: () => get<{ total: number; sample: { first_name: string; segment: string; product_name: string; price: number; reason: string; churn_risk: number }[] }>(`/api/v1/journeys/${journey}/audience?limit=8`) });
  const gen = useMutation({ mutationFn: () => post<{ templates: Templates; source: string }>("/api/v1/campaigns/templates", { journey, offer_pct: offer }),
    onSuccess: (r) => { setTemplates(r.templates); setSource(r.source); toast.success(r.source === "ai" ? "AI wrote two variants. Edit freely." : "Using the hand-written templates (AI unavailable or its draft failed validation)."); } });
  const create = useMutation({ mutationFn: () => post<{ id: number }>("/api/v1/campaigns", { name, journey, templates, template_source: source, offer_pct: offer, holdout_pct: holdout / 100, channel }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["campaigns"] }); toast.success("Campaign created as a draft."); navigate(`/app/campaigns/${r.id}`); } });
  const edit = (v: "A" | "B", lang: "en" | "hinglish", text: string) => setTemplates((t) => t && { ...t, [v]: { ...t[v], [lang]: text } });
  return (
    <div className="mx-auto max-w-5xl p-4 sm:p-6 lg:p-8">
      <Link to="/app/campaigns" className="mb-3 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Campaigns</Link>
      <PageHeader title="New campaign" description="Choose who, write two messages, keep a holdout. Guardrails: max 15% discount, 7-day frequency cap, open tickets excluded." />
      <div className="space-y-5">
        <Card><CardHeader title="1 · Audience" description={audience.data ? `${num(audience.data.total)} customers qualify today` : "Loading…"} />
          <CardBody>
            <div className="flex flex-wrap gap-2">{Object.entries(JOURNEY_LABEL).map(([k, l]) => (
              <button key={k} onClick={() => setJourney(k)} className={cn("cursor-pointer rounded-full border px-3.5 py-1.5 text-[13px] font-medium",
                journey === k ? "border-ink bg-ink text-ink-foreground" : "hover:border-primary/40")}>{l}</button>))}</div>
            {audience.data && <div className="mt-4 overflow-x-auto rounded-xl border"><table className="w-full text-[12.5px]"><thead className="bg-muted"><tr><Th>Customer</Th><Th>Segment</Th><Th>Product to promote</Th><Th>Why</Th></tr></thead>
              <tbody className="divide-y">{audience.data.sample.map((a, i) => <tr key={i}><Td>{a.first_name}</Td><Td>{a.segment}</Td><Td>{a.product_name} · {inr(a.price)}</Td><Td className="text-muted-foreground">{a.reason}</Td></tr>)}</tbody></table></div>}
          </CardBody></Card>
        <Card><CardHeader title="2 · Offer & measurement" />
          <CardBody className="grid gap-5 sm:grid-cols-3">
            <label className="text-[13px]"><span className="font-semibold">Name</span><Input value={name} onChange={(e) => setName(e.target.value)} className="mt-1.5" maxLength={80} /></label>
            <label className="text-[13px]"><span className="font-semibold">Discount: {offer ? `${offer}%` : "none"}</span>
              <input type="range" min={0} max={15} value={offer} onChange={(e) => { setOffer(Number(e.target.value)); setTemplates(null); }} className="mt-3 w-full accent-[var(--primary)]" />
              <span className="text-[11.5px] text-muted-foreground">Capped at 15% in code</span></label>
            <label className="text-[13px]"><span className="font-semibold">Holdout: {holdout}%</span>
              <input type="range" min={5} max={50} step={5} value={holdout} onChange={(e) => setHoldout(Number(e.target.value))} className="mt-3 w-full accent-[var(--primary)]" />
              <span className="text-[11.5px] text-muted-foreground">Not messaged: the baseline to compare against</span></label>
            <label className="text-[13px]"><span className="font-semibold">Channel</span>
              <select value={channel} onChange={(e) => setChannel(e.target.value)} className="mt-1.5 h-9 w-full rounded-xl border bg-card px-3"><option value="whatsapp">WhatsApp</option><option value="telegram">Telegram</option></select></label>
          </CardBody></Card>
        <Card><CardHeader title="3 · Messages (A/B test)" description="Use placeholders: {first_name} {product} {price} {discount} {code} {days}. Prices and discounts can't be typed in."
            action={<Button size="sm" variant="primary" onClick={() => gen.mutate()} disabled={gen.isPending}><Sparkles />{gen.isPending ? "Writing…" : templates ? "Rewrite" : "Write with AI"}</Button>} />
          <CardBody>
            {!templates ? <p className="rounded-xl border border-dashed p-6 text-center text-[13px] text-muted-foreground">Click “Write with AI” for two variants in English and Hinglish (hand-written templates are used if AI isn't available).</p>
              : <div className="grid gap-4 md:grid-cols-2">{(["A", "B"] as const).map((v) => (
                <div key={v} className="rounded-2xl border p-4"><div className="mb-2 flex items-center gap-2"><Badge tone="primary">Variant {v}</Badge><span className="text-[12px] text-muted-foreground">{templates[v].angle}</span></div>
                  <label className="text-[12px] font-semibold">English</label><Textarea rows={4} value={templates[v].en} onChange={(e) => edit(v, "en", e.target.value)} className="mt-1 mb-3" />
                  <label className="text-[12px] font-semibold">Hinglish</label><Textarea rows={4} value={templates[v].hinglish} onChange={(e) => edit(v, "hinglish", e.target.value)} className="mt-1" /></div>))}</div>}
            {gen.isError && <div className="mt-3"><ErrorNote error={gen.error} /></div>}
          </CardBody></Card>
        {create.isError && <ErrorNote error={create.error} />}
        <div className="flex justify-end"><Button variant="primary" size="lg" disabled={!templates || !name.trim() || create.isPending} onClick={() => create.mutate()}>Create draft<ArrowRight /></Button></div>
      </div>
    </div>
  );
}

type Results = { verdict: string; treated_rate: number; control_rate: number; abs_uplift: number; rel_uplift: number | null; p_value: number; significant: boolean;
  incremental_orders: number; incremental_revenue: number; message_cost: number; discount_cost: number; net_profit: number; roi: number | null; naive_orders: number;
  groups: { group: string; customers: number; conversions: number; rate: number; ci_low: number; ci_high: number; revenue: number }[];
  ab: { p_value: number; winner: string | null }; sample_size_needed_per_group: number; control_size: number };
type Detail = { campaign: CampaignRow & { templates: Templates; code: string | null; audience_desc: string; sent_at: string | null };
  groups: { grp: string; customers: number }[]; exclusions: { reason: string; customers: number }[];
  examples: { grp: string; language: string; message: string; name: string }[]; results: Results | null };

export function CampaignDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["campaign", id], queryFn: () => get<Detail>(`/api/v1/campaigns/${id}`) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["campaign", id] }); qc.invalidateQueries({ queryKey: ["campaigns"] }); };
  const send = useMutation({ mutationFn: () => post<{ sent: number }>(`/api/v1/campaigns/${id}/send`), onSuccess: (r) => { toast.success(`${num(r.sent)} messages sent (simulated outbox).`); refresh(); } });
  const sim = useMutation({ mutationFn: () => post(`/api/v1/campaigns/${id}/simulate`), onSuccess: () => { toast.success("14 days of customer responses simulated."); refresh(); } });
  if (q.isError) return <div className="p-8"><ErrorNote error={q.error} /></div>;
  if (!q.data) return <div className="p-8"><Skeleton className="h-96 rounded-2xl" /></div>;
  const { campaign: c, results: r } = q.data;
  const g = Object.fromEntries(q.data.groups.map((x) => [x.grp, x.customers]));
  const step = c.status === "draft" ? 0 : c.status === "sent" ? 1 : 2;
  return (
    <div className="mx-auto max-w-6xl space-y-5 p-4 sm:p-6 lg:p-8">
      <Link to="/app/campaigns" className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Campaigns</Link>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><h1 className="text-[26px] font-extrabold tracking-tight">{c.name}</h1>
          <p className="mt-1 text-[14px] text-muted-foreground">{JOURNEY_LABEL[c.journey] ?? titleCase(c.journey)} · {CHANNEL[c.channel] ?? titleCase(c.channel)} · {c.offer_pct ? `${c.offer_pct}% off with ${c.code}` : "no discount"} · {pct(c.holdout_pct, 0)} holdout</p></div>
        <div className="flex gap-2">
          {step === 0 && <Button variant="primary" onClick={() => send.mutate()} disabled={send.isPending}><Send />Send campaign</Button>}
          {step === 1 && <Button variant="primary" onClick={() => sim.mutate()} disabled={sim.isPending}><FlaskConical />Measure results</Button>}
          {step === 2 && <Button onClick={() => sim.mutate()} disabled={sim.isPending}><RefreshCcw />Re-run measurement</Button>}
        </div>
      </div>
      <div className="flex items-center gap-2 text-[13px]">{["Draft", "Sent", "Measured"].map((s, i) => (
        <div key={s} className="flex items-center gap-2"><span className={cn("grid size-6 place-items-center rounded-full text-[12px] font-bold", i <= step ? "bg-primary text-white" : "bg-muted text-muted-foreground")}>{i + 1}</span>
          <span className={i <= step ? "font-semibold" : "text-muted-foreground"}>{s}</span>{i < 2 && <span className="mx-1 h-px w-8 bg-border" />}</div>))}</div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Group A" value={num(g.A ?? 0)} hint="variant A" /><Stat label="Group B" value={num(g.B ?? 0)} hint="variant B" />
        <Stat label="Holdout (not messaged)" value={num(g.control ?? 0)} hint="the baseline" /><Stat label="Excluded by guardrails" value={num(g.excluded ?? 0)} hint={q.data.exclusions.map((e) => `${e.customers} ${e.reason}`).join(" · ") || "none"} />
      </div>
      {r && <ResultsView r={r} />}
      {!r && step === 1 && <Card className="p-5 text-[13.5px] text-muted-foreground"><BarChart3 className="mr-2 inline size-4 text-primary" />Sent. Click <b>Measure results</b> to simulate 14 days of customer responses (simulated customers: the statistics are real, the people aren't).</Card>}
      <Card><CardHeader title="Messages" description="Rendered for real customers from the templates" />
        <CardBody className="grid gap-3 md:grid-cols-2">{q.data.examples.map((e, i) => (
          <div key={i} className="rounded-2xl border bg-background p-3.5"><div className="mb-1.5 flex items-center gap-2 text-[12px]"><Badge tone="primary">Variant {e.grp}</Badge><span className="text-muted-foreground">to {e.name} · {e.language}</span></div>
            <p className="text-[13.5px] whitespace-pre-wrap">{e.message}</p></div>))}</CardBody></Card>
    </div>
  );
}

function ResultsView({ r }: { r: Results }) {
  const maxHi = Math.max(...r.groups.map((x) => x.ci_high), 0.01);
  return (
    <div className="space-y-4">
      <div className={cn("rounded-3xl p-5 text-[14.5px]", r.significant && r.net_profit > 0 ? "bg-success-soft text-success" : r.significant ? "bg-warning-soft text-warning" : "bg-muted text-foreground")}>
        <b>Verdict:</b> {r.verdict} <span className="mt-1 block text-[12px] opacity-70">Simulated customers: the statistics are real, the responses come from the simulator.</span></div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Uplift vs holdout" value={`${r.abs_uplift >= 0 ? "+" : ""}${(r.abs_uplift * 100).toFixed(1)} pts`} hint={`p = ${r.p_value.toFixed(3)} ${r.significant ? "· significant" : "· could be luck"}`} />
        <Stat label="Extra orders caused" value={num(Math.round(r.incremental_orders))} hint={`vs ${num(r.naive_orders)} orders a naive report would claim`} />
        <Stat label="Net profit" value={<span className={r.net_profit < 0 ? "text-danger" : ""}>{inr(r.net_profit)}</span>} hint={r.significant ? `ROI ${r.roi != null ? pct(r.roi, 0) : "–"}` : "not reliable: not significant"} />
        <Stat label="Costs" value={inr(r.message_cost + r.discount_cost)} hint={`messages ${inr(r.message_cost)} · discounts ${inr(r.discount_cost)}`} />
      </div>
      <Card><CardHeader title="Conversion by group" description="Bars show the 95% confidence range: overlapping ranges mean the difference may be luck" />
        <CardBody className="space-y-4">{r.groups.map((x) => (
          <div key={x.group}><div className="flex justify-between text-[13px]"><span className="font-semibold">{x.group === "control" ? "Holdout" : `Variant ${x.group}`} <span className="font-normal text-muted-foreground">· {num(x.conversions)}/{num(x.customers)}</span></span>
            <span className="font-bold tabular">{pct(x.rate)}</span></div>
            <div className="relative mt-1.5 h-3 rounded-full bg-muted">
              <div className={cn("absolute h-full rounded-full opacity-35", x.group === "control" ? "bg-ink" : "bg-primary")} style={{ left: `${(x.ci_low / maxHi) * 100}%`, width: `${((x.ci_high - x.ci_low) / maxHi) * 100}%` }} />
              <div className={cn("absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card", x.group === "control" ? "bg-ink" : "bg-primary")} style={{ left: `${(x.rate / maxHi) * 100}%` }} />
            </div></div>))}
          <p className="text-[12.5px] text-muted-foreground">A vs B: p = {r.ab.p_value.toFixed(3)} · {r.ab.winner ? `variant ${r.ab.winner} wins` : "no clear winner yet"}. Detecting a 30% lift needs ~{num(r.sample_size_needed_per_group)} customers per group.</p>
        </CardBody></Card>
    </div>
  );
}
