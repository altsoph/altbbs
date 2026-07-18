"""The news wire: scheduled import from HN, lobste.rs and shir-man.com.

Each source posts into its own board as the ghost user 'newswire'.
Dedup is by normalized URL across ALL sources (the trends dashboard
aggregates HN, so overlap is the norm, not the exception).
"""

import asyncio
import html as html_mod
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx  # dependency of python-telegram-bot

from .config import ROOT, Config
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


def strip_html(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return " ".join(html_mod.unescape(s).split())


def clip(s: str, n: int = 300) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0] + "…"


_META_DESC = [
    re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:|twitter:)?description'
               r'["\'][^>]*?content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*?(?:property|name)='
               r'["\'](?:og:|twitter:)?description["\']', re.I),
]


async def grab_snippet(client: httpx.AsyncClient, url: str,
                       limit: int = 300) -> str:
    """Fetch the article page and pull a description out of it."""
    try:
        r = await client.get(url)
        if "html" not in r.headers.get("content-type", "text/html"):
            return ""
        text = r.text[:400_000]
    except Exception as e:
        log.debug("snippet fetch %s failed: %s", url, e)
        return ""
    for pat in _META_DESC:
        m = pat.search(text)
        if m:
            sn = strip_html(m.group(1))
            if len(sn) > 20:
                return clip(sn, limit)
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", text, re.S | re.I):
        sn = strip_html(m.group(1))
        if len(sn) > 60:
            return clip(sn, limit)
    return ""


# ── fetchers: each returns [{title, url, comments, meta, snippet}] ───────
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
            "snippet": clip(strip_html(it.get("text") or "")),
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
            "snippet": clip(strip_html(it.get("description") or "")),
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
        # description = "<b>title</b> (Score: ...)<br/>summary<br/><b>Link:</b>..."
        summary = descr.split("<b>Link:</b>")[0]
        summary = re.sub(r"^.*?\(Score:[^)]*\)", "", summary, flags=re.S)
        items.append({
            "title": title,
            "url": url,
            "comments": cm.group(0) if cm else "",
            "meta": f"{score} {unit} · via {src or 'trends'}",
            "snippet": clip(strip_html(summary)),
        })
        if len(items) >= scan:
            break
    return items


# ── custom RSS/Atom feeds from an OPML file ─────────────────────────────
def find_opml(cfg: Config) -> Path | None:
    if cfg.feed_opml:
        p = Path(cfg.feed_opml)
        return p if p.is_absolute() else ROOT / p
    found = sorted(ROOT.glob("*.opml"))
    return found[0] if found else None


def load_opml(path: Path) -> dict[str, list[dict]]:
    """category -> [{'title', 'url'}], categories from <outline> nesting."""
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    cats: dict[str, list[dict]] = {}

    def walk(node, cat):
        for o in node.findall("outline"):
            if o.get("xmlUrl"):
                cats.setdefault(cat, []).append({
                    "title": (o.get("title") or o.get("text") or "feed").strip(),
                    "url": o.get("xmlUrl"),
                })
            else:
                walk(o, (o.get("title") or o.get("text") or cat).strip().lower())

    body = root.find("body")
    if body is not None:
        walk(body, "rss")
    return cats


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_date(s: str | None) -> float | None:
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s).timestamp()      # RFC 822 (RSS)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_feed_entries(xml_text: str, scan: int = 5) -> list[dict]:
    """Minimal RSS 2.0 / Atom parser: first `scan` entries of a feed."""
    root = ET.fromstring(xml_text)
    out = []
    for node in root.iter():
        if _strip_ns(node.tag) not in ("item", "entry"):
            continue
        title = link = desc = None
        date = None
        for c in node:
            t = _strip_ns(c.tag)
            if t == "title" and c.text:
                title = " ".join(c.text.split())
            elif t == "link":
                href = c.get("href")
                if href:                                  # Atom
                    if (c.get("rel") or "alternate") == "alternate" or not link:
                        link = href.strip()
                elif c.text and c.text.strip():           # RSS
                    link = c.text.strip()
            elif t in ("pubDate", "published", "updated", "date") and date is None:
                date = _parse_date(c.text)
            elif t in ("description", "summary") and desc is None:
                desc = c.text or "".join(c.itertext())
            elif t in ("encoded", "content") and desc is None:
                desc = c.text or "".join(c.itertext())    # content:encoded / Atom
        if title and link:
            out.append({"title": title, "url": link, "date": date,
                        "snippet": clip(strip_html(desc or ""))})
        if len(out) >= scan:
            break
    return out


async def fetch_opml_feed(client: httpx.AsyncClient,
                          sem: asyncio.Semaphore, feed: dict) -> list[dict]:
    async with sem:
        r = await client.get(feed["url"])
        r.raise_for_status()
        entries = parse_feed_entries(r.text)
    for e in entries:
        e["feed"] = feed["title"]
    return entries


async def import_opml(db: DB, cfg: Config, client: httpx.AsyncClient,
                      counts: dict) -> None:
    path = find_opml(cfg)
    if not path or not path.is_file():
        return
    try:
        cats = load_opml(path)
    except ET.ParseError as e:
        log.warning("opml %s unparseable: %s", path.name, e)
        return
    cutoff = time.time() - cfg.feed_max_age_days * 86400
    sem = asyncio.Semaphore(8)
    for cat, feeds in cats.items():
        bname = f"{cat[:20]} wire"
        b = db.board_by_name(bname)
        if not b:
            db.add_board(bname, f"auto: {len(feeds)} rss feeds from opml")
            b = db.board_by_name(bname)
        results = await asyncio.gather(
            *(fetch_opml_feed(client, sem, f) for f in feeds),
            return_exceptions=True)
        items = []
        for feed, res in zip(feeds, results):
            if isinstance(res, BaseException):
                log.warning("rss %s failed: %s", feed["url"], res)
                continue
            items += [e for e in res
                      if e["date"] is None or e["date"] >= cutoff]
        items.sort(key=lambda e: e["date"] or 0, reverse=True)
        for e in items:
            e["comments"] = ""
            e["meta"] = f"via {e['feed']}"
        counts[f"rss:{cat}"] = await post_new(
            db, cfg, client, b["id"], f"opml:{cat}", items)


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


def build_body(item: dict) -> str:
    title = item["title"].strip()
    lines = [title]
    snippet = (item.get("snippet") or "").strip()
    # some pages use the title as their description -- no value in repeating it
    if snippet and snippet.lower().rstrip(".…") != title.lower().rstrip(".…"):
        lines += ["", snippet]
    lines += ["", item["url"]]
    if item.get("comments") and norm_url(item["comments"]) != norm_url(item["url"]):
        lines.append(item["comments"])
    lines.append(item["meta"])
    return "\n".join(lines)[:2000]


async def post_new(db: DB, cfg: Config, client: httpx.AsyncClient,
                   board_id: int, source: str, items: list[dict]) -> int:
    """Post unseen items to a board, filling missing snippets from the URL."""
    new = 0
    for item in items:
        if new >= cfg.feed_max_per_source:
            break
        key = norm_url(item.get("url") or "")
        if not key or db.feed_seen(key):
            continue
        if not item.get("snippet"):
            item["snippet"] = await grab_snippet(client, item["url"])
        db.post(board_id, WIRE_UID, build_body(item))
        db.feed_mark(key, source)
        new += 1
    return new


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
            counts[source] = await post_new(
                db, cfg, client, boards[source], source, items)
        await import_opml(db, cfg, client, counts)
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
