import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AtSign, Clock, ExternalLink, MonitorPlay, Newspaper, Plus, Quote, Radar, RefreshCw, Search, ShieldAlert, Sparkles,
  ThumbsDown, ThumbsUp, Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ErrorNote, Stat } from "@/components/data";
import { EmptyState, PageHeader } from "@/components/empty";
import { ProductThumb } from "@/components/product";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { del, get, post, put, qs } from "@/lib/api";
import { ago, num, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

type Split = { mentions: number; positive: number; neutral: number; negative: number; mixed: number };
type Run = { id: number; started_at: string; finished_at: string | null; status: string; trigger: string; fetched: number; new: number;
  labelled: number; youtube_units: number; report: { sources?: Record<string, { fetched: number; error: string | null }>; purged?: number; error?: string } | null };
type Term = { id: number; term: string; kind: string; active: number };
type Brief = { id: number; created_at: string; method: "google_search" | "collected"; text: string; sources: { n: number; title: string; url: string }[];
  warnings: string[]; note?: string | null };
type Overview = {
  days: number; last_run: Run | null; every_hours: number; enabled_sources: string[]; filtered: { ads: number; off_topic: number };
  summary: Split & { alerts: number; complaints: number; side_effects: number; net: number | null };
  by_source: (Split & { source: string })[]; by_term: (Split & { term: string; kind: string })[];
  aspects: (Split & { aspect: string; label: string })[];
  ingredients: (Split & { ingredient: string; products: { id: number; name: string; image_url: string | null; price: number }[] })[];
  alerts: { id: number; source: string; url: string; author: string; text: string; alert: string; term: string; published_at: string }[];
  sources: { source: string; label: string; ready: boolean; needs: string | null }[]; brief: Brief | null; terms: Term[];
};
type Mention = { id: number; source: string; url: string; author: string | null; title: string | null; text: string; published_at: string | null;
  fetched_at: string; likes: number; term: string; term_kind: string; language: string | null; sentiment: string | null; kind: string | null;
  aspects: string[]; ingredients: string[]; gist: string | null; alert: string | null; relevant: number | null; labelled_by: string | null };

const SOURCE = { youtube: { label: "YouTube", icon: MonitorPlay }, bluesky: { label: "Bluesky", icon: AtSign }, news: { label: "Google News", icon: Newspaper } } as const;
const SENTIMENT_TONE = { positive: "good", negative: "bad", mixed: "warn", neutral: "neutral" } as const;
const ALERT_LABEL: Record<string, string> = { skin_reaction: "Skin reaction", legal_threat: "Legal threat" };

export function Listening() {
  const qc = useQueryClient();
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ["listening", days], queryFn: () => get<Overview>(`/api/v1/listening${qs({ days })}`),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => (query.state.data?.last_run?.status === "running" ? 3000 : false) });
  const running = q.data?.last_run?.status === "running";
  const wasRunning = useRef(false);
  useEffect(() => {     // tell the user once, when a scan they're watching finishes
    if (wasRunning.current && !running && q.data?.last_run) {
      const r = q.data.last_run;
      (r.status === "error" ? toast.error : toast.success)(`Scan ${r.status === "ok" ? "finished" : r.status}: ${r.new} new mentions.`);
      qc.invalidateQueries({ queryKey: ["listening-feed"] });
    }
    wasRunning.current = running;
  }, [running, q.data, qc]);
  const scan = useMutation({ mutationFn: () => post("/api/v1/listening/scan"),
    onSuccess: () => { toast("Scanning… this takes a minute."); qc.invalidateQueries({ queryKey: ["listening"] }); } });

  const d = q.data;
  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6 lg:p-8">
      <PageHeader title="Social listening" description="What people say about your brand and your market on YouTube, Bluesky and in the news. Public sources only, read on a schedule."
        actions={<div className="flex items-center gap-2">
          <Segmented value={days} onChange={setDays} options={[{ value: 7, label: "7 days" }, { value: 30, label: "30 days" }]} />
          <Button variant="primary" onClick={() => scan.mutate()} disabled={running || scan.isPending}>
            <RefreshCw className={cn(running && "animate-spin")} />{running ? "Scanning…" : "Scan now"}</Button></div>} />
      {q.isError && <ErrorNote error={q.error} />}
      {!d ? <Skeleton className="h-96 rounded-2xl" /> : (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-5">
            {d.summary.mentions === 0 ? (
              <Card><EmptyState icon={Radar} title={d.last_run ? "No mentions in this period" : "No scan yet"}
                body={<>Click <b>Scan now</b> to read what people are saying about your watch terms. Add your brand, products, categories or competitors on the right.</>} /></Card>
            ) : <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <Stat label="Mentions" value={num(d.summary.mentions)} hint={`${d.by_source.map((s) => `${num(s.mentions)} ${SOURCE[s.source as keyof typeof SOURCE]?.label ?? s.source}`).join(" · ")}${(d.filtered.ads + d.filtered.off_topic) ? ` · ${num(d.filtered.ads + d.filtered.off_topic)} ads/off-topic left out` : ""}`} />
                <Stat label="Net sentiment" value={d.summary.net == null ? "–" : `${d.summary.net > 0 ? "+" : ""}${d.summary.net}`}
                  hint={`${num(d.summary.positive)} positive · ${num(d.summary.negative)} negative (−100 to +100)`} />
                <Stat label="Complaints" value={num(d.summary.complaints)} hint={`${num(d.summary.side_effects)} mention side effects`} />
                <Stat label="Alerts about your brand" value={num(d.summary.alerts)} hint={d.summary.alerts ? "a person should look today" : "nothing urgent"} />
              </div>
              {d.alerts.length > 0 && (
                <Card className="border-danger/30"><CardHeader title={<span className="flex items-center gap-2 text-danger"><ShieldAlert className="size-4" />Alerts about your brand</span>}
                  description="Skin reactions or legal threats in public posts about you. Reply publicly with care, then move it to a private channel." />
                  <CardBody className="space-y-2">{d.alerts.map((a) => (
                    <a key={a.id} href={a.url} target="_blank" rel="noopener noreferrer" className="flex gap-3 rounded-xl border p-3 text-[13px] hover:bg-muted/50">
                      <Badge tone="bad" className="shrink-0">{ALERT_LABEL[a.alert] ?? titleCase(a.alert)}</Badge>
                      <span className="min-w-0 flex-1 line-clamp-2">{a.text}</span><ExternalLink className="size-3.5 shrink-0 text-subtle-foreground" /></a>))}
                  </CardBody></Card>)}
              <div className="grid gap-5 lg:grid-cols-2">
                <Card><CardHeader title="What people talk about" description="Each mention can touch several topics. Counted in code." />
                  <CardBody className="space-y-3">{d.aspects.length ? d.aspects.slice(0, 7).map((a) => <TopicRow key={a.aspect} label={a.label} s={a} max={d.aspects[0].mentions} />)
                    : <p className="text-[13px] text-muted-foreground">No topics yet.</p>}</CardBody></Card>
                <Card><CardHeader title="Ingredients in the conversation" description="And your products that contain them" />
                  <CardBody className="space-y-3">{d.ingredients.length ? d.ingredients.slice(0, 6).map((i) => (
                    <div key={i.ingredient} className="space-y-1.5">
                      <TopicRow label={titleCase(i.ingredient)} s={i} max={d.ingredients[0].mentions} />
                      {i.products.length > 0 && <div className="flex flex-wrap gap-1.5 pl-1">{i.products.map((p) => (
                        <span key={p.id} className="flex items-center gap-1.5 rounded-full border bg-card py-0.5 pr-2 pl-0.5 text-[11.5px] text-muted-foreground">
                          <ProductThumb src={p.image_url} alt="" className="size-5 rounded-full" />{p.name}</span>))}</div>}
                    </div>)) : <p className="text-[13px] text-muted-foreground">No ingredients mentioned yet.</p>}</CardBody></Card>
              </div>
              <BriefCard brief={d.brief} />
            </>}
            <Feed days={days} terms={d.terms} filtered={d.filtered} />
          </div>
          <div className="space-y-5"><Setup d={d} /></div>
        </div>)}
    </div>
  );
}

