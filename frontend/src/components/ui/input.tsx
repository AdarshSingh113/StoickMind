import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const base = "w-full rounded-lg border bg-card px-3 text-sm placeholder:text-subtle-foreground outline-none " +
  "transition-shadow focus:border-ring focus:ring-3 focus:ring-ring/15 disabled:opacity-60";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(base, "h-9", className)} {...props} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(base, "py-2 resize-none", className)} {...props} />;
}
