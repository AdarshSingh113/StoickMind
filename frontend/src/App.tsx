import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import { AppShell } from "@/components/shell";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { Login } from "@/pages/Login";
import { ComingSoon, NotFound } from "@/pages/Misc";

// Code splitting: each page is downloaded the first time it's opened, so the login screen doesn't wait for the
// chart library and the inbox doesn't wait for Overview's charts.
const Overview = lazy(() => import("@/pages/Overview").then((m) => ({ default: m.Overview })));
const Inbox = lazy(() => import("@/pages/Inbox").then((m) => ({ default: m.Inbox })));
const page = (el: React.ReactNode) => <Suspense fallback={<div className="p-8"><Skeleton className="h-8 w-48" /></div>}>{el}</Suspense>;

/** Everything except /login needs a session. The server is the real gatekeeper (every API call checks the
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
  if (me.isLoading) return <div className="flex h-dvh"><Skeleton className="m-4 w-56 rounded-xl" /><Skeleton className="m-4 flex-1 rounded-xl" /></div>;
  if (me.error instanceof ApiError && me.error.status === 401) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (me.isError || !me.data) return <div className="p-8 text-sm text-danger">Can't reach the Kotler API. Is the server running? (uvicorn kotler.server:app)</div>;
  return <AppShell me={me.data} />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected />}>
        <Route index element={page(<Overview />)} />
        <Route path="inbox" element={page(<Inbox />)} />
        <Route path="inbox/:channel/:id" element={page(<Inbox />)} />
        {["customers", "ask", "performance", "campaigns", "helpdesk", "studio"].map((p) => <Route key={p} path={p} element={<ComingSoon />} />)}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
