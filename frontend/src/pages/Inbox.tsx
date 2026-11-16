import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Bot, CircleUserRound, Hand, Inbox as InboxIcon, MessageSquareDashed, PanelRightClose, PanelRightOpen,
  Search, SendHorizontal, Sparkles, TriangleAlert, UserRound,
} from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";
import { agentLabel, ChannelIcon, channelLabel } from "@/components/brand";
import { EmptyState } from "@/components/empty";
import { ProductCards } from "@/components/product";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Channel, type Conversation, type ConversationSummary, type CustomerProfile, type InboxView, type Message } from "@/lib/api";
import { langLabel, clock, dayLabel, inr, num, pct, relativeTime, ago, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Same person -> same avatar colour everywhere (list, thread, profile). */
const seedOf = (customerId: number | null | undefined, channel: string, id: string) => (customerId ? `c${customerId}` : channel + id);
const statusLabel = (s: string) => (s === "rto" ? "RTO (refused)" : titleCase(s));

const name = (c: { customer_name?: string | null; display_name: string | null; channel: Channel }) =>
  c.customer_name ?? c.display_name ?? (c.channel === "web" ? "Website visitor" : "Unknown");

export function Inbox() {
  const { channel, id } = useParams();
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as InboxView) || "all";
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 250); return () => clearTimeout(t); }, [q]);
  const [chFilter, setChFilter] = useState<Channel | "">("");
  const list = useQuery({ queryKey: ["inbox", "list", view, chFilter, debounced], queryFn: () => api.inbox(view, chFilter || null, debounced),
    placeholderData: keepPreviousData });
  const selected = channel && id ? { channel: channel as Channel, id } : null;

  return (
    <div className="flex h-full min-h-0">
      {/* ---------------------------------------------------------------- list */}
      <section className={cn("flex w-full min-w-0 flex-col border-r bg-card md:w-[340px] md:shrink-0", selected && "hidden md:flex")}>
        <div className="space-y-3 border-b p-4">
          <div className="flex items-center justify-between">
            <h1 className="text-[18px] font-semibold tracking-tight">Inbox</h1>
            <select value={chFilter} onChange={(e) => setChFilter(e.target.value as Channel | "")} aria-label="Channel"
              className="h-8 rounded-lg border bg-card px-2 text-[12.5px] text-muted-foreground outline-none">
              <option value="">All channels</option><option value="whatsapp">WhatsApp</option>
              <option value="telegram">Telegram</option><option value="web">Website</option>
            </select>
          </div>
          <div className="relative">
            <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-subtle-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name or message" className="pl-9" />
          </div>
          <Segmented className="w-full [&>button]:flex-1 [&>button]:justify-center" value={view}
            onChange={(v) => setParams(v === "all" ? {} : { view: v })}
            options={[{ value: "all", label: "All", count: list.data?.counts.all },
              { value: "needs_human", label: "Needs you", count: list.data?.counts.needs_human },
              { value: "human", label: "Mine", count: list.data?.counts.human },
              { value: "ai", label: "AI", count: list.data?.counts.ai }]} />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto scroll-thin">
          {list.isLoading ? <ListSkeleton /> : list.data && list.data.conversations.length === 0
            ? (list.data.counts.all === 0 ? <NoChats /> : <p className="p-6 text-center text-[13px] text-muted-foreground">No conversations match.</p>)
            : list.data?.conversations.map((c) => <ConversationRow key={c.channel + c.external_id} c={c}
                active={selected?.channel === c.channel && selected.id === c.external_id} />)}
        </div>
      </section>

      {/* -------------------------------------------------------------- thread */}
      <section className={cn("min-w-0 flex-1", !selected && "hidden md:block")}>
        {selected ? <Thread key={selected.channel + selected.id} channel={selected.channel} id={selected.id} />
          : <div className="grid h-full place-items-center"><EmptyState icon={InboxIcon} title="Select a conversation"
              body="Customers' chats from WhatsApp, Telegram and your website appear here as they happen. The AI answers; you can take over any time." /></div>}
      </section>
    </div>
  );
}

