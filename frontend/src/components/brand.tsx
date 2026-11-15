import { Globe, Send } from "lucide-react";
import type { Channel } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="grid size-8 place-items-center rounded-[10px] bg-gradient-to-br from-indigo-600 to-violet-500 text-[15px] font-bold text-white shadow-sm">
        K
      </div>
      <span className="text-[15px] font-semibold tracking-tight">Kotler <span className="text-primary">AI</span></span>
    </div>
  );
}

function WhatsAppIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
      <path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2Zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8s-.4-.1-.6.1-.7.8-.8 1-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.2-.4.2-.4.7-1.3a.4.4 0 0 0 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.7 11.8 11.8 0 0 0 4.5 4c1.7.7 2.3.8 3.2.6a2.7 2.7 0 0 0 1.8-1.2 2.2 2.2 0 0 0 .1-1.3c0-.1-.2-.2-.4-.3Z" />
    </svg>
  );
}

const CH = {
  telegram: { label: "Telegram", Icon: Send, tone: "bg-sky-100 text-sky-600 dark:bg-sky-950 dark:text-sky-300" },
  whatsapp: { label: "WhatsApp", Icon: WhatsAppIcon, tone: "bg-emerald-100 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-300" },
  web: { label: "Website", Icon: Globe, tone: "bg-violet-100 text-violet-600 dark:bg-violet-950 dark:text-violet-300" },
} as const;

export const channelLabel = (c: Channel) => CH[c].label;

export function ChannelIcon({ channel, className }: { channel: Channel; className?: string }) {
  const { Icon, tone, label } = CH[channel];
  return (
    <span title={label} className={cn("grid size-[18px] place-items-center rounded-full ring-2 ring-card", tone, className)}>
      <Icon className="size-[11px]" />
    </span>
  );
}

const AGENTS: Record<string, string> = { kavya: "Kavya · shopping", asha: "Asha · support", "skin-quiz": "Ira · skin quiz",
  human: "Team", campaign: "Campaign" };
export const agentLabel = (slug: string | null) => (slug ? AGENTS[slug] ?? slug : "");
