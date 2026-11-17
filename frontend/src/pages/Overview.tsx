import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowRight, ArrowUpRight, Bot, CircleAlert, Clock, Headset, Lightbulb, ShieldCheck, ShoppingBag, Sparkles, TrendingUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { PageHeader } from "@/components/empty";
import { ProductThumb } from "@/components/product";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Insight, type Kpi, type Overview as Data } from "@/lib/api";
import { delta, inr, inrCompact, monthLabel, num, pct, shortDate, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

const CHART = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)"];
const axis = { fontSize: 11.5, fill: "var(--subtle-foreground)" };

function fmt(k: Pick<Kpi, "format">, v: number, compact = true) {
  return k.format === "inr" ? (compact ? inrCompact(v) : inr(v)) : k.format === "pct" ? pct(v) : num(v);
}

export function Overview() {
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ["overview", days], queryFn: () => api.overview(days), placeholderData: keepPreviousData });
  const d = q.data;
  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6 lg:p-8">
      <PageHeader title="Overview"
        description={d ? <>Glow & Co. · {shortDate(d.period.start)} – {shortDate(d.period.end)} <span className="text-subtle-foreground">· compared with the previous {days} days</span></> : "Loading…"}
        actions={<Segmented value={days} onChange={setDays} options={[{ value: 7, label: "7 days" }, { value: 30, label: "30 days" }, { value: 90, label: "90 days" }]} />} />
      {q.isError ? <Card className="p-6 text-sm text-danger">Couldn't load the overview: {(q.error as Error).message}</Card>
        : !d ? <OverviewSkeleton /> : (
        <div className={cn("space-y-4 transition-opacity", q.isFetching && "opacity-70")}>
          <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 xl:grid-cols-5 [&>*:last-child]:col-span-2 md:[&>*:last-child]:col-span-1">
            {d.kpis.map((k) => <KpiCard key={k.key} k={k} spark={k.key === "net_revenue" ? d.daily.map((x) => x.net_revenue) : k.key === "orders" ? d.daily.map((x) => x.orders) : undefined} />)}
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <RevenueCard d={d} />
            <InsightsCard items={d.insights} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
            <CustomersCard d={d} />
            <CategoryCard d={d} />
            <OperationsCard d={d} />
          </div>
          <TopProductsCard d={d} />
        </div>
      )}
    </div>
  );
}