function ConversationRow({ c, active }: { c: ConversationSummary; active: boolean }) {
  const preview = c.last_text ? (c.last_direction === "out" ? (c.last_author === "human" ? "You: " : "AI: ") + c.last_text : c.last_text) : "";
  return (
    <Link to={`/app/inbox/${c.channel}/${encodeURIComponent(c.external_id)}${location.search}`}
      className={cn("flex gap-3 border-b px-4 py-3 transition-colors", active ? "bg-primary-soft/70" : "hover:bg-muted/60")}>
      <div className="relative">
        <Avatar name={name(c)} seed={seedOf(c.customer_id, c.channel, c.external_id)} />
        <ChannelIcon channel={c.channel} className="absolute -right-1 -bottom-1" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={cn("truncate text-[13.5px]", c.unread ? "font-semibold" : "font-medium")}>{name(c)}</span>
          <span className="ml-auto shrink-0 text-[11.5px] text-subtle-foreground">{relativeTime(c.last_at)}</span>
        </div>
        <p className={cn("mt-0.5 line-clamp-1 text-[12.5px]", c.unread ? "text-foreground" : "text-muted-foreground")}>{stripStars(preview)}</p>
        <div className="mt-1.5 flex items-center gap-1.5">
          {c.needs_human ? <Badge tone="bad"><Hand />Needs you</Badge> : null}
          {c.handler === "human" ? <Badge tone="primary"><UserRound />You're handling</Badge>
            : <Badge tone="neutral"><Bot />{agentLabel(c.agent_slug) || "AI"}</Badge>}
          {c.external_id.startsWith("demo-") && <Badge tone="outline">demo</Badge>}
          {c.unread > 0 && <span className="ml-auto grid h-5 min-w-5 place-items-center rounded-full bg-primary px-1.5 text-[11px] font-semibold text-white tabular">{c.unread}</span>}
        </div>
      </div>
    </Link>
  );
}

const stripStars = (s: string) => s.replace(/\*([^*\n]+)\*/g, "$1");

/** *bold* -> <strong>, built from React nodes (never innerHTML), so message text can't inject markup. */
function RichText({ text }: { text: string }) {
  return <>{text.split(/(\*[^*\n]+\*)/g).map((part, i) =>
    /^\*[^*\n]+\*$/.test(part) ? <strong key={i} className="font-semibold">{part.slice(1, -1)}</strong> : <Fragment key={i}>{part}</Fragment>)}</>;
}

