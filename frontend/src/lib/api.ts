/** Typed client for the Kotler API. Same origin in production (FastAPI serves the app) and in development
 * (the Vite proxy), so the HttpOnly session cookie is sent automatically; no tokens in JavaScript. */

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : msg;
    } catch { /* not JSON */ }
    if (res.status === 401 && !path.endsWith("/auth/login")) window.dispatchEvent(new Event("kotler:logged-out"));
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const get = <T>(p: string) => request<T>(p);
export const post = <T>(p: string, body?: unknown) =>
  request<T>(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T>(p: string, body: unknown) => request<T>(p, { method: "PUT", body: JSON.stringify(body) });
export const del = <T>(p: string) => request<T>(p, { method: "DELETE" });
/** Build a query string, skipping empty values. */
export const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
};

// ------------------------------------------------------------------ types
export type Me = { user: string; brand: string; default_password: boolean };

export type Kpi = {
  key: string; label: string; value: number; previous: number; delta: number | null;
  format: "inr" | "int" | "pct"; good_when_up: boolean;
};
export type Insight = { tone: "good" | "bad" | "warn" | "neutral"; title: string; body: string };
export type Overview = {
  period: { days: number; start: string; end: string };
  kpis: Kpi[];
  repeat_rate_90d: number;
  daily: { day: string; gmv: number; net_revenue: number; orders: number }[];
  monthly: { month: string; net_revenue: number; orders: number; new_buyers: number; returning_buyers: number }[];
  top_products: { name: string; category: string; image_url: string | null; units: number; revenue: number }[];
  categories: { category: string; revenue: number }[];
  support: { open: number; escalated: number; ai_resolved_share: number; avg_resolution_hours: number;
             pending_approvals: number };
  inbox: { chats: number; needs_human: number; human: number };
  ai: { agent_turns: number; conversations: number; p95_s: number; guard_rate: number; escalation_rate: number;
        cost_inr: number };
  insights: Insight[];
};

export type Channel = "telegram" | "whatsapp" | "web";
export type ConversationSummary = {
  channel: Channel; external_id: string; display_name: string | null; customer_id: number | null;
  customer_name: string | null; city: string | null; agent_slug: string | null; handler: "ai" | "human";
  needs_human: number; marketing_opt_in: number; last_inbound_at: string | null; handoff_at: string | null;
  last_text: string | null; last_direction: "in" | "out" | null; last_author: string | null;
  last_at: string | null; last_id: number | null; unread: number;
};
export type InboxView = "all" | "needs_human" | "human" | "ai";
export type InboxList = { conversations: ConversationSummary[]; counts: Record<InboxView, number> };
export type Message = { id: number; direction: "in" | "out"; text: string; agent_slug: string | null; created_at: string;
  cards?: import("@/components/product").ProductCard[] };
export type CustomerProfile = {
  id: number; name: string; phone: string; email: string | null; city: string; state: string; tier: number;
  skin_type: string | null; preferred_language: string; acquisition_channel: string; created_at: string;
  orders: number; lifetime_value: number; last_order_at: string | null; segment?: string; churn_risk?: number;
  clv_12m?: number; open_tickets: number;
  recent_orders: { order_number: string; created_at: string; status: string; payment_method: string; total: number }[];
};
export type Conversation = {
  session: Pick<ConversationSummary, "channel" | "external_id" | "display_name" | "customer_id" | "agent_slug" |
    "handler" | "needs_human" | "marketing_opt_in" | "last_inbound_at" | "handoff_at">;
  can_reply: boolean;
  messages: Message[];
  notes: { id: number; author: string; text: string; created_at: string }[];
  customer: CustomerProfile | null;
};
export type AssistAction = "suggest" | "friendlier" | "shorter" | "hinglish" | "english" | "summarize";
export type LiveEvent = Message & {
  channel: Channel; external_id: string; display_name: string | null; needs_human: number; handler: string;
};

// ------------------------------------------------------------------ endpoints
const enc = encodeURIComponent;
export const api = {
  me: () => get<Me>("/api/v1/auth/me"),
  login: (password: string) => post<{ ok: boolean }>("/api/v1/auth/login", { password }),
  logout: () => post<{ ok: boolean }>("/api/v1/auth/logout"),
  overview: (days: number) => get<Overview>(`/api/v1/overview?days=${days}`),
  inbox: (view: InboxView, channel: string | null, q: string) =>
    get<InboxList>(`/api/v1/inbox?view=${view}${channel ? `&channel=${channel}` : ""}${q ? `&q=${enc(q)}` : ""}`),
  conversation: (ch: string, id: string) => get<Conversation>(`/api/v1/inbox/${ch}/${enc(id)}`),
  takeover: (ch: string, id: string) => post(`/api/v1/inbox/${ch}/${enc(id)}/takeover`),
  release: (ch: string, id: string) => post(`/api/v1/inbox/${ch}/${enc(id)}/release`),
  reply: (ch: string, id: string, text: string) => post(`/api/v1/inbox/${ch}/${enc(id)}/reply`, { text }),
  loadDemo: () => post<{ loaded: number }>("/api/v1/inbox/demo"),
  assist: (ch: string, id: string, action: AssistAction, draft = "") =>
    post<{ text: string; warnings: string[]; language: string }>(`/api/v1/inbox/${ch}/${enc(id)}/assist`, { action, draft }),
  addNote: (ch: string, id: string, text: string) => post(`/api/v1/inbox/${ch}/${enc(id)}/notes`, { text }),
  approvalsCount: async () => (await get<{ approvals: unknown[] }>("/api/v1/helpdesk/approvals")).approvals.length,
};
