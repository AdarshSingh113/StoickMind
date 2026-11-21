import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router";
import { AppShell } from "@/components/shell";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { Login } from "@/pages/Login";
import { NotFound } from "@/pages/Misc";

// Code splitting: each page is downloaded the first time it's opened.
const named = <K extends string>(loader: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  lazy(() => loader().then((m) => ({ default: m[name] })));
const Landing = named(() => import("@/pages/Landing"), "Landing");
const Overview = named(() => import("@/pages/Overview"), "Overview");
const Inbox = named(() => import("@/pages/Inbox"), "Inbox");
const Customers = named(() => import("@/pages/Customers"), "Customers");
const Customer360 = named(() => import("@/pages/Customer360"), "Customer360");
const Ask = named(() => import("@/pages/Ask"), "Ask");
const Performance = named(() => import("@/pages/Performance"), "Performance");
const Campaigns = named(() => import("@/pages/Campaigns"), "Campaigns");
const NewCampaign = named(() => import("@/pages/Campaigns"), "NewCampaign");
const CampaignDetail = named(() => import("@/pages/Campaigns"), "CampaignDetail");
const Helpdesk = named(() => import("@/pages/Helpdesk"), "Helpdesk");
const Studio = named(() => import("@/pages/Studio"), "Studio");
const AgentEditor = named(() => import("@/pages/Studio"), "AgentEditor");
const Listening = named(() => import("@/pages/Listening"), "Listening");

const page = (el: ReactNode) => <Suspense fallback={<div className="p-8"><Skeleton className="h-8 w-48" /></div>}>{el}</Suspense>;

/** Everything under /app needs a session. The server is the real gatekeeper (every API call checks the
 * cookie); this only decides which screen to show. */
function Protected() {
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false, staleTime: 5 * 60_000 });
  useEffect(() => {
    const onLogout = () => { qc.clear(); navigate("/login", { state: { from: location.pathname } }); };
    window.addEventListener("kotler:logged-out", onLogout);
    return () => window.removeEventListener("kotler:logged-out", onLogout);
  }, [navigate, qc, location.pathname]);
  if (me.isLoading) return <div className="flex h-dvh"><Skeleton className="m-4 w-60 rounded-2xl" /><Skeleton className="m-4 flex-1 rounded-2xl" /></div>;
  if (me.error instanceof ApiError && me.error.status === 401) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (me.isError || !me.data) return <div className="p-8 text-sm text-danger">Can't reach the Kotler API. Is the server running? (uvicorn kotler.server:app)</div>;
  return <AppShell me={me.data} />;
}

/** Links from R1/R2 (/inbox/...) keep working. */
function LegacyInbox() {
  const { channel, id } = useParams();
  return <Navigate replace to={channel && id ? `/app/inbox/${channel}/${encodeURIComponent(id)}` : "/app/inbox"} />;
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={page(<Landing />)} />
      <Route path="/login" element={<Login />} />
      <Route path="/inbox" element={<LegacyInbox />} />
      <Route path="/inbox/:channel/:id" element={<LegacyInbox />} />
      <Route path="/app" element={<Protected />}>
        <Route index element={page(<Overview />)} />
        <Route path="inbox" element={page(<Inbox />)} />
        <Route path="inbox/:channel/:id" element={page(<Inbox />)} />
        <Route path="customers" element={page(<Customers />)} />
        <Route path="customers/:id" element={page(<Customer360 />)} />
        <Route path="ask" element={page(<Ask />)} />
        <Route path="performance" element={page(<Performance />)} />
        <Route path="campaigns" element={page(<Campaigns />)} />
        <Route path="campaigns/new" element={page(<NewCampaign />)} />
        <Route path="campaigns/:id" element={page(<CampaignDetail />)} />
        <Route path="helpdesk" element={page(<Helpdesk />)} />
        <Route path="listening" element={page(<Listening />)} />
        <Route path="studio" element={page(<Studio />)} />
        <Route path="studio/:slug" element={page(<AgentEditor />)} />
        <Route path="*" element={<NotFound />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