function Thread({ channel, id }: { channel: Channel; id: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [showProfile, setShowProfile] = useState(true);
  const conv = useQuery({ queryKey: ["conversation", channel, id], queryFn: () => api.conversation(channel, id) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["conversation", channel, id] }); qc.invalidateQueries({ queryKey: ["inbox"] }); };
  const takeover = useMutation({ mutationFn: () => api.takeover(channel, id), onSuccess: () => { refresh(); toast.success("You're handling this chat. The AI will stay quiet."); } });
  const release = useMutation({ mutationFn: () => api.release(channel, id), onSuccess: () => { refresh(); toast("Handed back to the AI."); } });
  // Opening the thread marked it read on the server: refresh the unread counters in the list.
  useEffect(() => { if (conv.data) qc.invalidateQueries({ queryKey: ["inbox", "list"] }); }, [conv.data?.messages.length, qc]); // eslint-disable-line

  if (conv.isLoading) return <div className="space-y-4 p-6">{[1, 2, 3, 4].map((i) => <Skeleton key={i} className={cn("h-14 rounded-2xl", i % 2 ? "w-2/3" : "ml-auto w-1/2")} />)}</div>;
  if (conv.isError || !conv.data) return <div className="p-6 text-sm text-danger">Couldn't load this conversation.</div>;
  const { session: s, customer } = conv.data;
  const who = customer?.name ?? s.display_name ?? (channel === "web" ? "Website visitor" : "Unknown");
  const human = s.handler === "human";

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b bg-card px-4 py-3">
          <button className="text-muted-foreground md:hidden" onClick={() => navigate("/app/inbox")} aria-label="Back"><ArrowLeft className="size-5" /></button>
          <div className="relative"><Avatar name={who} seed={seedOf(s.customer_id, channel, id)} /><ChannelIcon channel={channel} className="absolute -right-1 -bottom-1" /></div>
          <div className="min-w-0">
            <div className="truncate text-[14.5px] font-semibold">{who}</div>
            <div className="text-[12px] text-muted-foreground">{channelLabel(channel)}{customer ? ` · ${customer.city}` : " · guest"}
              {s.last_inbound_at && ` · last message ${ago(s.last_inbound_at)}`.replace("just now ago", "just now")}</div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {human ? <Button size="sm" onClick={() => release.mutate()} disabled={release.isPending}><Sparkles />Hand back to AI</Button>
              : <Button size="sm" variant="primary" onClick={() => takeover.mutate()} disabled={takeover.isPending}><Hand />Take over</Button>}
            <button className="hidden text-muted-foreground hover:text-foreground xl:block" onClick={() => setShowProfile(!showProfile)}
              aria-label="Toggle customer panel">{showProfile ? <PanelRightClose className="size-5" /> : <PanelRightOpen className="size-5" />}</button>
          </div>
        </header>
        <Messages messages={conv.data.messages} />
        <Composer channel={channel} id={id} human={human} canReply={conv.data.can_reply} needsHuman={!!s.needs_human}
          onTakeover={() => takeover.mutate()} onSent={refresh} />
      </div>
      {showProfile && <Profile conv={conv.data} />}
    </div>
  );
}

function Messages({ messages }: { messages: Message[] }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [messages.length]);
  const groups = useMemo(() => {
    const out: { day: string; items: Message[] }[] = [];
    for (const m of messages) {
      const day = dayLabel(m.created_at);
      if (out.at(-1)?.day !== day) out.push({ day, items: [] });
      out.at(-1)!.items.push(m);
    }
    return out;
  }, [messages]);
  if (!messages.length) return <div className="grid flex-1 place-items-center"><EmptyState icon={MessageSquareDashed} title="No messages yet" body="Messages appear here live." /></div>;
  return (
    <div data-testid="thread" className="min-h-0 flex-1 overflow-y-auto bg-background px-4 py-6 scroll-thin sm:px-8">
      <div className="mx-auto max-w-3xl space-y-1">
        {groups.map((g) => (
          <Fragment key={g.day}>
            <div className="sticky top-0 z-10 flex justify-center py-2"><span className="rounded-full border bg-card px-3 py-0.5 text-[11.5px] text-muted-foreground shadow-card">{g.day}</span></div>
            {g.items.map((m, i) => <Bubble key={m.id} m={m} grouped={i > 0 && g.items[i - 1].direction === m.direction && g.items[i - 1].agent_slug === m.agent_slug} />)}
          </Fragment>
        ))}
        <div ref={end} />
      </div>
    </div>
  );
}

function Bubble({ m, grouped }: { m: Message; grouped: boolean }) {
  const inbound = m.direction === "in";
  const human = m.agent_slug === "human";
  return (
    <div className={cn("flex animate-in", inbound ? "justify-start" : "justify-end", grouped ? "mt-1" : "mt-3")}>
      <div className={cn("max-w-[78%]", !inbound && "items-end text-right")}>
        {!grouped && !inbound && (
          <div className="mb-1 flex items-center justify-end gap-1 text-[11.5px] text-muted-foreground">
            {human ? <><CircleUserRound className="size-3.5" />You</> : <><Bot className="size-3.5" />{agentLabel(m.agent_slug) || "AI"}</>}
          </div>
        )}
        <div className={cn("inline-block rounded-2xl px-3.5 py-2 text-left text-[14px] leading-relaxed whitespace-pre-wrap shadow-card",
          inbound ? "rounded-tl-md border bg-card" : human ? "rounded-tr-md bg-primary text-primary-foreground" : "rounded-tr-md bg-primary-soft text-foreground")}>
          <RichText text={m.text} />
        </div>
        {!inbound && <ProductCards cards={m.cards} className="justify-end" />}
        <div className={cn("mt-0.5 text-[10.5px] text-subtle-foreground", inbound ? "pl-2" : "pr-2")}>{clock(m.created_at)}</div>
      </div>
    </div>
  );
}

