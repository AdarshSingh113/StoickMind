"""Where mentions come from. Each fetcher returns plain dicts in one shape, so the rest never cares about the source:

    {source, external_id, url, author, title, text, published_at, likes, language}

Only official, allowed access: the YouTube Data API (API key), Bluesky's public AppView API and the Google News
RSS search feed. Every fetcher caps how much it pulls per scan, so a scan stays inside free quotas.
"""

from __future__ import annotations

import html
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

TIMEOUT = 20
UA = {"User-Agent": "KotlerAI-listening/1.0 (learning project)"}
FMT = "%Y-%m-%d %H:%M:%S"

# Caps per term per scan. YouTube costs: a video search = 100 quota units, a page of comments = 1 unit;
# the free daily quota is 10,000 units, so 5 terms x 4 scans a day x 103 units ~ 2,100 units.
YOUTUBE_VIDEOS = 3
YOUTUBE_COMMENTS = 20
BLUESKY_POSTS = 25
NEWS_ITEMS = 12


class SourceError(Exception):
    """A source failed in a way the user can fix (missing key, quota, access). Shown on the Listening page."""


def http_get(url: str, params: dict | None = None, headers: dict | None = None) -> requests.Response:
    """The one network call (tests replace it with recorded responses)."""
    return requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=TIMEOUT)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(FMT) if dt.tzinfo else dt.strftime(FMT)


