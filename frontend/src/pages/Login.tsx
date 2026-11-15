import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bot, LineChart, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { Logo } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export function Login() {
  const [password, setPassword] = useState("");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const login = useMutation({
    mutationFn: () => api.login(password),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ["me"] }); navigate(from, { replace: true }); },
  });
  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <div className="flex flex-col justify-center px-6 py-12 sm:px-12">
        <div className="mx-auto w-full max-w-sm">
          <Logo />
          <h1 className="mt-10 text-2xl font-semibold tracking-tight">Welcome back</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">Sign in to your store's AI workspace.</p>
          <form className="mt-8 space-y-4" onSubmit={(e) => { e.preventDefault(); login.mutate(); }}>
            <label className="block">
              <span className="mb-1.5 block text-[13px] font-medium">Admin password</span>
              <Input type="password" autoFocus autoComplete="current-password" value={password}
                onChange={(e) => setPassword(e.target.value)} className="h-10" placeholder="••••••••" />
            </label>
            {login.error && <p role="alert" className="text-[13px] text-danger">{(login.error as Error).message}</p>}
            <Button variant="primary" size="lg" className="w-full" disabled={!password || login.isPending}>
              {login.isPending ? "Signing in…" : <>Sign in <ArrowRight /></>}
            </Button>
          </form>
          <p className="mt-6 text-[12px] text-subtle-foreground">Local development password: <code>kotler</code> (unless you set KOTLER_ADMIN_PASSWORD).</p>
        </div>
      </div>
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-indigo-600 via-indigo-700 to-violet-700 lg:flex lg:flex-col lg:justify-center lg:px-16">
        <div className="absolute -top-24 -right-24 size-96 rounded-full bg-white/10 blur-3xl" />
        <div className="absolute -bottom-32 -left-20 size-96 rounded-full bg-violet-400/20 blur-3xl" />
        <div className="relative max-w-md text-white">
          <h2 className="text-3xl font-semibold leading-tight tracking-tight">AI agents that sell, support and bring customers back.</h2>
          <ul className="mt-8 space-y-4 text-[15px] text-indigo-100">
            {[[Bot, "Shopping, skin-quiz and helpdesk agents on WhatsApp, Telegram and your website"],
              [LineChart, "Revenue, retention and RTO risk, with ML models you can inspect"],
              [ShieldCheck, "Guardrails in code: grounded prices, approvals, privacy-safe analytics"]].map(([Icon, text], i) => {
              const I = Icon as typeof Bot;
              return <li key={i} className="flex gap-3"><I className="mt-0.5 size-5 shrink-0 text-white" />{text as string}</li>;
            })}
          </ul>
        </div>
      </div>
    </div>
  );
}