const QUICK = ["Thanks for your patience! Let me check that for you.", "I've sorted this out for you. Anything else I can help with?",
  "Could you share your order number, please?"];

function Composer({ channel, id, human, canReply, needsHuman, onTakeover, onSent }: {
  channel: Channel; id: string; human: boolean; canReply: boolean; needsHuman: boolean; onTakeover: () => void; onSent: () => void;
}) {
  const [text, setText] = useState("");
  const send = useMutation({ mutationFn: (t: string) => api.reply(channel, id, t), onSuccess: () => { setText(""); onSent(); },
    onError: (e) => toast.error((e as Error).message) });
  if (!human) {
    return (
      <div className="border-t bg-card px-4 py-3">
        <div className={cn("flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 text-[13px]", needsHuman ? "border-danger/30 bg-danger-soft" : "bg-muted/60")}>
          {needsHuman ? <Hand className="size-4 text-danger" /> : <Bot className="size-4 text-primary" />}
          <span className="flex-1 text-muted-foreground">{needsHuman ? <><b className="text-foreground">The AI escalated this chat.</b> A person should reply.</>
            : "The AI is handling this conversation. Take over to reply yourself; the AI goes quiet until you hand it back."}</span>
          <Button size="sm" variant="primary" onClick={onTakeover}><Hand />Take over</Button>
        </div>
      </div>
    );
  }
  const submit = () => { const t = text.trim(); if (t && !send.isPending) send.mutate(t); };
  return (
    <div className="border-t bg-card px-4 py-3">
      {!canReply && (
        <div className="mb-2 flex items-center gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning">
          <TriangleAlert className="size-4" />WhatsApp only allows free-form replies within 24 hours of the customer's last message.
        </div>
      )}
      <div className="mb-2 flex gap-1.5 overflow-x-auto scroll-thin">
        {QUICK.map((qr) => <button key={qr} onClick={() => setText(qr)} className="shrink-0 cursor-pointer rounded-full border px-2.5 py-1 text-[12px] text-muted-foreground hover:border-primary/40 hover:text-foreground">{qr.slice(0, 34)}…</button>)}
      </div>
      <div className="flex items-end gap-2 rounded-xl border bg-background p-2 focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/15">
        <Textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} disabled={!canReply}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
          placeholder={`Reply on ${channelLabel(channel)}… (Enter to send, Shift+Enter for a new line)`}
          className="border-0 bg-transparent shadow-none focus:ring-0" maxLength={4000} />
        <Button variant="primary" size="icon" onClick={submit} disabled={!text.trim() || send.isPending || !canReply} aria-label="Send"><SendHorizontal /></Button>
      </div>
    </div>
  );
}

function Profile({ conv }: { conv: Conversation }) {
  const c = conv.customer;
  return (
    <aside className="hidden w-[300px] shrink-0 overflow-y-auto border-l bg-card scroll-thin xl:block">
      {!c ? (
        <div className="p-5">
          <div className="mb-3 grid size-12 place-items-center rounded-full bg-muted text-muted-foreground"><UserRound className="size-6" /></div>
          <div className="text-[14px] font-semibold">Guest</div>
          <p className="mt-1 text-[12.5px] text-muted-foreground">Not linked to a customer yet. Once they verify with an order number and phone digits, their profile appears here.</p>
        </div>
      ) : <CustomerPanel c={c} optIn={!!conv.session.marketing_opt_in} />}
    </aside>
  );
}

