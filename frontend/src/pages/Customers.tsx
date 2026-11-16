import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { ErrorNote, Td, Th } from "@/components/data";
import { EmptyState, PageHeader } from "@/components/empty";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { get, qs } from "@/lib/api";
import { inr, inrCompact, num, pct, ago, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

export type CustomerRow = {
  id: number; name: string; city: string; state: string; tier: number; skin_type: string | null; language: string;
  channel: string; created_at: string; orders: number; lifetime_value: number; last_order_at: string | null;
  segment: string | null; churn_risk: number | null; clv_12m: number | null; value_at_risk: number | null;
};
type Seg = { segment: string; customers: number; churn_risk: number; value_at_risk: number };
type ListResp = { total: number; page: number; page_size: number; customers: CustomerRow[]; segments: Seg[] };

export const SEG_TONE: Record<string, "good" | "primary" | "warn" | "bad" | "neutral"> = {
  Champions: "good", Loyal: "good", "Potential loyalists": "primary", "New customers": "primary", Promising: "primary",
  "Need attention": "warn", "About to sleep": "warn", "At risk": "bad", "Can't lose them": "bad", Hibernating: "neutral", Lost: "neutral",
};

export function riskTone(r: number | null | undefined) {
  return r == null ? "text-muted-foreground" : r >= 0.7 ? "text-danger" : r >= 0.4 ? "text-warning" : "text-success";
}

export function Customers() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [segment, setSegment] = useState<string | null>(null);
  const [tier, setTier] = useState<number | null>(null);
  const [sort, setSort] = useState("value");
  const [page, setPage] = useState(1);
  useEffect(() => { const t = setTimeout(() => { setDebounced(q.trim()); setPage(1); }, 250); return () => clearTimeout(t); }, [q]);
  const data = useQuery({
    queryKey: ["customers", debounced, segment, tier, sort, page],
    queryFn: () => get<ListResp>(`/api/v1/customers${qs({ q: debounced, segment, tier, sort, page, page_size: 25 })}`),
    placeholderData: keepPreviousData,
  });
  const d = data.data;
  const pages = d ? Math.max(1, Math.ceil(d.total / d.page_size)) : 1;
  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6 lg:p-8">
      <PageHeader title="Customers" description="Everyone who bought from Glow & Co., scored by the ML models: segment, churn risk and predicted value." />
      {data.isError && <ErrorNote error={data.error} />}
      {d && (
        <div className="mb-5 flex gap-2 overflow-x-auto pb-1 scroll-thin">
          <SegChip label="All customers" active={!segment} onClick={() => { setSegment(null); setPage(1); }} />
          {d.segments.map((s) => <SegChip key={s.segment} label={s.segment} count={s.customers} active={segment === s.segment}
            onClick={() => { setSegment(segment === s.segment ? null : s.segment); setPage(1); }} />)}
        </div>
      )}
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b p-4">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute top-2.5 left-3.5 size-4 text-subtle-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, city, phone or email" className="pl-10" />
          </div>
          <select value={tier ?? ""} onChange={(e) => { setTier(e.target.value ? Number(e.target.value) : null); setPage(1); }} aria-label="City tier"
            className="h-9 rounded-full border bg-card px-3 text-[13px]"><option value="">All tiers</option><option value="1">Tier 1 (metro)</option>
            <option value="2">Tier 2</option><option value="3">Tier 3</option></select>
          <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }} aria-label="Sort"
            className="h-9 rounded-full border bg-card px-3 text-[13px]">
            <option value="value">Highest lifetime value</option><option value="clv">Highest predicted value</option>
            <option value="churn">Highest churn risk</option><option value="recent">Most recent order</option>
            <option value="orders">Most orders</option><option value="name">Name A–Z</option></select>
          {d && <span className="text-[13px] text-muted-foreground tabular">{num(d.total)} customers</span>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13.5px]">
            <thead className="border-b bg-muted/50"><tr><Th>Customer</Th><Th>Segment</Th><Th className="text-right">Orders</Th>
              <Th className="text-right">Lifetime value</Th><Th className="text-right">Next 12 months</Th><Th className="text-right">Churn risk</Th><Th>Last order</Th></tr></thead>
            <tbody className="divide-y">
              {!d ? Array.from({ length: 8 }, (_, i) => <tr key={i}><td colSpan={7} className="px-4 py-3"><Skeleton className="h-6" /></td></tr>)
                : d.customers.map((c) => (
                <tr key={c.id} onClick={() => navigate(`/app/customers/${c.id}`)} className={cn("cursor-pointer hover:bg-muted/50", data.isFetching && "opacity-70")}>
                  <Td><div className="flex items-center gap-3"><Avatar name={c.name} seed={`c${c.id}`} className="size-8 text-[12px]" />
                    <div><div className="font-semibold">{c.name}</div><div className="text-[12px] text-muted-foreground">{c.city} · Tier {c.tier}{c.skin_type ? ` · ${titleCase(c.skin_type)}` : ""}</div></div></div></Td>
                  <Td>{c.segment && <Badge tone={SEG_TONE[c.segment] ?? "neutral"}>{c.segment}</Badge>}</Td>
                  <Td className="text-right tabular">{num(c.orders)}</Td>
                  <Td className="text-right font-semibold tabular">{inr(c.lifetime_value)}</Td>
                  <Td className="text-right tabular text-muted-foreground">{inrCompact(c.clv_12m)}</Td>
                  <Td className={cn("text-right font-semibold tabular", riskTone(c.churn_risk))}>{pct(c.churn_risk, 0)}</Td>
                  <Td className="text-muted-foreground">{c.last_order_at ? `${ago(c.last_order_at)}` : "never"}</Td>
                </tr>))}
            </tbody>
          </table>
          {d && d.customers.length === 0 && <EmptyState icon={UsersRound} title="No customers match" body="Try a different search or segment." />}
        </div>
        {d && pages > 1 && (
          <div className="flex items-center justify-between border-t px-4 py-3 text-[13px] text-muted-foreground">
            <span>Page {page} of {pages}</span>
            <div className="flex gap-2">
              <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft />Previous</Button>
              <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next<ChevronRight /></Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function SegChip({ label, count, active, onClick }: { label: string; count?: number; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className={cn("flex shrink-0 cursor-pointer items-center gap-2 rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-colors",
      active ? "border-ink bg-ink text-ink-foreground" : "bg-card text-muted-foreground hover:border-primary/40 hover:text-foreground")}>
      {label}{count != null && <span className={cn("rounded-full px-1.5 text-[11.5px] tabular", active ? "bg-white/20" : "bg-muted")}>{num(count)}</span>}
    </button>
  );
}
