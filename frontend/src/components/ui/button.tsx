import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-semibold transition-all active:scale-[0.98] " +
    "disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0 cursor-pointer",
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground shadow-[0_6px_16px_-6px] shadow-primary/60 hover:brightness-105",
        ink: "bg-ink text-ink-foreground hover:opacity-90",
        secondary: "border bg-card text-foreground shadow-card hover:bg-muted",
        ghost: "text-muted-foreground hover:bg-muted hover:text-foreground",
        danger: "bg-danger text-white hover:bg-danger/90",
      },
      size: { sm: "h-8 px-3.5 text-[13px]", md: "h-9 px-4", lg: "h-11 px-6 text-[15px]", xl: "h-13 px-8 text-base", icon: "size-9" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>;

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(button({ variant, size }), className)} {...props} />;
}
