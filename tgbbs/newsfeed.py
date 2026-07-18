"""The news wire: scheduled import from HN, lobste.rs and shir-man.com.

Each source posts into its own board as the ghost user 'newswire'.
Dedup is by normalized URL across ALL sources (the trends dashboard
aggregates HN, so overlap is the norm, not the exception).
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qsl, urlsplit

import httpx  # dependency of python-telegram-bot

from .config import Config
from .db import DB

log = logging.getLogger("tgbbs.newsfeed")

WIRE_UID = -200
WIRE_HANDLE = "newswire"
UA = {"User-Agent": "altBBS-newswire/0.1 (hobby BBS bot)"}

BOARDS = {
    "hn":       ("hn wire",       "auto: news.ycombinator.com top"),
    "lobsters": ("lobsters wire", "auto: lobste.rs hottest"),
    "trends":   ("trends wire",   "auto: shir-man.com top of the day"),
}

TRACKING_PARAMS = re.compile(r"^(utm_|ref$|ref_|fbclid|gclid)")


def norm_url(url: str) -> str:
    """Canonical dedup key: scheme/www/tracking-params/fragment-insensitive."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    query = "&".join(f"{k}={v}" for k, v in sorted(parse_qsl(parts.query))
                     if not TRACKING_PARAMS.match(k.lower()))
    return f"{host}{path}" + (f"?{query}" if query else "")


# ── fetchers: each returns [{title, url, comments, meta}] ────────────────
async def fetch_hn(client: httpx.AsyncClient, scan: int, min_score: int):
    r = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    ids = r.json()[:scan]
    items = []
    for sid in ids:
        try:
            it = (await client.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")).json()
        except (httpx.HTTPError, ValueError):
            continue
        if not it or it.get("type") != "story" or it.get("dead"):
            continue
        if it.get("score", 0) < min_score:
            continue
        comments = f"https://news.ycombinator.com/item?id={sid}"
        items.append({
            "title": it.get("title", "(untitled)"),
            "url": it.get("url") or comments,
            "comments": comments,
            "meta": f"{it.get('score', 0)} pts · "
                    f"{it.get('descendants', 0)} comments",
        })
    return items


async def fetch_lobsters(client: httpx.AsyncClient, scan: int):
    r = await client.get("https://lobste.rs/hottest.json")
    items = []
    for it in r.json()[:scan]:
        tags = " ".join(it.get("tags", [])[:4])
        items.append({
            "title": it.get("title", "(untitled)"),
            "url": it.get("url") or it.get("comments_url", ""),
            "comments": it.get("comments_url", ""),
            "meta": f"{it.get('score', 0)} pts · [{tags}]",
        })
    return items


async def fetch_trends(client: httpx.AsyncClient, scan: int):
    r = await client.get("https://shir-man.com/api/rss?sort=day")
    root = ET.fromstring(r.text)
    ns = {"sm": "https://shir-man.com/rss/ns#"}
    items = []
    for it in root.iter("item"):
        title = it.findtext("title") or "(untitled)"
        url = it.findtext("link") or ""
        src = it.findtext("sm:source", "", ns)
        score = it.findtext("sm:raw_score", "", ns)
        unit = it.findtext("sm:raw_score_unit", "pts", ns)
        descr = it.findtext("description") or ""
        cm = re.search(r"https://news\.ycombinator\.com/item\?id=\d+", descr)
        items.append({
            "title": title,
            "url": url,
            "comments": cm.group(0) if cm else "",
            "meta": f"{score} {unit} · via {src or 'trends'}",
        })
        if len(items) >= scan:
            break
    return items


# ── plumbing ──────────────────────────────────────────────────────────────
def ensure_wire(db: DB) -> dict[str, int]:
    """Create the newswire ghost user + wire boards. Returns source->board id."""
    if not db.user(WIRE_UID):
        from .db import now
        ts = now()
        db.conn.execute(
            "INSERT INTO users(id, handle, level, joined, last_call, calls) "
            "VALUES (?,?,?,?,?,?)", (WIRE_UID, WIRE_HANDLE, 10, ts, ts, 0))
        db.conn.commit()
    ids = {}
    for source, (name, descr) in BOARDS.items():
        b = db.board_by_name(name)
        if not b:
            db.add_board(name, descr)
            b = db.board_by_name(name)
        ids[source] = b["id"]
    return ids


def post_item(db: DB, board_id: int, source: str, item: dict) -> bool:
    key = norm_url(item["url"])
    if not key or db.feed_seen(key):
        return False
    lines = [item["title"].strip(), "", item["url"]]
    if item["comments"] and norm_url(item["comments"]) != key:
        lines.append(item["comments"])
    lines.append(item["meta"])
    db.post(board_id, WIRE_UID, "\n".join(lines)[:2000])
    db.feed_mark(key, source)
    return True


async def run_import(db: DB, cfg: Config) -> dict[str, int]:
    """Fetch all sources, post unseen items. Returns per-source new counts."""
    boards = ensure_wire(db)
    counts = {}
    async with httpx.AsyncClient(
            timeout=20, headers=UA, follow_redirects=True) as client:
        for source, fetcher in (
                ("hn", lambda c: fetch_hn(c, 30, cfg.feed_hn_min_score)),
                ("lobsters", lambda c: fetch_lobsters(c, 25)),
                ("trends", lambda c: fetch_trends(c, 25))):
            try:
                items = await fetcher(client)
            except Exception as e:
                log.warning("fetch %s failed: %s", source, e)
                counts[source] = -1
                continue
            new = 0
            for item in items:
                if new >= cfg.feed_max_per_source:
                    break
                if post_item(db, boards[source], source, item):
                    new += 1
            counts[source] = new
    log.info("news wire import: %s", counts)
    return counts


async def feed_loop(db: DB, cfg: Config) -> None:
    """Background task: first import shortly after boot, then on interval."""
    await asyncio.sleep(30)
    while True:
        try:
            await run_import(db, cfg)
        except Exception:
            log.exception("news wire import crashed; will retry next interval")
        await asyncio.sleep(cfg.feed_interval_min * 60)