function KpiCard({ k, spark }: { k: Kpi; spark?: number[] }) {
  const good = k.delta == null ? null : (k.delta >= 0) === k.good_when_up;
  const Arrow = (k.delta ?? 0) >= 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <Card className="p-4 animate-in">
      <div className="text-[13px] text-muted-foreground">{k.label}</div>
      <div className="mt-1.5 flex items-end justify-between gap-2">
        <div className="text-[22px] font-semibold tracking-tight whitespace-nowrap tabular leading-none sm:text-[26px]" title={fmt(k, k.value, false)}>{fmt(k, k.value)}</div>
        {spark && spark.length > 1 && (
          <div className="pointer-events-none hidden h-9 w-20 shrink-0 opacity-90 sm:block">
            <ResponsiveContainer>
              <AreaChart data={spark.map((v, i) => ({ i, v }))} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                <defs><linearGradient id={`sp-${k.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="var(--chart-1)" stopOpacity={0.25} /><stop offset="1" stopColor="var(--chart-1)" stopOpacity={0} /></linearGradient></defs>
                <Area dataKey="v" type="monotone" stroke="var(--chart-1)" strokeWidth={1.5} fill={`url(#sp-${k.key})`} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
      <div className="mt-2.5 flex items-center gap-1.5 text-[12px]">
        {k.delta != null && Math.abs(k.delta) >= 0.0005 ? (
          <span className={cn("inline-flex items-center font-medium", good ? "text-success" : "text-danger")}>
            <Arrow className="size-3.5" />{delta(k.delta)}</span>
        ) : <span className="text-muted-foreground">No change</span>}
        <span className="truncate text-subtle-foreground">vs {fmt(k, k.previous)}</span>
      </div>
    </Card>
  );
}

function ChartTooltip({ active, payload, label, money = true, labelFmt }: {
  active?: boolean; payload?: { name: string; value: number; color: string; dataKey: string }[]; label?: string;
  money?: boolean; labelFmt?: (l: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-card px-3 py-2 text-[12.5px] shadow-lg">
      <div className="mb-1 font-medium">{label && labelFmt ? labelFmt(label) : label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2 text-muted-foreground">
          <span className="size-2 rounded-full" style={{ background: p.color }} />{p.name}
          <span className="ml-auto pl-4 font-medium text-foreground tabular">{money && p.dataKey.includes("revenue") ? inr(p.value) : num(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

function RevenueCard({ d }: { d: Data }) {
  const placed = d.daily.reduce((s, x) => s + x.gmv, 0);
  const delivered = d.daily.reduce((s, x) => s + x.net_revenue, 0);
  return (
    <Card className="xl:col-span-2">
      <CardHeader title="Revenue" description={`${inr(placed)} ordered · ${inr(delivered)} delivered so far`}
        action={<div className="flex items-center gap-3 text-[12px] text-muted-foreground">
          <span className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm bg-[var(--chart-1)] opacity-60" />Ordered</span>
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 bg-[var(--chart-2)]" />Delivered</span></div>} />
      <CardBody className="h-80 pt-2">
        <ResponsiveContainer>
          <AreaChart data={d.daily.map((x) => ({ ...x, gmv_revenue: x.gmv }))} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs><linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--chart-1)" stopOpacity={0.22} /><stop offset="1" stopColor="var(--chart-1)" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="day" tickFormatter={shortDate} tick={axis} tickLine={false} axisLine={false} minTickGap={28} />
            <YAxis tickFormatter={inrCompact} tick={axis} tickLine={false} axisLine={false} width={64} />
            <Tooltip content={<ChartTooltip labelFmt={shortDate} />} cursor={{ stroke: "var(--border)" }} />
            <Area name="Ordered" dataKey="gmv_revenue" type="monotone" stroke="var(--chart-1)" strokeWidth={2} fill="url(#rev)" />
            <Area name="Delivered" dataKey="net_revenue" type="monotone" stroke="var(--chart-2)" strokeWidth={2} fill="none" />
          </AreaChart>
        </ResponsiveContainer>
      </CardBody>
      <p className="-mt-2 px-5 pb-4 text-[12px] text-subtle-foreground">The gap at the end is normal: recent orders are still on their way.</p>
    </Card>
  );
}

const TONE = { good: { icon: TrendingUp, cls: "bg-success-soft text-success" }, bad: { icon: ArrowDownRight, cls: "bg-danger-soft text-danger" },
  warn: { icon: CircleAlert, cls: "bg-warning-soft text-warning" }, neutral: { icon: Lightbulb, cls: "bg-primary-soft text-primary" } };

function InsightsCard({ items }: { items: Insight[] }) {
  return (
    <Card>
      <CardHeader title="What to know" description="Computed from your data, not written by AI" action={<Sparkles className="size-4 text-primary" />} />
      <CardBody className="space-y-3">
        {items.map((it) => {
          const t = TONE[it.tone];
          return (
            <div key={it.title} className="flex gap-3 rounded-lg border p-3">
              <div className={cn("grid size-8 shrink-0 place-items-center rounded-lg", t.cls)}><t.icon className="size-4" /></div>
              <div className="min-w-0">
                <div className="text-[13.5px] font-semibold">{it.title}</div>
                <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{it.body}</p>
              </div>
            </div>
          );
        })}
      </CardBody>
    </Card>
  );
}

function CustomersCard({ d }: { d: Data }) {
  return (
    <Card>
      <CardHeader title="New vs returning buyers" description={`${pct(d.repeat_rate_90d, 0)} of customers buy again within 90 days`} />
      <CardBody className="h-60">
        <ResponsiveContainer>
          <BarChart data={d.monthly} margin={{ top: 8, right: 0, bottom: 0, left: -16 }} barCategoryGap="28%">
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="month" tickFormatter={monthLabel} tick={axis} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={8} />
            <YAxis tick={axis} tickLine={false} axisLine={false} />
            <Tooltip content={<ChartTooltip money={false} labelFmt={monthLabel} />} cursor={{ fill: "var(--muted)" }} />
            <Bar name="Returning" dataKey="returning_buyers" stackId="b" fill="var(--chart-1)" />
            <Bar name="New" dataKey="new_buyers" stackId="b" fill="var(--chart-2)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardBody>
    </Card>
  );
}

function CategoryCard({ d }: { d: Data }) {
  const top = d.categories.slice(0, 5);
  const rest = d.categories.slice(5).reduce((s, c) => s + c.revenue, 0);
  const data = rest ? [...top, { category: "other", revenue: rest }] : top;
  const total = data.reduce((s, c) => s + c.revenue, 0);
  return (
    <Card>
      <CardHeader title="Revenue by category" description="Order value, this period" />
      <CardBody className="flex items-center gap-4">
        <div className="relative size-40 shrink-0">
          <ResponsiveContainer>
            <PieChart>
              <Pie data={data} dataKey="revenue" nameKey="category" innerRadius={52} outerRadius={76} paddingAngle={2} strokeWidth={0}>
                {data.map((_, i) => <Cell key={i} fill={CHART[i % CHART.length]} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 grid place-items-center text-center">
            <div><div className="text-[17px] font-semibold tabular">{inrCompact(total)}</div><div className="text-[11px] text-muted-foreground">total</div></div>
          </div>
        </div>
        <ul className="min-w-0 flex-1 space-y-2">
          {data.map((c, i) => (
            <li key={c.category} className="flex items-center gap-2 text-[13px]">
              <span className="size-2.5 shrink-0 rounded-sm" style={{ background: CHART[i % CHART.length] }} />
              <span className="truncate">{titleCase(c.category)}</span>
              <span className="ml-auto text-muted-foreground tabular">{pct(c.revenue / total, 0)}</span>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

function OperationsCard({ d }: { d: Data }) {
  const rows = [
    { icon: Headset, label: "Chats waiting for a person", value: num(d.inbox.needs_human), to: "/app/inbox?view=needs_human", alert: d.inbox.needs_human > 0 },
    { icon: CircleAlert, label: "Open support tickets", value: num(d.support.open), alert: false },
    { icon: ShieldCheck, label: "AI actions awaiting approval", value: num(d.support.pending_approvals), alert: d.support.pending_approvals > 0 },
    { icon: Bot, label: "AI replies this period", value: num(d.ai.agent_turns), hint: d.ai.agent_turns ? `p95 ${d.ai.p95_s.toFixed(1)}s · ${inr(d.ai.cost_inr)} est.` : "none yet" },
    { icon: ShoppingBag, label: "Sales from AI chats", value: inr(d.ai_sales.revenue), to: "/app/customers?via=ai",
      hint: d.ai_sales.chats_shown_products ? `${d.ai_sales.orders} orders · ${d.ai_sales.chats_converted} of ${d.ai_sales.chats_shown_products} chats with product cards bought` : "no product cards shown yet" },
    { icon: Clock, label: "Avg ticket resolution", value: `${d.support.avg_resolution_hours.toFixed(0)} h` },
  ];
  return (
    <Card className="lg:col-span-2 xl:col-span-1">
      <CardHeader title="Operations" description="What needs attention, and what the AI did" />
      <CardBody className="divide-y">
        {rows.map((r) => {
          const body = (
            <div className="flex items-center gap-3 py-2.5">
              <r.icon className="size-4 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px]">{r.label}</div>
                {r.hint && <div className="text-[11.5px] text-subtle-foreground">{r.hint}</div>}
              </div>
              {r.alert ? <Badge tone="bad" className="tabular">{r.value}</Badge> : <span className="text-[14px] font-semibold tabular">{r.value}</span>}
              {r.to && <ArrowRight className="size-4 text-subtle-foreground" />}
            </div>
          );
          return r.to ? <Link key={r.label} to={r.to} className="block rounded-md hover:bg-muted/60">{body}</Link> : <div key={r.label}>{body}</div>;
        })}
      </CardBody>
    </Card>
  );
}

function TopProductsCard({ d }: { d: Data }) {
  const max = Math.max(...d.top_products.map((p) => p.revenue), 1);
  return (
    <Card>
      <CardHeader title="Top products" description="By order value this period" />
      <div className="overflow-x-auto">
        <table className="w-full text-[13.5px]">
          <thead><tr className="border-y bg-muted/50 text-left text-[12px] text-muted-foreground">
            <th className="px-5 py-2 font-medium">Product</th><th className="px-3 py-2 font-medium">Category</th>
            <th className="px-3 py-2 text-right font-medium">Units</th><th className="w-[38%] px-5 py-2 font-medium">Revenue</th></tr></thead>
          <tbody className="divide-y">
            {d.top_products.map((p) => (
              <tr key={p.name} className="hover:bg-muted/40">
                <td className="px-5 py-2.5 font-medium"><div className="flex items-center gap-3">
                  <ProductThumb src={p.image_url} alt={p.name} className="size-10" />{p.name}</div></td>
                <td className="px-3 py-2.5"><Badge tone="outline">{titleCase(p.category)}</Badge></td>
                <td className="px-3 py-2.5 text-right tabular">{num(p.units)}</td>
                <td className="px-5 py-2.5">
                  <div className="flex items-center gap-3">
                    <div className="h-1.5 flex-1 rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${(p.revenue / max) * 100}%` }} /></div>
                    <span className="w-20 text-right tabular">{inrCompact(p.revenue)}</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-[118px] rounded-xl" />)}</div>
      <div className="grid gap-4 xl:grid-cols-3"><Skeleton className="h-[360px] rounded-xl xl:col-span-2" /><Skeleton className="h-[360px] rounded-xl" /></div>
      <div className="grid gap-4 lg:grid-cols-3">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-[300px] rounded-xl" />)}</div>
    </div>
  );
}
