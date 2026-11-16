import { useMutation } from "@tanstack/react-query";
import { ArrowUp, BadgeCheck, Code2, Download, Lock, MessageSquareText, RotateCcw, ShieldAlert, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ErrorNote } from "@/components/data";
import { PageHeader } from "@/components/empty";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { post } from "@/lib/api";
import { num } from "@/lib/format";

type Answer = {
  question: string; sql: string; title: string; explanation: string;
  chart: { type: "bar" | "line" | "none"; x?: string; y?: string; color?: string | null };
  columns: string[]; rows: Record<string, string | number | null>[]; row_count: number; answer: string;
  answer_status: "verified" | "withheld" | "none"; ungrounded: string[]; attempts: number; error: string | null; data_end: string;
};

const EXAMPLES = ["Delivered revenue by month", "Which city tier has the highest RTO rate on COD orders?",
  "Top 5 products by units sold", "Support tickets per category, and how many the AI resolved",
  "Which AI agent escalates to humans most often?", "Average order value by acquisition channel"];
const axis = { fontSize: 11.5, fill: "var(--subtle-foreground)" };

const fmtCell = (v: unknown) => (typeof v === "number" ? (Math.abs(v) < 1 && v !== 0 ? v.toFixed(3) : num(v)) : (v ?? "–") as string);

