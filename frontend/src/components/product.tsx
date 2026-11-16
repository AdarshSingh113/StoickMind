import { Package } from "lucide-react";
import { inr } from "@/lib/format";
import { cn } from "@/lib/utils";

export type ProductCard = {
  product_id: number; name: string; price: number; mrp: number; size: string; image_url: string | null;
  in_stock?: boolean; buy_url?: string;
};

/** Product packshot with a graceful fallback (images are served by the API at /media/products/...). */
export function ProductThumb({ src, alt, className }: { src?: string | null; alt: string; className?: string }) {
  return src
    ? <img src={src} alt={alt} loading="lazy" className={cn("shrink-0 rounded-lg bg-muted object-cover", className)} />
    : <div className={cn("grid shrink-0 place-items-center rounded-lg bg-muted text-subtle-foreground", className)}><Package className="size-4" /></div>;
}

/** The product cards an agent's reply came with, as a horizontal strip. */
export function ProductCards({ cards, className }: { cards?: ProductCard[]; className?: string }) {
  if (!cards?.length) return null;
  return (
    <div className={cn("mt-2 flex gap-2 overflow-x-auto pb-1 scroll-thin", className)}>
      {cards.map((c) => (
        <div key={c.product_id} className="w-36 shrink-0 overflow-hidden rounded-xl border bg-card text-left shadow-card">
          <ProductThumb src={c.image_url} alt={c.name} className="aspect-square w-full rounded-none" />
          <div className="p-2">
            <div className="line-clamp-2 text-[12px] font-semibold leading-snug">{c.name}</div>
            <div className="mt-1 text-[12px] tabular"><b>{inr(c.price)}</b>
              {c.mrp > c.price && <s className="ml-1 text-subtle-foreground">{inr(c.mrp)}</s>}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
