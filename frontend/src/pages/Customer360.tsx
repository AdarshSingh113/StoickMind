import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bot, Lightbulb, Mail, MapPin, MessagesSquare, Phone, ShoppingBag, Sparkles, Ticket } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChannelIcon, agentLabel } from "@/components/brand";
import { ErrorNote, Stat, StatusBadge, Td, Th } from "@/components/data";
import { ProductThumb } from "@/components/product";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { get, type Channel } from "@/lib/api";
import { langLabel, inr, inrCompact, monthLabel, num, pct, relativeTime, ago, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";
import { riskTone, SEG_TONE } from "./Customers";

type C360 = {
  customer: { id: number; name: string; city: string; state: string; tier: number; skin_type: string | null; language: string;
    channel: string; created_at: string; orders: number; lifetime_value: number; last_order_at: string | null; phone: string;
    email: string | null; pincode: string; segment: string | null };
  scores: { segment?: string; rfm?: string; churn_risk?: number; predicted_spend_90d?: number; clv_12m?: number; value_at_risk?: number };
  features: Record<string, number | string | null>;
  segment_info: { description: string; action: string } | null;
  orders: { id: number; order_number: string; created_at: string; status: string; payment_method: string; total: number;
    discount: number; coupon_code: string | null; courier: string | null; items: string | null; source: string }[];
  monthly: { month: string; spend: number; orders: number }[];
  tickets: { id: number; created_at: string; channel: string; category: string; priority: string; status: string; message: string; resolved_by: string | null }[];
  chats: { channel: Channel; external_id: string; handler: string; needs_human: number; last_inbound_at: string | null }[];
  conversations: { id: number; agent: string; channel: string; created_at: string; turns: number }[];
  campaigns: { id: number; name: string; journey: string; grp: string; converted: number | null; revenue: number | null; status: string }[];
  top_products: { name: string; category: string; image_url: string | null; units: number }[];
};

const axis = { fontSize: 11.5, fill: "var(--subtle-foreground)" };

export function Customer360() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["customer", id], queryFn: () => get<C360>(`/api/v1/customers/${id}`) });
  if (q.isError) return <div className="p-8"><ErrorNote error={q.error} /></div>;
  if (!q.data) return <div className="space-y-4 p-8"><Skeleton className="h-28 rounded-2xl" /><div className="grid grid-cols-4 gap-4">{[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}</div><Skeleton className="h-80 rounded-2xl" /></div>;
  const { customer: c, scores: s, features: f } = q.data;
  return (
    <div className="mx-auto max-w-[1400px] space-y-5 p-4 sm:p-6 lg:p-8">
      <Link to="/app/customers" className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />All customers</Link>
      <Card className="overflow-hidden">
        <div className="h-16 bg-gradient-to-r from-primary-soft via-card to-card" />
        <div className="-mt-8 flex flex-wrap items-end gap-5 px-6 pb-5">
          <Avatar name={c.name} seed={`c${c.id}`} className="size-20 border-4 border-card text-[24px]" />
          <div className="min-w-0 flex-1">
            <h1 className="text-[26px] font-extrabold tracking-tight">{c.name}</h1>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted-foreground">
              <span className="flex items-center gap-1.5"><MapPin className="size-3.5" />{c.city}, {c.state} · Tier {c.tier}</span>
              <span className="flex items-center gap-1.5"><Phone className="size-3.5" />{c.phone}</span>
              {c.email && <span className="flex items-center gap-1.5"><Mail className="size-3.5" />{c.email}</span>}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {s.segment && <Badge tone={SEG_TONE[s.segment] ?? "neutral"}>{s.segment}</Badge>}
            {c.skin_type && <Badge tone="outline">{titleCase(c.skin_type)} skin</Badge>}
            <Badge tone="outline">{langLabel(c.language)}</Badge>
            <Badge tone="outline">via {titleCase(c.channel)}</Badge>
            {q.data.orders.some((o) => o.source === "ai_chat") && <Badge tone="primary"><Sparkles />Bought via AI chat</Badge>}
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="Lifetime value" value={inr(c.lifetime_value)} hint={`${num(c.orders)} orders`} />
        <Stat label="Predicted next 12 months" value={inrCompact(s.clv_12m)} hint="value model" />
        <Stat label="Churn risk" value={<span className={riskTone(s.churn_risk)}>{pct(s.churn_risk, 0)}</span>} hint="no order in the next 90 days" />
        <Stat label="Value at risk" value={inrCompact(s.value_at_risk)} hint="churn × predicted value" />
        <Stat label="Last order" value={c.last_order_at ? relativeTime(c.last_order_at) : "–"} hint={f.avg_days_between_orders ? `usually every ${Math.round(Number(f.avg_days_between_orders))} days` : "one order so far"} className="col-span-2 lg:col-span-1" />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="space-y-5 xl:col-span-2">
          {q.data.segment_info && (
            <div className="flex gap-3 rounded-2xl border border-primary/25 bg-primary-soft/60 p-4">
              <Lightbulb className="mt-0.5 size-5 shrink-0 text-primary" />
              <div className="text-[13.5px]"><b>{s.segment}:</b> {q.data.segment_info.description} <span className="text-muted-foreground">Suggested: {q.data.segment_info.action}</span></div>
            </div>
          )}
          <Card>
            <CardHeader title="Spend by month" description="Orders placed (excluding cancelled)" />
            <CardBody className="h-56">
              {q.data.monthly.length ? (
                <ResponsiveContainer>
                  <BarChart data={q.data.monthly} margin={{ top: 8, right: 0, bottom: 0, left: -6 }}>
                    <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                    <XAxis dataKey="month" tickFormatter={monthLabel} tick={axis} tickLine={false} axisLine={false} />
                    <YAxis tickFormatter={inrCompact} tick={axis} tickLine={false} axisLine={false} width={58} />
                    <Tooltip formatter={(v) => inr(Number(v))} labelFormatter={(l) => monthLabel(String(l))} cursor={{ fill: "var(--muted)" }} />
                    <Bar dataKey="spend" name="Spend" fill="var(--chart-1)" radius={[6, 6, 0, 0]} maxBarSize={36} />
                  </BarChart>
                </ResponsiveContainer>) : <p className="text-[13px] text-muted-foreground">No orders yet.</p>}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Orders" description={`${q.data.orders.length} most recent`} action={<ShoppingBag className="size-4 text-muted-foreground" />} />
            <div className="max-h-[420px] overflow-auto scroll-thin">
              <table className="w-full text-[13px]">
                <thead className="sticky top-0 border-y bg-muted"><tr><Th>Order</Th><Th>Items</Th><Th>Status</Th><Th className="text-right">Total</Th></tr></thead>
                <tbody className="divide-y">{q.data.orders.map((o) => (
                  <tr key={o.id}><Td><div className="font-semibold">{o.order_number}</div><div className="text-[11.5px] text-muted-foreground">{ago(o.created_at)} · {o.payment_method.toUpperCase()}{o.coupon_code ? ` · ${o.coupon_code}` : ""}
                    {o.source === "ai_chat" && <span className="ml-1 font-semibold text-primary">· AI chat</span>}</div></Td>
                    <Td className="max-w-[340px] text-muted-foreground"><div className="line-clamp-2">{o.items}</div></Td>
                    <Td><StatusBadge value={o.status} /></Td><Td className="text-right font-semibold tabular">{inr(o.total)}</Td></tr>))}</tbody>
              </table>
            </div>
          </Card>
        </div>
        <div className="space-y-5">
          <Card>
            <CardHeader title="Behaviour" description="From the feature store" />
            <CardBody className="grid grid-cols-2 gap-3 text-[13px]">
              <Fact k="Avg order value" v={inr(Number(f.aov ?? 0))} />
              <Fact k="Cash on delivery" v={pct(Number(f.cod_share ?? 0), 0)} />
              <Fact k="Refused at door (RTO)" v={num(Number(f.rto_count ?? 0))} />
              <Fact k="Returns" v={num(Number(f.returns_count ?? 0))} />
              <Fact k="Uses coupons" v={pct(Number(f.coupon_share ?? 0), 0)} />
              <Fact k="Favourite category" v={f.top_category ? titleCase(String(f.top_category)) : "–"} />
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Favourite products" />
            <CardBody className="space-y-2">{q.data.top_products.map((p) => (
              <div key={p.name} className="flex items-center gap-3 text-[13px]"><ProductThumb src={p.image_url} alt={p.name} className="size-10" />
                <span className="min-w-0 flex-1 truncate">{p.name}</span><Badge tone="outline">×{p.units}</Badge></div>))}
              {!q.data.top_products.length && <p className="text-[13px] text-muted-foreground">None yet.</p>}</CardBody>
          </Card>
          <Card>
            <CardHeader title="Conversations" action={<MessagesSquare className="size-4 text-muted-foreground" />} />
            <CardBody className="space-y-2">
              {q.data.chats.map((ch) => (
                <Link key={ch.channel + ch.external_id} to={`/app/inbox/${ch.channel}/${encodeURIComponent(ch.external_id)}`}
                  className="flex items-center gap-2.5 rounded-xl border p-2.5 text-[13px] hover:border-primary/40">
                  <ChannelIcon channel={ch.channel} /> Open in inbox
                  {ch.needs_human ? <Badge tone="bad" className="ml-auto">Needs you</Badge> : <span className="ml-auto text-[12px] text-muted-foreground">{relativeTime(ch.last_inbound_at)}</span>}
                </Link>))}
              {q.data.conversations.map((v) => (
                <div key={v.id} className="flex items-center gap-2.5 text-[13px] text-muted-foreground"><Bot className="size-4" />{agentLabel(v.agent) || v.agent} · {v.turns} messages · {ago(v.created_at)}</div>))}
              {!q.data.chats.length && !q.data.conversations.length && <p className="text-[13px] text-muted-foreground">No AI conversations yet.</p>}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Support tickets" action={<Ticket className="size-4 text-muted-foreground" />} />
            <CardBody className="space-y-2.5">{q.data.tickets.slice(0, 5).map((t) => (
              <div key={t.id} className="rounded-xl border p-2.5 text-[13px]"><div className="flex items-center justify-between gap-2"><span className="font-semibold">{titleCase(t.category)}</span><StatusBadge value={t.status} /></div>
                <p className="mt-1 line-clamp-2 text-[12.5px] text-muted-foreground">{t.message}</p></div>))}
              {!q.data.tickets.length && <p className="text-[13px] text-muted-foreground">No tickets. 🎉</p>}</CardBody>
          </Card>
          {q.data.campaigns.length > 0 && (
            <Card>
              <CardHeader title="Campaigns" />
              <CardBody className="space-y-2">{q.data.campaigns.map((m) => (
                <Link key={m.id} to={`/app/campaigns/${m.id}`} className="flex items-center justify-between gap-2 text-[13px] hover:text-primary">
                  <span className="truncate">{m.name}</span>
                  <Badge tone={m.grp === "control" ? "neutral" : m.grp === "excluded" ? "outline" : m.converted ? "good" : "primary"}>
                    {m.grp === "control" ? "Holdout" : m.grp === "excluded" ? "Excluded" : m.converted ? "Bought" : `Group ${m.grp}`}</Badge>
                </Link>))}</CardBody>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function Fact({ k, v }: { k: string; v: ReactNode }) {
  return <div className={cn("rounded-xl bg-muted/60 p-2.5")}><div className="text-[11.5px] text-muted-foreground">{k}</div><div className="mt-0.5 font-semibold">{v}</div></div>;
}
