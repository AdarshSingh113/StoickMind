import { cn } from "@/lib/utils";

export function Segmented<T extends string | number>({ value, options, onChange, className }: {
  value: T; options: { value: T; label: string; count?: number }[]; onChange: (v: T) => void; className?: string;
}) {
  return (
    <div role="tablist" className={cn("inline-flex rounded-lg border bg-muted p-0.5", className)}>
      {options.map((o) => (
        <button key={String(o.value)} role="tab" aria-selected={o.value === value} onClick={() => onChange(o.value)}
          className={cn("flex items-center gap-1.5 rounded-md px-2 py-1 text-[13px] font-medium whitespace-nowrap transition-colors cursor-pointer",
            o.value === value ? "bg-card text-foreground shadow-card" : "text-muted-foreground hover:text-foreground")}>
          {o.label}
          {o.count != null && (
            <span className={cn("tabular rounded px-1 text-[11px]", o.value === value ? "bg-muted" : "bg-card/60")}>{o.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}
