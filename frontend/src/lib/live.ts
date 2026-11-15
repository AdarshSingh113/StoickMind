import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import type { LiveEvent } from "./api";

/** One live connection for the whole app (Server-Sent Events). New messages refresh the inbox queries, so every
 * screen showing conversations updates by itself. EventSource reconnects automatically after network blips and
 * resends the last event id, so nothing is missed. */
export function useLiveInbox(): boolean {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    const es = new EventSource("/api/v1/inbox/stream");
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.addEventListener("message", (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as LiveEvent;
      qc.invalidateQueries({ queryKey: ["inbox"] });
      qc.invalidateQueries({ queryKey: ["conversation", ev.channel, ev.external_id] });
      const viewing = location.pathname.startsWith("/inbox");
      const fresh = Date.now() - new Date(ev.created_at.replace(" ", "T")).getTime() < 120_000;  // not old/demo events
      if (fresh && ev.direction === "in" && (ev.handler === "human" || ev.needs_human) && !document.hidden) {
        toast(`${ev.display_name ?? "Customer"} needs a reply`, {
          description: ev.text.slice(0, 90),
          action: viewing ? undefined : { label: "Open", onClick: () => location.assign(`/inbox/${ev.channel}/${encodeURIComponent(ev.external_id)}`) },
        });
      }
    });
    return () => es.close();
  }, [qc]);
  return connected;
}