const STATUS_TONE: Record<string, "good" | "primary" | "bad" | "neutral" | "warn"> = {
  delivered: "good", shipped: "primary", out_for_delivery: "primary", placed: "primary", rto: "bad", returned: "warn", cancelled: "neutral" };

function CustomerPanel({ c, optIn }: { c: CustomerProfile; optIn: boolean }) {
  const stat = (label: string, value: ReactNode) => (
    <div className="rounded-lg border p-2.5"><div className="text-[11px] text-muted-foreground">{label}</div><div className="mt-0.5 text-[14px] font-semibold tabular">{value}</div></div>);
  return (
    <div className="space-y-5 p-5">
      <div>
        <Avatar name={c.name} seed={seedOf(c.id, "", "")} className="size-12 text-[15px]" />
        <div className="mt-3 text-[15px] font-semibold">{c.name}</div>
        <div className="text-[12.5px] text-muted-foreground">{c.city}, {c.state} · Tier {c.tier}</div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {c.segment && <Badge tone="primary">{c.segment}</Badge>}
          {c.skin_type && <Badge tone="outline">{titleCase(c.skin_type)} skin</Badge>}
          <Badge tone="outline">{langLabel(c.preferred_language)}</Badge>
          {!optIn && <Badge tone="warn">Opted out of offers</Badge>}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {stat("Lifetime value", inr(c.lifetime_value))}
        {stat("Orders", num(c.orders))}
        {stat("Churn risk", c.churn_risk != null ? <span className={c.churn_risk > 0.6 ? "text-danger" : ""}>{pct(c.churn_risk, 0)}</span> : "–")}
        {stat("Open tickets", num(c.open_tickets))}
      </div>
      <div>
        <div className="mb-2 text-[12px] font-medium text-muted-foreground uppercase tracking-wide">Recent orders</div>
        <div className="space-y-2">
          {c.recent_orders.length === 0 && <p className="text-[12.5px] text-muted-foreground">No orders yet.</p>}
          {c.recent_orders.map((o) => (
            <div key={o.order_number} className="rounded-lg border p-2.5">
              <div className="flex items-center justify-between"><span className="text-[12.5px] font-medium">{o.order_number}</span>
                <Badge tone={STATUS_TONE[o.status] ?? "neutral"}>{statusLabel(o.status)}</Badge></div>
              <div className="mt-1 flex justify-between text-[12px] text-muted-foreground">
                <span>{ago(o.created_at)} · {o.payment_method.toUpperCase()}</span><span className="tabular">{inr(o.total)}</span></div>
            </div>
          ))}
        </div>
      </div>
      <div className="space-y-1 text-[12.5px] text-muted-foreground">
        <div>{c.phone} {c.email && `· ${c.email}`}</div>
        <div>Customer since {new Date(c.created_at.replace(" ", "T")).toLocaleDateString("en-IN", { month: "short", year: "numeric" })} · via {titleCase(c.acquisition_channel)}</div>
      </div>
    </div>
  );
}

function NoChats() {
  const qc = useQueryClient();
  const demo = useMutation({ mutationFn: api.loadDemo, onSuccess: () => { qc.invalidateQueries({ queryKey: ["inbox"] }); toast.success("Loaded 5 demo conversations."); } });
  return (
    <EmptyState icon={InboxIcon} title="No conversations yet"
      body={<>Message your Telegram bot, chat on the <a className="text-primary underline" href="/store" target="_blank">demo store</a>, or load sample chats to explore.</>}
      action={<Button variant="primary" onClick={() => demo.mutate()} disabled={demo.isPending}><Sparkles />Load demo conversations</Button>} />
  );
}

function ListSkeleton() {
  return <div className="space-y-px">{Array.from({ length: 6 }, (_, i) => (
    <div key={i} className="flex gap-3 px-4 py-3"><Skeleton className="size-9 rounded-full" /><div className="flex-1 space-y-2"><Skeleton className="h-3.5 w-1/2" /><Skeleton className="h-3 w-5/6" /></div></div>))}</div>;
}