/** One topic: how often it comes up, and how many of those are positive / negative (with icons, never colour alone). */
function TopicRow({ label, s, max }: { label: string; s: Split; max: number }) {
  return (
    <div className="text-[13px]">
      <div className="flex items-center gap-2"><span className="flex-1 font-medium">{label}</span>
        <span className="flex items-center gap-1 tabular text-success"><ThumbsUp className="size-3" />{s.positive}</span>
        <span className="flex items-center gap-1 tabular text-danger"><ThumbsDown className="size-3" />{s.negative}</span>
        <span className="w-8 text-right font-semibold tabular">{s.mentions}</span></div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted" title={`${s.mentions} mentions`}>
        <div className="h-full rounded-full bg-[var(--chart-1)]" style={{ width: `${(100 * s.mentions) / Math.max(max, 1)}%` }} /></div>
    </div>
  );
}

function BriefCard({ brief }: { brief: Brief | null }) {
  const qc = useQueryClient();
  const write = useMutation({ meta: { inlineError: true }, mutationFn: () => post<{ brief: Brief }>("/api/v1/listening/brief", { method: "auto" }),
    onSuccess: (r) => { if (r.brief.note) toast(r.brief.note); qc.invalidateQueries({ queryKey: ["listening"] }); } });
  const b = write.data?.brief ?? brief;
  // "[3]" or "[1, 4]": each number links to the post it cites.
  const linked = (text: string) => text.split(/(\[\d{1,3}(?:\s*,\s*\d{1,3})*\])/).map((part, i) => {
    if (!/^\[\d/.test(part)) return part;
    const nums = part.slice(1, -1).split(",").map((n) => Number(n.trim()));
    return <span key={i}>[{nums.map((n, j) => {
      const src = b?.sources.find((s) => s.n === n);
      return <span key={n}>{j > 0 && ", "}{src ? <a href={src.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-primary hover:underline">{n}</a> : n}</span>;
    })}]</span>;
  });
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Sparkles className="size-4 text-primary" />AI brief</span>}
        description={b ? (b.method === "google_search" ? "Gemini searched Google and cites the pages it used" : "Written only from the mentions collected here, with links")
          : "A short summary of what people say, with sources"}
        action={<Button size="sm" variant="secondary" onClick={() => write.mutate()} disabled={write.isPending}>
          <Sparkles className="text-primary" />{write.isPending ? "Writing…" : b ? "Write again" : "Write brief"}</Button>} />
      <CardBody className="space-y-3 text-[13.5px]">
        {write.isError && <ErrorNote error={write.error} />}
        {b ? <>
          <div className="space-y-1.5 whitespace-pre-line leading-relaxed">{linked(b.text)}</div>
          {b.warnings.map((w) => <p key={w} className="text-[12px] text-warning">⚠ {w}</p>)}
          {b.method === "google_search" && b.sources.length > 0 && <div className="flex flex-wrap gap-1.5 pt-1">{b.sources.map((s) => (
            <a key={s.n} href={s.url} target="_blank" rel="noopener noreferrer" className="rounded-full border px-2 py-0.5 text-[11.5px] text-muted-foreground hover:text-foreground">[{s.n}] {s.title}</a>))}</div>}
          <p className="text-[11.5px] text-subtle-foreground">{b.method === "google_search" ? "Google Search" : "Collected mentions"} · {ago(b.created_at)} · AI-written: check the links before acting</p>
        </> : <p className="text-muted-foreground">No brief yet. Numbers in a brief are checked against the counts above; links point to the real posts.</p>}
      </CardBody>
    </Card>
  );
}

function Feed({ days, terms, filtered }: { days: number; terms: Term[]; filtered: Overview["filtered"] }) {
  const [noise, setNoise] = useState(false);
  const [source, setSource] = useState("");
  const [sentiment, setSentiment] = useState("");
  const [term, setTerm] = useState("");
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => { const t = setTimeout(() => setSearch(text.trim()), 250); return () => clearTimeout(t); }, [text]);
  const q = useQuery({ queryKey: ["listening-feed", days, source, sentiment, term, search, noise],
    queryFn: () => get<{ total: number; mentions: Mention[] }>(`/api/v1/listening/mentions${qs({ days, source: source || null, sentiment: sentiment || null, term: term || null, q: search || null, noise: noise || null, limit: 60 })}`),
    placeholderData: keepPreviousData });
  const select = "h-9 rounded-full border bg-card px-3 text-[13px]";
  return (
    <Card>
      <CardHeader title="Mentions" description={q.data ? `${num(q.data.total)} in the last ${days} days` : "…"}
        action={(filtered.ads + filtered.off_topic) > 0 && <label className="flex cursor-pointer items-center gap-1.5 text-[12.5px] text-muted-foreground">
          <input type="checkbox" checked={noise} onChange={(e) => setNoise(e.target.checked)} className="accent-[var(--primary)]" />
          Show {num(filtered.ads)} ads and {num(filtered.off_topic)} off-topic</label>} />
      <div className="flex flex-wrap items-center gap-2 border-y px-4 py-3">
        <div className="relative min-w-[180px] flex-1"><Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-subtle-foreground" />
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Search mentions" className="pl-9" /></div>
        <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="Source" className={select}><option value="">All sources</option>
          {Object.entries(SOURCE).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <select value={sentiment} onChange={(e) => setSentiment(e.target.value)} aria-label="Sentiment" className={select}><option value="">Any sentiment</option>
          {["positive", "negative", "mixed", "neutral"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}</select>
        <select value={term} onChange={(e) => setTerm(e.target.value)} aria-label="Watch term" className={select}><option value="">All terms</option>
          {terms.map((t) => <option key={t.id} value={t.term}>{t.term}</option>)}</select>
      </div>
      <div className="divide-y">
        {q.data?.mentions.map((m) => <MentionRow key={m.id} m={m} />)}
        {q.data && q.data.mentions.length === 0 && <p className="p-6 text-center text-[13px] text-muted-foreground">No mentions match.</p>}
        {!q.data && <Skeleton className="m-4 h-40 rounded-xl" />}
      </div>
    </Card>
  );
}

function MentionRow({ m }: { m: Mention }) {
  const S = SOURCE[m.source as keyof typeof SOURCE];
  return (
    <div className="flex gap-3 px-4 py-3.5" data-testid="mention">
      <div className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground" title={S?.label}>{S ? <S.icon className="size-4" /> : null}</div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted-foreground">
          <span className="font-semibold text-foreground">{m.author || S?.label}</span>
          <span>{ago(m.published_at ?? m.fetched_at)}</span>
          {m.alert && <Badge tone="bad"><ShieldAlert />{ALERT_LABEL[m.alert] ?? m.alert}</Badge>}
          {m.sentiment && <Badge tone={SENTIMENT_TONE[m.sentiment as keyof typeof SENTIMENT_TONE] ?? "neutral"}>
            {m.sentiment === "positive" ? <ThumbsUp /> : m.sentiment === "negative" ? <ThumbsDown /> : null}{titleCase(m.sentiment)}</Badge>}
          {m.kind && m.kind !== "other" && <Badge tone="outline">{titleCase(m.kind)}</Badge>}
          {m.relevant === 0 && <Badge tone="warn">off-topic</Badge>}
          <span className="rounded bg-muted px-1.5 text-[11px]">{m.term}</span>
          {m.likes > 0 && <span className="flex items-center gap-1"><ThumbsUp className="size-3" />{num(m.likes)}</span>}
        </div>
        {m.title && <div className="mt-1 truncate text-[12px] text-subtle-foreground">on “{m.title}”</div>}
        <p className="mt-1 line-clamp-3 text-[13.5px] whitespace-pre-line">{m.text}</p>
        {m.gist && m.language !== "en" && <p className="mt-1 flex items-start gap-1.5 text-[12.5px] text-muted-foreground"><Quote className="mt-0.5 size-3 shrink-0" />{m.gist}</p>}
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {m.aspects.filter((a) => a !== "other").map((a) => <span key={a} className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">{titleCase(a)}</span>)}
          {m.ingredients.map((i) => <span key={i} className="rounded-full bg-primary-soft px-2 py-0.5 text-[11px] text-primary">{i}</span>)}
          <a href={m.url} target="_blank" rel="noopener noreferrer" className="ml-auto flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground">Open<ExternalLink className="size-3" /></a>
        </div>
      </div>
    </div>
  );
}

const SCHEDULE = [{ value: 0, label: "Off" }, { value: 6, label: "Every 6 h" }, { value: 12, label: "Every 12 h" }, { value: 24, label: "Daily" }];

function Setup({ d }: { d: Overview }) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["listening"] });
  const [term, setTerm] = useState("");
  const [kind, setKind] = useState("category");
  const add = useMutation({ mutationFn: () => post("/api/v1/listening/terms", { term, kind }), onSuccess: () => { setTerm(""); refresh(); } });
  const toggle = useMutation({ mutationFn: (t: Term) => post(`/api/v1/listening/terms/${t.id}`, { active: !t.active }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: number) => del(`/api/v1/listening/terms/${id}`), onSuccess: refresh });
  const save = useMutation({ mutationFn: (s: { every_hours: number; sources: string[] }) => put("/api/v1/listening/settings", s),
    onSuccess: () => { toast.success("Saved."); refresh(); } });
  const r = d.last_run;
  return <>
    <Card><CardHeader title="Watch terms" description="Brand terms raise alerts. Category, product and competitor terms are market research." />
      <CardBody className="space-y-3">
        <div className="space-y-1.5">{d.terms.map((t) => (
          <div key={t.id} className={cn("flex items-center gap-2 rounded-xl border px-3 py-2 text-[13px]", !t.active && "opacity-50")}>
            <input type="checkbox" checked={!!t.active} onChange={() => toggle.mutate(t)} aria-label={`Watch ${t.term}`} className="accent-[var(--primary)]" />
            <span className="min-w-0 flex-1 truncate font-medium">{t.term}</span>
            <Badge tone={t.kind === "brand" ? "primary" : "outline"}>{t.kind}</Badge>
            <button onClick={() => remove.mutate(t.id)} aria-label={`Remove ${t.term}`} className="text-subtle-foreground hover:text-danger"><Trash2 className="size-3.5" /></button>
          </div>))}</div>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (term.trim()) add.mutate(); }}>
          <Input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="e.g. a competitor's name" maxLength={60} className="h-9 flex-1" />
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind" className="h-9 rounded-full border bg-card px-2 text-[12.5px]">
            {["brand", "product", "category", "competitor"].map((k) => <option key={k}>{k}</option>)}</select>
          <Button size="icon" type="submit" aria-label="Add term" disabled={!term.trim() || add.isPending}><Plus /></Button>
        </form>
      </CardBody></Card>
    <Card><CardHeader title="Sources" description="Official, allowed access only" />
      <CardBody className="space-y-2">
        {d.sources.map((s) => {
          const on = d.enabled_sources.includes(s.source);
          const err = r?.report?.sources?.[s.source]?.error;
          const S = SOURCE[s.source as keyof typeof SOURCE];
          return (
            <div key={s.source} className="rounded-xl border px-3 py-2 text-[13px]">
              <label className="flex cursor-pointer items-center gap-2">
                <input type="checkbox" checked={on} className="accent-[var(--primary)]"
                  onChange={() => save.mutate({ every_hours: d.every_hours, sources: on ? d.enabled_sources.filter((x) => x !== s.source) : [...d.enabled_sources, s.source] })} />
                {S && <S.icon className="size-4 text-muted-foreground" />}<span className="flex-1 font-medium">{s.label}</span>
                {!s.ready ? <Badge tone="warn">needs key</Badge> : err && on ? <Badge tone="bad">error</Badge> : on ? <Badge tone="good">ready</Badge> : null}
              </label>
              {s.needs && <p className="mt-1 pl-6 text-[11.5px] text-muted-foreground">Add {s.needs}</p>}
              {err && on && s.ready && <p className="mt-1 pl-6 text-[11.5px] text-danger">{err}</p>}
            </div>);
        })}
        <p className="text-[11.5px] leading-relaxed text-muted-foreground">Not included on purpose: LinkedIn, Facebook, Instagram and marketplace reviews. Reading them needs approved access for a registered business; scraping breaks their terms.</p>
      </CardBody></Card>
    <Card><CardHeader title="Schedule" description="The agent scans on its own while the server runs" />
      <CardBody className="space-y-3 text-[13px]">
        <Segmented value={d.every_hours} onChange={(v) => save.mutate({ every_hours: v, sources: d.enabled_sources })} options={SCHEDULE} />
        {r ? <div className="rounded-xl bg-muted/60 p-3 text-[12.5px]">
          <div className="flex items-center gap-1.5 font-semibold"><Clock className="size-3.5" />Last scan {ago(r.started_at)}
            <Badge tone={r.status === "ok" ? "good" : r.status === "running" ? "primary" : r.status === "partial" ? "warn" : "bad"} className="ml-auto">{r.status}</Badge></div>
          {r.status !== "running" && <div className="mt-1 text-muted-foreground">{num(r.fetched)} read · {num(r.new)} new · {num(r.labelled)} labelled
            {r.youtube_units ? ` · ${num(r.youtube_units)} of 10,000 YouTube units` : ""}{r.report?.purged ? ` · ${r.report.purged} expired removed` : ""}</div>}
          {r.report?.error && <div className="mt-1 text-danger">{r.report.error}</div>}
        </div> : <p className="text-muted-foreground">No scan yet.</p>}
        <p className="text-[11.5px] text-muted-foreground">YouTube comments are deleted after 30 days (YouTube's rules); other mentions after 90.</p>
      </CardBody></Card>
  </>;
}
