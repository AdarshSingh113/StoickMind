import { cn } from "@/lib/utils";

export function Segmented<T extends string | number>({ value, options, onChange, className }: {
  value: T; options: { value: T; label: string; count?: number }[]; onChange: (v: T) => void; className?: string;
}) {
  return (
    <div role="tablist" className={cn("inline-flex rounded-full border bg-muted p-1", className)}>
      {options.map((o) => (
        <button key={String(o.value)} role="tab" aria-selected={o.value === value} onClick={() => onChange(o.value)}
          className={cn("flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium whitespace-nowrap transition-colors cursor-pointer",
            o.value === value ? "bg-ink text-ink-foreground shadow-card" : "text-muted-foreground hover:text-foreground")}>
          {o.label}
          {o.count != null && (
            <span className={cn("tabular rounded px-1 text-[11px]", o.value === value ? "bg-white/20" : "bg-card/70")}>{o.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}
