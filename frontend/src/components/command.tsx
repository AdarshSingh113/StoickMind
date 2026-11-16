import { Command } from "cmdk";
import { Inbox, LogOut, Moon, Search, Store, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { channelLabel } from "./brand";
import { NAV } from "./shell";

/** Ctrl+K / ⌘K: jump to any page or conversation without the mouse. */
export function CommandPalette({ open, setOpen, toggleTheme, theme, onLogout }: {
  open: boolean; setOpen: (v: boolean) => void; toggleTheme: () => void; theme: string; onLogout: () => void;
}) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(!open); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);
  const chats = useQuery({ queryKey: ["inbox", "search", q], queryFn: () => api.inbox("all", null, q), enabled: open && q.length > 1 });
  if (!open) return null;
  const go = (path: string) => { setOpen(false); setQ(""); navigate(path); };
  const item = "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm aria-selected:bg-muted [&_svg]:size-4 [&_svg]:text-muted-foreground";
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 p-4 pt-[12vh] backdrop-blur-[2px]" onClick={() => setOpen(false)}>
      <Command label="Command menu" shouldFilter={!q || q.length < 2} onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl overflow-hidden rounded-xl border bg-card shadow-2xl animate-in">
        <div className="flex items-center gap-2 border-b px-4">
          <Search className="size-4 text-muted-foreground" />
          <Command.Input autoFocus value={q} onValueChange={setQ} placeholder="Search pages or conversations…"
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-subtle-foreground" />
          <kbd className="rounded border px-1.5 text-[11px] text-muted-foreground">Esc</kbd>
        </div>
        <Command.List className="max-h-80 overflow-y-auto p-2 scroll-thin" onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
          <Command.Empty className="px-3 py-6 text-center text-sm text-muted-foreground">Nothing found.</Command.Empty>
          {(chats.data?.conversations.length ?? 0) > 0 && (
            <Command.Group heading="Conversations" className="mb-2 text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5">
              {chats.data!.conversations.slice(0, 6).map((c) => (
                <Command.Item key={c.channel + c.external_id} value={`chat ${c.channel} ${c.external_id}`} className={item}
                  onSelect={() => go(`/app/inbox/${c.channel}/${encodeURIComponent(c.external_id)}`)}>
                  <Inbox /> <span className="text-foreground">{c.customer_name ?? c.display_name ?? "Website visitor"}</span>
                  <span className="ml-auto text-xs">{channelLabel(c.channel)}</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
          <Command.Group heading="Go to" className="text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5">
            {NAV.flatMap((g) => g.items).map(({ to, label, icon: Icon }) => (
              <Command.Item key={to} className={item} onSelect={() => go(to)}><Icon /><span className="text-foreground">{label}</span></Command.Item>))}
            <Command.Item className={item} onSelect={() => go("/app/campaigns/new")}><Inbox /><span className="text-foreground">New campaign</span></Command.Item>
            <Command.Item className={item} onSelect={() => { setOpen(false); window.open("/store", "_blank"); }}>
              <Store /><span className="text-foreground">Open demo store</span></Command.Item>
          </Command.Group>
          <Command.Group heading="Actions" className="text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5">
            <Command.Item className={item} onSelect={() => { toggleTheme(); setOpen(false); }}>
              {theme === "dark" ? <Sun /> : <Moon />}<span className="text-foreground">Switch to {theme === "dark" ? "light" : "dark"} mode</span></Command.Item>
            <Command.Item className={item} onSelect={() => { setOpen(false); onLogout(); }}><LogOut /><span className="text-foreground">Log out</span></Command.Item>
          </Command.Group>
        </Command.List>
      </Command>
    </div>
  );
}
