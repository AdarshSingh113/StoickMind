import {
  ArrowRight, BadgeCheck, Bot, ChartNoAxesCombined, ChevronLeft, Database, Flame, Handshake, Inbox, LifeBuoy, Lock,
  Megaphone, MessageSquareText, PackageCheck, Repeat, ShieldCheck, Sparkles, Store, Wand2,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Logo } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Msg = { from: "bot" | "me"; text: string };
type Module = {
  key: string; label: string[]; icon: typeof Bot; title: string; context: string[]; preview: ReactNode;
};

function Phone({ name, sub, msgs, chips }: { name: string; sub: string; msgs: Msg[]; chips?: string[] }) {
  return (
    <div className="mx-auto w-full max-w-[330px] rounded-[28px] border bg-card p-2 shadow-[0_24px_60px_-24px_rgba(60,30,0,0.35)]">
      <div className="rounded-[22px] border bg-background">
        <div className="flex items-center gap-2.5 border-b bg-card px-4 py-3 rounded-t-[22px]">
          <ChevronLeft className="size-4 text-muted-foreground" />
          <div className="grid size-8 place-items-center rounded-full bg-ink text-[13px] font-extrabold text-primary">G</div>
          <div><div className="flex items-center gap-1 text-[13px] font-bold">{name}<BadgeCheck className="size-3.5 text-sky-500" /></div>
            <div className="text-[11px] text-muted-foreground">{sub}</div></div>
        </div>
        <div className="space-y-2 px-3 py-4 text-[12.5px] leading-relaxed">
          {msgs.map((m, i) => (
            <div key={i} className={cn("flex", m.from === "me" ? "justify-end" : "justify-start")}>
              <div className={cn("max-w-[85%] rounded-2xl px-3 py-2", m.from === "me" ? "rounded-br-md bg-primary text-white"
                : "rounded-bl-md border bg-card")}>{m.text}</div>
            </div>
          ))}
          {chips && <div className="flex flex-wrap justify-end gap-1.5 pt-1">{chips.map((c) =>
            <span key={c} className="rounded-full border border-primary/40 bg-primary-soft px-2.5 py-1 text-[11.5px] font-medium text-primary">{c}</span>)}</div>}
        </div>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-3xl border bg-card p-5 shadow-[0_18px_50px_-30px_rgba(60,30,0,0.3)]">
      <div className="mb-3 text-[13px] font-bold">{title}</div>
      {children}
    </div>
  );
}

const bar = (label: string, pct: number, value: string, tone = "bg-primary") => (
  <div key={label} className="space-y-1">
    <div className="flex justify-between text-[12px]"><span>{label}</span><span className="font-semibold tabular">{value}</span></div>
    <div className="h-2 rounded-full bg-muted"><div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} /></div>
  </div>
);