function Chart({ a }: { a: Answer }) {
  const { type, x, y } = a.chart;
  if (type === "none" || !x || !y || a.rows.length < 2) return null;
  const C = type === "line" ? LineChart : BarChart;
  const incomplete = type === "line" && String(a.rows.at(-1)?.[x]) === a.data_end.slice(0, 7);
  return (
    <div className="mt-4">
      <div className="h-64">
        <ResponsiveContainer>
          <C data={a.rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey={x} tick={axis} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={12} />
            <YAxis tick={axis} tickLine={false} axisLine={false} width={64} tickFormatter={(v) => num(Number(v))} />
            <Tooltip formatter={(v) => num(Number(v))} cursor={{ fill: "var(--muted)" }} />
            {type === "line" ? <Line dataKey={y} stroke="var(--chart-1)" strokeWidth={2.5} dot={{ r: 3 }} />
              : <Bar dataKey={y} fill="var(--chart-1)" radius={[6, 6, 0, 0]} maxBarSize={48} />}
          </C>
        </ResponsiveContainer>
      </div>
      {incomplete && <p className="mt-1 text-[12px] text-subtle-foreground">{a.data_end.slice(0, 7)} is incomplete (data ends {a.data_end}), so it looks lower than it will be.</p>}
    </div>
  );
}

function download(a: Answer) {
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [a.columns.map(esc).join(","), ...a.rows.map((r) => a.columns.map((c) => esc(r[c])).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  Object.assign(document.createElement("a"), { href: url, download: "kotler-answer.csv" }).click();
  URL.revokeObjectURL(url);
}

function AnswerCard({ a }: { a: Answer }) {
  const [showSql, setShowSql] = useState(false);
  return (
    <div className="space-y-3 animate-in">
      <div className="flex justify-end"><div className="max-w-[80%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-[14px] text-ink-foreground">{a.question}</div></div>
      <Card className="p-5">
        {a.error ? (
          <div className="flex gap-3 text-[13.5px] text-danger"><ShieldAlert className="size-5 shrink-0" />
            <div><b>Couldn't answer:</b> {a.error}{a.sql && <pre className="mt-2 overflow-x-auto rounded-xl bg-muted p-3 text-[12px] text-foreground">{a.sql}</pre>}</div></div>
        ) : (<>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h3 className="text-[17px] font-bold">{a.title || "Result"}</h3>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={() => setShowSql(!showSql)}><Code2 />SQL</Button>
              <Button size="sm" variant="ghost" onClick={() => download(a)}><Download />CSV</Button>
            </div>
          </div>
          {a.answer_status === "verified" && (
            <p className="mt-2 text-[14.5px] leading-relaxed">{a.answer} <Badge tone="good" className="ml-1 align-middle"><BadgeCheck />numbers checked</Badge></p>)}
          {a.answer_status === "withheld" && (
            <p className="mt-2 rounded-xl bg-warning-soft p-3 text-[13px] text-warning"><b>Summary withheld:</b> it contained numbers that aren't in the result ({a.ungrounded.slice(0, 4).join(", ")}). The table below is exact.</p>)}
          {showSql && <div className="mt-3 rounded-xl bg-muted p-3 text-[12px]"><p className="mb-2 text-muted-foreground">{a.explanation}{a.attempts > 1 && " (fixed after a failed first attempt)"}</p>
            <pre className="overflow-x-auto font-mono">{a.sql}</pre></div>}
          <Chart a={a} />
          <div className="mt-4 max-h-72 overflow-auto rounded-xl border scroll-thin">
            <table className="w-full text-[13px]">
              <thead className="sticky top-0 bg-muted"><tr>{a.columns.map((c) => <th key={c} className="px-3 py-2 text-left font-semibold text-muted-foreground">{c.replace(/_/g, " ")}</th>)}</tr></thead>
              <tbody className="divide-y">{a.rows.map((r, i) => <tr key={i}>{a.columns.map((c) => <td key={c} className="px-3 py-2 tabular">{fmtCell(r[c])}</td>)}</tr>)}</tbody>
            </table>
          </div>
          <p className="mt-2 text-[12px] text-subtle-foreground">{num(a.row_count)} rows{a.row_count > a.rows.length && ` (first ${a.rows.length} shown)`}</p>
        </>)}
      </Card>
    </div>
  );
}

export function Ask() {
  const [history, setHistory] = useState<Answer[]>([]);
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const ask = useMutation({
    mutationFn: (question: string) => post<Answer>("/api/v1/ask", { question, history: history.slice(-3).map((h) => ({ question: h.question, sql: h.sql })) }),
    onSuccess: (a) => { setHistory((h) => [...h, a]); setText(""); },
  });
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [history.length, ask.isPending]);
  const submit = (q: string) => { if (q.trim() && !ask.isPending) ask.mutate(q.trim()); };
  return (
    <div className="mx-auto flex min-h-full max-w-4xl flex-col p-4 sm:p-6 lg:p-8">
      <PageHeader title="Ask your data" description="Plain English or Hinglish. The SQL is always shown and every number in the summary is checked."
        actions={history.length > 0 && <Button size="sm" onClick={() => setHistory([])}><RotateCcw />New conversation</Button>} />
      <div className="flex-1 space-y-6">
        {history.length === 0 && (
          <Card className="p-6 sm:p-8">
            <div className="grid size-12 place-items-center rounded-2xl bg-primary-soft text-primary"><MessageSquareText className="size-6" /></div>
            <h2 className="mt-4 text-[20px] font-extrabold">What would you like to know?</h2>
            <p className="mt-1 text-[14px] text-muted-foreground">Orders, customers, products, tickets, campaigns, even the AI's own performance.</p>
            <div className="mt-5 flex flex-wrap gap-2">{EXAMPLES.map((e) => (
              <button key={e} onClick={() => submit(e)} className="cursor-pointer rounded-full border bg-card px-3.5 py-1.5 text-[13px] hover:border-primary/50 hover:bg-primary-soft/50">
                <Sparkles className="mr-1.5 inline size-3.5 text-primary" />{e}</button>))}</div>
            <p className="mt-6 flex items-center gap-2 text-[12.5px] text-muted-foreground"><Lock className="size-3.5" />Names, phones, emails and addresses are blocked by the database connection, column by column. Read-only.</p>
          </Card>
        )}
        {history.map((a, i) => <AnswerCard key={i} a={a} />)}
        {ask.isPending && <div className="space-y-3"><div className="flex justify-end"><div className="rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-[14px] text-ink-foreground opacity-80">{ask.variables}</div></div>
          <Card className="space-y-3 p-5"><Skeleton className="h-5 w-1/3" /><Skeleton className="h-4 w-2/3" /><Skeleton className="h-48" /></Card></div>}
        {ask.isError && <ErrorNote error={ask.error} />}
        <div ref={end} />
      </div>
      <div className="sticky bottom-0 mt-6 bg-gradient-to-t from-background via-background to-transparent pt-4 pb-1">
        <div className="flex items-end gap-2 rounded-3xl border bg-card p-2 shadow-card focus-within:border-ring">
          <Textarea rows={1} value={text} onChange={(e) => setText(e.target.value)} maxLength={500}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(text); } }}
            placeholder={history.length ? "Ask a follow-up, e.g. “and by month?”" : "Ask a question about your business…"}
            className="border-0 bg-transparent py-2.5 shadow-none focus:ring-0" />
          <Button variant="primary" size="icon" aria-label="Ask" disabled={!text.trim() || ask.isPending} onClick={() => submit(text)}><ArrowUp /></Button>
        </div>
      </div>
    </div>
  );
}
