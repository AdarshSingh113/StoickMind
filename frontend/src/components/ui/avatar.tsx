import { initials } from "@/lib/format";
import { cn } from "@/lib/utils";

const tones = ["bg-indigo-100 text-indigo-700", "bg-teal-100 text-teal-700", "bg-amber-100 text-amber-800",
  "bg-pink-100 text-pink-700", "bg-violet-100 text-violet-700", "bg-sky-100 text-sky-700"];
const darkTones = ["dark:bg-indigo-950 dark:text-indigo-300", "dark:bg-teal-950 dark:text-teal-300",
  "dark:bg-amber-950 dark:text-amber-300", "dark:bg-pink-950 dark:text-pink-300", "dark:bg-violet-950 dark:text-violet-300",
  "dark:bg-sky-950 dark:text-sky-300"];

/** Same person -> same colour, every time (hash of their id). */
export function Avatar({ name, seed, className }: { name: string | null; seed: string; className?: string }) {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const i = h % tones.length;
  return (
    <div className={cn("grid size-9 shrink-0 place-items-center rounded-full text-[13px] font-semibold", tones[i], darkTones[i], className)}>
      {initials(name)}
    </div>
  );
}