const MODULES: Module[] = [
  { key: "shop", label: ["Shopping", "Agent"], icon: Handshake, title: "Kavya recommends from your real catalogue",
    context: ["Ask about skin type and concern before recommending.", "Only quote prices returned by search_products.",
      "Reply in the customer's language: English, Hinglish or Hindi."],
    preview: <Phone name="Glow & Co." sub="Shopping assistant · online" msgs={[
      { from: "me", text: "oily skin ke liye koi achha face wash batao" },
      { from: "bot", text: "Oily skin ke liye Neem & Tea Tree Oil-Control Face Wash best rahega: oil control karta hai aur pores clean rakhta hai." },
      { from: "me", text: "aur serum?" },
      { from: "bot", text: "Salicylic Acid 2% Acne Serum saath mein lo. Dono milake routine complete ho jayega ✨" }]} /> },
  { key: "quiz", label: ["Skin", "Quiz"], icon: Wand2, title: "Ira runs a guided skin quiz",
    context: ["Ask one question at a time: feel by noon, concern, sensitivity, budget.",
      "Save the skin profile so every agent remembers it.", "End with a routine of in-stock products."],
    preview: <Phone name="Glow & Co." sub="Skin quiz · Ira" msgs={[
      { from: "bot", text: "How does your skin feel by noon?" }, { from: "me", text: "Shiny on the forehead" },
      { from: "bot", text: "And your cheeks: tight, normal or oily?" }]} chips={["Tight", "Normal", "Oily"]} /> },
  { key: "help", label: ["AI", "Helpdesk"], icon: LifeBuoy, title: "Asha resolves support with policies, not guesses",
    context: ["Verify guests with order number + last 4 phone digits.", "Search the policy before stating any timeline.",
      "Escalate to a person for allergies, anger or anything unclear."],
    preview: <Phone name="Glow & Co." sub="Customer care · Asha" msgs={[
      { from: "me", text: "Where is my order KTL-103245?" },
      { from: "bot", text: "It's out for delivery with Delhivery today and should reach you by 7 pm." },
      { from: "me", text: "Great, thanks!" }]} /> },
  { key: "orders", label: ["Order", "Management"], icon: PackageCheck, title: "Actions with limits enforced in code",
    context: ["Cancel before shipping; refunds up to ₹1,000 go through automatically.", "Bigger refunds wait for a person's approval.",
      "Max 10% coupon, one per customer per 30 days."],
    preview: <Panel title="Recent AI actions">
      {[["Cancel KTL-103311", "Done", "bg-success-soft text-success"], ["Refund ₹1,499 · damaged serum", "Needs approval", "bg-warning-soft text-warning"],
        ["Coupon 10% · cancel-and-save", "Done", "bg-success-soft text-success"], ["Refund ₹5,000 request", "Blocked: over limit", "bg-danger-soft text-danger"]].map(([a, s, c]) => (
        <div key={a} className="flex items-center justify-between border-b py-2.5 text-[13px] last:border-0"><span>{a}</span>
          <span className={cn("rounded-full px-2 py-0.5 text-[11.5px] font-semibold", c)}>{s}</span></div>))}
    </Panel> },
  { key: "cdp", label: ["Customer", "CDP"], icon: Database, title: "Every customer, scored by machine learning",
    context: ["RFM segments from real orders.", "Churn risk and 12-month value, validated on time-based backtests.",
      "COD refusal (RTO) risk before you ship."],
    preview: <Panel title="Segments · 1,500 customers"><div className="space-y-3">
      {bar("Champions", 82, "307")}{bar("Loyal", 58, "214", "bg-ink")}{bar("At risk", 44, "163", "bg-[var(--chart-3)]")}{bar("Lost", 71, "266", "bg-[var(--chart-6)]")}</div></Panel> },
  { key: "retention", label: ["Retention", "Journeys"], icon: Repeat, title: "Four journeys that bring customers back",
    context: ["Replenishment when a product should be running out.", "Win-back for valuable customers drifting away.",
      "Cross-sell to complete a routine; second-order nudges."],
    preview: <Panel title="Who to message today"><div className="space-y-3">
      {bar("Replenishment", 90, "331 customers")}{bar("Win-back", 62, "230 customers", "bg-ink")}{bar("Complete your routine", 100, "717 customers", "bg-[var(--chart-3)]")}{bar("Second order", 22, "61 customers", "bg-[var(--chart-4)]")}</div></Panel> },
  { key: "campaigns", label: ["AI", "Campaigns"], icon: Megaphone, title: "AI-written A/B messages, measured against a holdout",
    context: ["Prices and discounts come from placeholders, never typed by the AI.", "15% discount cap, 7-day frequency cap.",
      "Uplift, significance and ROI vs a control group."],
    preview: <Phone name="Glow & Co." sub="WhatsApp · campaign" msgs={[
      { from: "bot", text: "Hi Neha! Your Vitamin C Brightening Face Wash should be running low by now. Restock today and keep that glow going ✨ Use code KTL710 for 10% off." }]}
      chips={["Shop now", "Stop offers"]} /> },
  { key: "inbox", label: ["Omnichannel", "Inbox"], icon: Inbox, title: "WhatsApp, Telegram and your website in one inbox",
    context: ["New messages appear live.", "Take over any chat: the AI goes quiet until you hand it back.",
      "Escalated chats are flagged so nobody waits."],
    preview: <Panel title="Inbox · live">{[["Ananya", "The moisturizer gave me a rash…", "Needs you"], ["Rahul", "serum ka price kya hai?", "Kavya"], ["Website visitor", "oily on the forehead, dry cheeks", "Ira"]].map(([n, t, b]) => (
      <div key={n} className="flex items-center gap-3 border-b py-2.5 last:border-0"><div className="grid size-8 place-items-center rounded-full bg-primary-soft text-[12px] font-bold text-primary">{n[0]}</div>
        <div className="min-w-0 flex-1"><div className="text-[13px] font-semibold">{n}</div><div className="truncate text-[12px] text-muted-foreground">{t}</div></div>
        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", b === "Needs you" ? "bg-danger-soft text-danger" : "bg-muted text-muted-foreground")}>{b}</span></div>))}</Panel> },
  { key: "ask", label: ["Ask your", "data"], icon: MessageSquareText, title: "Questions in plain English, answers you can verify",
    context: ["Read-only SQL with names, phones and addresses blocked column by column.", "Every number in the summary is checked against the result.",
      "The SQL is always shown."],
    preview: <Panel title="“Which city tier refuses the most COD orders?”"><div className="space-y-3">
      {bar("Tier 3", 100, "33.9%")}{bar("Tier 2", 59, "19.9%", "bg-ink")}{bar("Tier 1", 45, "15.4%", "bg-[var(--chart-6)]")}</div>
      <p className="mt-3 text-[12px] text-muted-foreground">Tier 3 has the highest RTO rate at 33.9% of 425 COD orders. <span className="font-semibold text-success">✓ numbers checked</span></p></Panel> },
  { key: "studio", label: ["Agent", "Studio"], icon: Bot, title: "Build and version your own agents",
    context: ["Instructions, goal, success criteria and tools as configuration.", "Every save is a version; roll back in one click.",
      "Test in a playground and let an LLM judge score it."],
    preview: <Panel title="Versions · Kavya">{[["v4", "Tightened price rule", "Live"], ["v3", "Added Hinglish examples", ""], ["v2", "New tool: build_routine", ""]].map(([v, n, s]) => (
      <div key={v} className="flex items-center gap-3 border-b py-2.5 text-[13px] last:border-0"><span className="rounded-md bg-muted px-1.5 font-mono text-[12px]">{v}</span>{n}
        {s && <span className="ml-auto rounded-full bg-success-soft px-2 py-0.5 text-[11px] font-semibold text-success">{s}</span>}</div>))}</Panel> },
];

const GUARDS = [
  { icon: ShieldCheck, title: "Grounded prices", body: "A reply quoting a price that no tool returned is blocked and corrected." },
  { icon: Lock, title: "Limits in code", body: "Refund limits, discount caps and approvals can't be talked around." },
  { icon: Sparkles, title: "Language that matches", body: "Hinglish in, Hinglish out: detected in code, repaired if missed." },
  { icon: ChartNoAxesCombined, title: "Measured, not guessed", body: "Every AI call traced: speed, cost, safety checks, judge scores." },
  { icon: Flame, title: "RTO before it happens", body: "A model flags risky COD orders so you confirm them first." },
  { icon: Database, title: "Privacy by default", body: "Analytics can count customers but never read their phone numbers." },
];

export function Landing() {
  const [active, setActive] = useState(MODULES[0].key);
  const m = MODULES.find((x) => x.key === active)!;
  return (
    <div className="min-h-dvh bg-background">
      <header className="sticky top-0 z-30 border-b border-transparent bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-18 max-w-7xl items-center gap-8 px-5 py-4">
          <Logo />
          <nav className="hidden items-center gap-7 text-[15px] font-medium text-foreground/80 md:flex">
            <a href="#product" className="hover:text-foreground">Product</a>
            <a href="#guardrails" className="hover:text-foreground">Guardrails</a>
            <a href="#how" className="hover:text-foreground">How it works</a>
            <a href="/store" className="flex items-center gap-1.5 hover:text-foreground"><Sparkles className="size-4 text-primary" />Live demo</a>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Link to="/login" className="hidden sm:block"><Button variant="ghost">Sign in</Button></Link>
            <Link to="/app"><Button variant="primary" size="lg">Open dashboard</Button></Link>
          </div>
        </div>
      </header>

      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-x-0 -top-40 mx-auto h-[620px] max-w-6xl rounded-full bg-[radial-gradient(closest-side,rgba(242,120,12,0.16),transparent)] blur-2xl" />
        <div className="relative mx-auto max-w-6xl px-5 pt-14 pb-10 text-center sm:pt-20">
          <span className="inline-flex items-center gap-2 rounded-full border bg-card px-3.5 py-1.5 text-[13px] font-medium text-muted-foreground shadow-card">
            <span className="size-1.5 rounded-full bg-primary" /> Built for Indian D2C brands · English, Hinglish & Hindi
          </span>
          <h1 className="mt-7 text-[40px] leading-[1.05] font-extrabold tracking-[-0.025em] sm:text-[64px] lg:text-[76px]">
            The AI CRM that sells,<br />
            <span className="bg-gradient-to-r from-[#f2780c] via-[#f58b2a] to-[#f6a04b] bg-clip-text text-transparent">supports and retains</span>
          </h1>
          <p className="mx-auto mt-6 max-w-3xl text-[17px] leading-relaxed text-muted-foreground sm:text-[21px]">
            One workspace for your marketing and support. Kotler's AI agents answer on WhatsApp, Telegram and your
            website, act on orders within limits you set, and win customers back, with every number measured.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Link to="/app"><Button variant="primary" size="xl">Open the dashboard <ArrowRight /></Button></Link>
            <a href="/store"><Button size="xl" variant="secondary"><Store />Try the demo store</Button></a>
          </div>
        </div>

        <div id="product" className="relative mx-auto max-w-7xl px-3 sm:px-5">
          <div role="tablist" className="flex snap-x gap-1 overflow-x-auto pb-3 scroll-thin lg:justify-between">
            {MODULES.map((x) => {
              const on = x.key === active;
              return (
                <button key={x.key} role="tab" aria-selected={on} onClick={() => setActive(x.key)}
                  className="group flex min-w-[96px] shrink-0 snap-start cursor-pointer flex-col items-center gap-2.5 rounded-2xl px-2 py-3">
                  <span className={cn("grid size-14 place-items-center rounded-2xl transition-all",
                    on ? "bg-ink text-primary shadow-lg" : "bg-primary-soft/70 text-primary group-hover:bg-primary-soft")}>
                    <x.icon className="size-6" strokeWidth={2.2} />
                  </span>
                  <span className={cn("text-center text-[14px] leading-tight", on ? "font-bold text-foreground" : "text-muted-foreground")}>
                    {x.label[0]}<br />{x.label[1]}
                  </span>
                </button>
              );
            })}
          </div>
          <div key={m.key} className="mt-6 grid items-center gap-8 pb-20 animate-in lg:grid-cols-[1.1fr_1fr]">
            <div className="rounded-3xl border bg-card p-6 shadow-[0_18px_50px_-30px_rgba(60,30,0,0.3)] sm:p-8">
              <div className="text-[13px] font-semibold text-primary">{m.label.join(" ")}</div>
              <h2 className="mt-2 text-[26px] leading-tight font-extrabold sm:text-[30px]">{m.title}</h2>
              <div className="mt-6 rounded-2xl border bg-background p-4">
                <div className="text-[13px] font-bold">Context & instructions</div>
                <div className="text-[12px] text-muted-foreground">What this module follows, enforced in code where it matters</div>
                <ul className="mt-3 space-y-2 text-[14px]">
                  {m.context.map((c) => <li key={c} className="flex gap-2.5"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" />{c}</li>)}
                </ul>
              </div>
            </div>
            <div>{m.preview}</div>
          </div>
        </div>
      </section>

      <section className="border-y bg-card">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-6 px-5 py-12 text-center md:grid-cols-4">
          {[["3", "AI agents, live"], ["3", "channels: WhatsApp, Telegram, web"], ["4", "retention journeys"], ["₹0", "to run on free tiers"]].map(([n, l]) => (
            <div key={l}><div className="font-display text-[44px] font-extrabold tracking-tight text-primary">{n}</div>
              <div className="text-[14px] text-muted-foreground">{l}</div></div>))}
        </div>
      </section>

      <section id="guardrails" className="mx-auto max-w-6xl px-5 py-20">
        <h2 className="text-center text-[34px] leading-tight font-extrabold sm:text-[44px]">Guardrails in code,<br /><span className="text-primary">not just in prompts</span></h2>
        <p className="mx-auto mt-4 max-w-2xl text-center text-[17px] text-muted-foreground">A prompt is a request. These are rules the AI can't break, each covered by automated tests.</p>
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {GUARDS.map((g) => (
            <div key={g.title} className="rounded-3xl border bg-card p-6 transition-shadow hover:shadow-[0_18px_50px_-30px_rgba(60,30,0,0.35)]">
              <div className="grid size-11 place-items-center rounded-2xl bg-primary-soft text-primary"><g.icon className="size-5" /></div>
              <h3 className="mt-4 text-[18px] font-bold">{g.title}</h3>
              <p className="mt-1.5 text-[14.5px] leading-relaxed text-muted-foreground">{g.body}</p>
            </div>))}
        </div>
      </section>

      <section id="how" className="mx-auto max-w-6xl px-5 pb-20">
        <h2 className="text-center text-[34px] font-extrabold sm:text-[44px]">Up and running in three steps</h2>
        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {[["Connect channels", "Add a Telegram bot token, a WhatsApp test number, or one line of script for your website."],
            ["Tune your agents", "Edit instructions, tools and goals in Agent Studio. Test in the playground before going live."],
            ["Watch it work", "Take over chats in the live inbox, launch campaigns with a holdout, and track every rupee."]].map(([t, b], i) => (
            <div key={t} className="rounded-3xl border bg-card p-7">
              <div className="grid size-10 place-items-center rounded-full bg-ink font-display text-[16px] font-extrabold text-primary">{i + 1}</div>
              <h3 className="mt-4 text-[19px] font-bold">{t}</h3><p className="mt-2 text-[14.5px] text-muted-foreground">{b}</p>
            </div>))}
        </div>
      </section>

      <section className="px-5 pb-16">
        <div className="relative mx-auto max-w-6xl overflow-hidden rounded-[32px] bg-ink px-6 py-14 text-center text-ink-foreground sm:px-12">
          <div className="pointer-events-none absolute -top-24 left-1/2 h-64 w-[80%] -translate-x-1/2 rounded-full bg-primary/30 blur-3xl" />
          <h2 className="relative text-[32px] leading-tight font-extrabold sm:text-[44px]">See your store run on AI agents</h2>
          <p className="relative mx-auto mt-3 max-w-xl text-[16px] opacity-75">Open the workspace with demo data: 1,500 customers, real models, live inbox.</p>
          <Link to="/app" className="relative mt-8 inline-block"><Button variant="primary" size="xl">Open the dashboard <ArrowRight /></Button></Link>
        </div>
      </section>

      <footer className="border-t">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-5 py-8 text-[13px] text-muted-foreground">
          <Logo /><span>An open learning project. Demo data only.</span>
          <div className="ml-auto flex gap-5"><a href="/store" className="hover:text-foreground">Demo store</a><Link to="/login" className="hover:text-foreground">Sign in</Link></div>
        </div>
      </footer>
    </div>
  );
}
