import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot, ChartNoAxesCombined, Inbox, LayoutDashboard, LogOut, Megaphone, Menu, MessageSquareText, Moon, Search,
  Store, Sun, TriangleAlert, UsersRound, Wrench, X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { api, type Me } from "@/lib/api";
import { useLiveInbox } from "@/lib/live";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { Logo } from "./brand";
import { CommandPalette } from "./command";

type NavItem = { to: string; label: string; icon: typeof Inbox; soon?: string; end?: boolean };
const NAV: { section: string; items: NavItem[] }[] = [
  { section: "Workspace", items: [
    { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
    { to: "/inbox", label: "Inbox", icon: Inbox },
  ] },
  { section: "Coming next", items: [
    { to: "/customers", label: "Customers", icon: UsersRound, soon: "R3" },
    { to: "/ask", label: "Ask your data", icon: MessageSquareText, soon: "R4" },
    { to: "/performance", label: "AI performance", icon: ChartNoAxesCombined, soon: "R4" },
    { to: "/campaigns", label: "Campaigns", icon: Megaphone, soon: "R5" },
    { to: "/helpdesk", label: "Helpdesk", icon: Wrench, soon: "R5" },
    { to: "/studio", label: "Agent Studio", icon: Bot, soon: "R6" },
  ] },
];

function Sidebar({ needsHuman, onNavigate }: { needsHuman: number; onNavigate?: () => void }) {
  return (
    <nav className="flex h-full flex-col gap-6 overflow-y-auto px-3 py-4 scroll-thin">
      <Logo className="px-2" />
      {NAV.map((group) => (
        <div key={group.section}>
          <div className="mb-1 px-3 text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">{group.section}</div>
          {group.items.map(({ to, label, icon: Icon, soon, end }) =>
            soon ? (
              <div key={to} className="flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] text-subtle-foreground" title={`Coming in ${soon}`}>
                <Icon className="size-4" /> {label}
                <span className="ml-auto rounded border px-1.5 text-[10.5px]">{soon}</span>
              </div>
            ) : (
              <NavLink key={to} to={to} end={end} onClick={onNavigate}
                className={({ isActive }) => cn("flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors",
                  isActive ? "bg-primary-soft text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
                <Icon className="size-4" /> {label}
                {to === "/inbox" && needsHuman > 0 && (
                  <span className="ml-auto rounded-full bg-danger px-1.5 text-[11px] font-semibold text-white tabular">{needsHuman}</span>
                )}
              </NavLink>
            ))}
        </div>
      ))}
      <a href="/store" target="_blank" rel="noreferrer"
        className="mt-auto flex items-center gap-3 rounded-lg border border-dashed px-3 py-2 text-[13px] text-muted-foreground hover:text-foreground">
        <Store className="size-4" /> Demo store + chat widget
      </a>
    </nav>
  );
}

export function AppShell({ me }: { me: Me }) {
  const [theme, toggleTheme] = useTheme();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const live = useLiveInbox();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const counts = useQuery({ queryKey: ["inbox", "counts"], queryFn: () => api.inbox("all", null, ""), refetchInterval: 60_000 });
  const needsHuman = counts.data?.counts.needs_human ?? 0;
  const logout = async () => { await api.logout().catch(() => {}); qc.clear(); navigate("/login"); };

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="hidden w-60 shrink-0 border-r bg-card lg:block"><Sidebar needsHuman={needsHuman} /></aside>
      {mobileNav && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setMobileNav(false)}>
          <div className="absolute inset-0 bg-black/30" />
          <aside className="absolute inset-y-0 left-0 w-64 border-r bg-card animate-in" onClick={(e) => e.stopPropagation()}>
            <button className="absolute top-4 right-3 text-muted-foreground" onClick={() => setMobileNav(false)} aria-label="Close menu"><X className="size-5" /></button>
            <Sidebar needsHuman={needsHuman} onNavigate={() => setMobileNav(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-card/80 px-4 backdrop-blur lg:px-6">
          <button className="text-muted-foreground lg:hidden" onClick={() => setMobileNav(true)} aria-label="Open menu"><Menu className="size-5" /></button>
          <button onClick={() => setPaletteOpen(true)}
            className="flex h-9 w-full max-w-sm cursor-pointer items-center gap-2 rounded-lg border bg-background px-3 text-[13px] text-subtle-foreground hover:border-ring/50">
            <Search className="size-4" /> Search or jump to…
            <kbd className="ml-auto hidden rounded border bg-card px-1.5 text-[11px] sm:inline">Ctrl K</kbd>
          </button>
          <div className="ml-auto flex items-center gap-1.5">
            <span className="mr-2 hidden items-center gap-1.5 text-[12px] text-muted-foreground sm:flex" title={live ? "Receiving live updates" : "Reconnecting…"}>
              <span className={cn("size-2 rounded-full", live ? "bg-emerald-500 shadow-[0_0_0_3px] shadow-emerald-500/20" : "bg-amber-500")} />
              {live ? "Live" : "Connecting"}
            </span>
            <IconButton label="Toggle theme" onClick={toggleTheme}>{theme === "dark" ? <Sun /> : <Moon />}</IconButton>
            <IconButton label="Log out" onClick={logout}><LogOut /></IconButton>
            <div className="ml-1 hidden text-right sm:block">
              <div className="text-[13px] font-medium leading-tight">Admin</div>
              <div className="text-[11.5px] text-muted-foreground leading-tight">{me.brand}</div>
            </div>
          </div>
        </header>
        {me.default_password && (
          <div className="flex items-center gap-2 border-b bg-warning-soft px-4 py-2 text-[12.5px] text-warning lg:px-6">
            <TriangleAlert className="size-4 shrink-0" />
            <span>Development password in use. Set <code className="font-semibold">KOTLER_ADMIN_PASSWORD</code> before deploying.</span>
          </div>
        )}
        <main className="min-h-0 flex-1 overflow-y-auto scroll-thin"><Outlet /></main>
      </div>
      <CommandPalette open={paletteOpen} setOpen={setPaletteOpen} toggleTheme={toggleTheme} theme={theme} onLogout={logout} />
    </div>
  );
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button aria-label={label} title={label} onClick={onClick}
      className="grid size-9 cursor-pointer place-items-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground [&_svg]:size-[18px]">
      {children}
    </button>
  );
}
