"""One listening scan, the schedule that repeats it, and the command line.

A scan: for every active watch term and every enabled source, fetch what's new, keep only mentions we haven't
seen (the database refuses duplicates), add rule fields (ingredients, alerts), label with AI, then delete what's
past its retention period. Every scan is recorded (what was fetched, quota used, which sources failed and why).

The schedule runs inside the server: a background thread wakes every few minutes and starts a scan when one is
due (Listening page -> "every N hours"; 0 = off). Or run it as its own process:

    python -m kotler.listening scan               one scan now
    python -m kotler.listening watch --every 6    a scan every 6 hours, forever
    python -m kotler.listening brief              write a brief from what was collected
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from kotler import db
from kotler.listening import analyze, sources, store

_lock = threading.Lock()
PENDING_LIMIT = 200          # mentions labelled per scan (each batch of 20 is one LLM call)


class ScanBusy(Exception):
    pass


def _since() -> datetime:
    """Look back to just before the last successful scan, at most 30 days."""
    last = db.query_one("SELECT started_at FROM listening_runs WHERE status IN ('ok', 'partial') "
                        "ORDER BY id DESC LIMIT 1")
    floor = datetime.now(timezone.utc) - timedelta(days=30)
    if not last:
        return floor
    started = datetime.strptime(last["started_at"], store.FMT).replace(tzinfo=timezone.utc) - timedelta(hours=2)
    return max(started, floor)


def label_pending(llm, limit: int = PENDING_LIMIT) -> int:
    rows = db.query_df("SELECT id, source, term, title, text FROM listening_mentions WHERE sentiment IS NULL "
                       "ORDER BY id DESC LIMIT ?", (limit,)).to_dict("records")
    if not rows:
        return 0
    labels = analyze.label(llm, rows)
    with db.get_conn() as conn:
        for r, lbl in zip(rows, labels):
            # If the text literally names the watch term it IS relevant (the model once called "Best Vitamin C
            # Serums 2026" off-topic for "vitamin c serum"). The model only judges items that don't name it.
            relevant = True if analyze.names_it(r["term"] or "", f"{r.get('title') or ''} {r['text']}") \
                else lbl.get("relevant")
            if analyze.is_promotion(r["text"]):
                lbl = {**lbl, "kind": "promotion"}
            conn.execute("UPDATE listening_mentions SET sentiment = ?, kind = ?, aspects = ?, gist = ?, language = ?, "
                         "relevant = ?, labelled_by = ? WHERE id = ?",
                         (lbl["sentiment"], lbl["kind"], json.dumps(lbl["aspects"]), lbl.get("gist"),
                          lbl.get("language") or analyze.detect_language(r["text"]) or "en",
                          None if relevant is None else int(relevant), lbl["labelled_by"], r["id"]))
    return len(rows)


def scan(trigger: str = "manual", llm="auto") -> dict:
    """Run one scan. Raises ScanBusy if one is already running."""
    if not _lock.acquire(blocking=False):
        raise ScanBusy("A scan is already running.")
    try:
        return _scan(trigger, llm)
    finally:
        _lock.release()


def _scan(trigger: str, llm) -> dict:
    store.ensure_tables()
    if llm == "auto":
        from kotler.llm import get_llm
        llm = get_llm()
    with db.get_conn() as conn:
        conn.execute("UPDATE listening_runs SET status = 'error', finished_at = ? WHERE status = 'running'",
                     (store.now(),))        # a scan interrupted by a restart
        run_id = conn.execute("INSERT INTO listening_runs (started_at, status, trigger) VALUES (?, 'running', ?)",
                              (store.now(), trigger)).lastrowid
    since, enabled = _since(), store.enabled_sources()
    report = {s: {"fetched": 0, "error": None} for s in enabled}
    fetched, units, broken = [], 0, set()
    for term in store.terms(active_only=True):
        for src in enabled:
            if src in broken:
                continue
            try:
                if src == "youtube":
                    items, used = sources.youtube(term, since)
                    units += used
                else:
                    items = {"bluesky": sources.bluesky, "news": sources.news}[src](term, since)
            except sources.SourceError as e:
                report[src]["error"] = str(e)
                broken.add(src)            # same problem for every term (missing key, quota): stop asking
                continue
            except Exception as e:         # network trouble: note it, keep going with the other sources
                report[src]["error"] = f"{type(e).__name__}: {str(e)[:160]}"
                continue
            if term["kind"] in ("brand", "competitor") and src != "youtube":
                items = [m for m in items if analyze.names_it(term["term"], f"{m.get('title') or ''} {m['text']}")]
            for m in items:
                # The watch term and video title are context: a comment under a "vitamin c serum review" video is
                # about vitamin C even if it never says so.
                text = f"{term['term']} {m.get('title') or ''} {m['text']}"
                m.update(term_id=term["id"], term=term["term"], term_kind=term["kind"],
                         ingredients=analyze.ingredients(text), alert=analyze.alert(m["text"], term["kind"]))
            report[src]["fetched"] += len(items)
            fetched += items
    new_ids = store.save_mentions(fetched)
    labelled = label_pending(llm)
    purged = store.purge_expired()
    errors = [s for s, r in report.items() if r["error"]]
    status = "error" if enabled and len(errors) == len(enabled) else "partial" if errors else "ok"
    with db.get_conn() as conn:
        conn.execute("UPDATE listening_runs SET finished_at = ?, status = ?, fetched = ?, new = ?, labelled = ?, "
                     "youtube_units = ?, report = ? WHERE id = ?",
                     (store.now(), status, len(fetched), len(new_ids), labelled, units,
                      json.dumps({"sources": report, "purged": purged, "since": since.strftime(store.FMT)}), run_id))
    return {"run_id": run_id, "status": status, "fetched": len(fetched), "new": len(new_ids), "labelled": labelled,
            "youtube_units": units, "sources": report, "purged": purged}


def scan_in_background(trigger: str = "manual") -> None:
    if _lock.locked():
        raise ScanBusy("A scan is already running.")
    threading.Thread(target=lambda: _safe_scan(trigger), daemon=True, name="listening-scan").start()


def _safe_scan(trigger: str) -> None:
    try:
        scan(trigger)
    except ScanBusy:
        pass
    except Exception as e:          # never kill the server's thread; the failure is visible as a run row
        with db.get_conn() as conn:
            conn.execute("UPDATE listening_runs SET status = 'error', finished_at = ?, report = ? WHERE status = 'running'",
                         (store.now(), json.dumps({"error": f"{type(e).__name__}: {str(e)[:300]}"})))


# ------------------------------------------------------------------ schedule
def due(now: datetime | None = None) -> bool:
    store.ensure_tables()
    every = int(store.setting("every_hours") or 0)
    if every <= 0:
        return False
    last = db.query_one("SELECT started_at FROM listening_runs ORDER BY id DESC LIMIT 1")
    now = now or datetime.now()
    return not last or now - datetime.strptime(last["started_at"], store.FMT) >= timedelta(hours=every)


def start_scheduler(check_every_s: int = 300) -> threading.Thread:
    """Background thread inside the server: checks every 5 minutes whether a scan is due."""
    def loop():
        while True:
            time.sleep(check_every_s)
            try:
                if due() and not _lock.locked():
                    _safe_scan("schedule")
            except Exception:
                pass                     # e.g. database briefly locked: try again next time
    t = threading.Thread(target=loop, daemon=True, name="listening-scheduler")
    t.start()
    return t


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Kotler AI social listening")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="run one scan now")
    w = sub.add_parser("watch", help="scan every N hours, forever")
    w.add_argument("--every", type=float, default=6)
    sub.add_parser("brief", help="write a brief from the collected mentions")
    args = ap.parse_args(argv)
    from kotler.bootstrap import prepare
    prepare()
    if args.cmd == "scan":
        print(json.dumps(scan("cli"), indent=2))
    elif args.cmd == "watch":
        while True:
            print(json.dumps(scan("cli")), flush=True)
            time.sleep(args.every * 3600)
    else:
        from kotler.listening.insights import write_brief
        from kotler.llm import get_llm
        llm = get_llm()
        if llm is None:
            raise SystemExit("Set GEMINI_API_KEY to write a brief.")
        b = write_brief(llm)
        print(b.get("note") or "", b["text"], *[f"[{s['n']}] {s['url']}" for s in b["sources"]], sep="\n")