def _iso(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        return _utc(datetime.fromisoformat(ts.replace("Z", "+00:00")))
    except ValueError:
        return None


def _quoted(term: str) -> str:
    return f'"{term}"' if " " in term else term


# ------------------------------------------------------------------ YouTube
YT = "https://www.googleapis.com/youtube/v3"


def youtube_configured() -> bool:
    return bool(os.environ.get("YOUTUBE_API_KEY"))


def _yt(path: str, params: dict) -> dict:
    r = http_get(f"{YT}/{path}", params, {"x-goog-api-key": os.environ.get("YOUTUBE_API_KEY", "")})
    if r.status_code == 200:
        return r.json()
    try:
        err = r.json().get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        msg = err.get("message", "")
    except ValueError:
        reason, msg = "", r.text[:200]
    if reason == "commentsDisabled":
        return {"items": [], "comments_disabled": True}
    if reason in ("quotaExceeded", "dailyLimitExceeded"):
        raise SourceError("YouTube daily quota used up (10,000 units). It resets at midnight Pacific time.")
    if r.status_code in (400, 403) and ("API key" in msg or reason in ("keyInvalid", "accessNotConfigured", "forbidden")
                                         or "has not been used" in msg or "disabled" in msg):
        raise SourceError("YouTube refused the API key. Create a key in Google Cloud with the YouTube Data API v3 "
                          f"enabled. ({msg[:160]})")
    raise SourceError(f"YouTube error {r.status_code}: {msg[:200]}")


def youtube(term: dict, since: datetime) -> tuple[list[dict], int]:
    """Comments under recent review videos for the term. Returns (mentions, quota units used)."""
    if not youtube_configured():
        raise SourceError("Add YOUTUBE_API_KEY (free, from Google Cloud: enable 'YouTube Data API v3').")
    q = term["term"] if term["kind"] in ("brand", "competitor") else f"{term['term']} review"
    found = _yt("search", {"part": "snippet", "q": q, "type": "video", "maxResults": YOUTUBE_VIDEOS,
                           "order": "relevance", "regionCode": "IN",
                           "publishedAfter": (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")})
    units, out = 100, []
    for v in found.get("items", []):
        vid = (v.get("id") or {}).get("videoId")
        if not vid:
            continue
        title = html.unescape((v.get("snippet") or {}).get("title", ""))
        threads = _yt("commentThreads", {"part": "snippet", "videoId": vid, "maxResults": YOUTUBE_COMMENTS,
                                         "order": "time", "textFormat": "plainText"})
        units += 1
        for t in threads.get("items", []):
            top = (t.get("snippet") or {}).get("topLevelComment") or {}
            s = top.get("snippet") or {}
            text, published = (s.get("textOriginal") or s.get("textDisplay") or "").strip(), _iso(s.get("publishedAt"))
            if not text or not published or published < _utc(since):
                continue
            out.append({"source": "youtube", "external_id": top.get("id") or t.get("id"),
                        "url": f"https://www.youtube.com/watch?v={vid}&lc={top.get('id', '')}",
                        "author": s.get("authorDisplayName"), "title": title, "text": text,
                        "published_at": published, "likes": s.get("likeCount", 0)})
    return out, units


# ------------------------------------------------------------------ Bluesky
BSKY_HOSTS = ("https://public.api.bsky.app", "https://api.bsky.app")


def bluesky(term: dict, since: datetime) -> list[dict]:
    params = {"q": _quoted(term["term"]), "limit": BLUESKY_POSTS, "sort": "latest",
              "since": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if since.tzinfo
              else since.strftime("%Y-%m-%dT%H:%M:%SZ")}
    data, last = None, None
    for host in BSKY_HOSTS:                 # the documented public host sometimes refuses search; try the other
        r = http_get(f"{host}/xrpc/app.bsky.feed.searchPosts", params)
        if r.status_code == 200:
            data = r.json()
            break
        last = r.status_code
    if data is None:
        raise SourceError(f"Bluesky search refused the request ({last}). It may need a login now.")
    out = []
    for p in data.get("posts", []):
        rec, author = p.get("record") or {}, p.get("author") or {}
        text, uri = (rec.get("text") or "").strip(), p.get("uri", "")
        if not text or not uri:
            continue
        handle, rkey = author.get("handle", ""), uri.rsplit("/", 1)[-1]
        out.append({"source": "bluesky", "external_id": uri, "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                    "author": author.get("displayName") or handle, "title": "", "text": text,
                    "published_at": _iso(rec.get("createdAt")) or _iso(p.get("indexedAt")),
                    "likes": p.get("likeCount", 0), "language": (rec.get("langs") or [None])[0]})
    return out


# ------------------------------------------------------------------ Google News
NEWS = "https://news.google.com/rss/search"


def news(term: dict, since: datetime) -> list[dict]:
    r = http_get(NEWS, {"q": f"{_quoted(term['term'])} when:30d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    if r.status_code != 200:
        raise SourceError(f"Google News returned {r.status_code}.")
    body = r.content[:3_000_000]
    if b"<!DOCTYPE" in body or b"<!ENTITY" in body:    # an RSS feed has no business declaring entities
        raise SourceError("Google News sent something that isn't a plain RSS feed.")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise SourceError("Couldn't read the Google News feed.") from e
    out = []
    for item in root.iter("item"):
        title = html.unescape(item.findtext("title") or "").strip()
        link, guid = item.findtext("link"), item.findtext("guid") or item.findtext("link")
        publisher = (item.findtext("source") or "").strip()
        try:
            published = _utc(parsedate_to_datetime(item.findtext("pubDate") or ""))
        except (TypeError, ValueError):
            published = None
        if not title or not guid:
            continue
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3]
        out.append({"source": "news", "external_id": guid, "url": link, "author": publisher, "title": "",
                    "text": title, "published_at": published, "likes": 0, "language": "en"})
        if len(out) >= NEWS_ITEMS:
            break
    return out


SOURCES = {"youtube": "YouTube comments", "bluesky": "Bluesky posts", "news": "Google News"}


def status() -> list[dict]:
    """What the Listening page shows under 'Sources'."""
    return [{"source": "youtube", "label": SOURCES["youtube"], "ready": youtube_configured(),
             "needs": None if youtube_configured() else "YOUTUBE_API_KEY (free, Google Cloud)"},
            {"source": "bluesky", "label": SOURCES["bluesky"], "ready": True, "needs": None},
            {"source": "news", "label": SOURCES["news"], "ready": True, "needs": None}]
