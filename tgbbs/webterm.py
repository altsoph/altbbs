"""CRT web terminal -- a Telegram Mini App front-end for the BBS.

Architecture (keeps the no-open-ports story intact):
- this module serves HTTP (the CRT page) + WebSocket on 127.0.0.1 only
- you expose it with an OUTBOUND-only tunnel:
      cloudflared tunnel --url http://localhost:8737
  and put the printed https URL into .env as BBS_WEB_URL
- the [W] CRT TERMINAL button on the main menu opens that URL as a
  Mini App; the page authenticates with Telegram-signed initData
  (HMAC, bot token as key), so callers are exactly their BBS users
- the terminal drives the SAME session machinery as the chat UI:
  buttons send callback data into BBS._act(), typed lines go through
  BBS.on_text() -- hotkeys, posting, mail, doors, chat all just work
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

log = logging.getLogger("tgbbs.webterm")
nodelog = logging.getLogger("tgbbs.node")

PAGE_PATH = Path(__file__).parent / "webterm.html"
AUTH_TIMEOUT = 15
MAX_AGE = 86400  # initData older than a day is stale


class WebUpdate:
    """Duck-typed telegram.Update: just enough for show()/on_text()."""

    is_web = True

    def __init__(self, uid: int):
        self.effective_user = SimpleNamespace(id=uid)
        self.effective_chat = SimpleNamespace(id=uid, type="private")
        self.callback_query = None
        self.message = None


class WebCtx:
    """Duck-typed context: real bot, so downloads/mail pings still work."""

    def __init__(self, bot):
        self.bot = bot


def validate_init_data(init_data: str, token: str) -> int | None:
    """Verify Telegram WebApp initData; return the telegram user id."""
    try:
        pairs = dict(parse_qsl(init_data[:4096], keep_blank_values=True))
        their_hash = pairs.pop("hash", "")
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        mine = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not (their_hash and hmac.compare_digest(mine, their_hash)):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > MAX_AGE:
            return None
        return int(json.loads(pairs["user"])["id"])
    except (ValueError, KeyError, TypeError):
        return None


def _process_request(connection, request):
    path = request.path.split("?", 1)[0]
    if path == "/ws":
        return None  # proceed with the websocket handshake
    headers = Headers()
    if path in ("/", "/index.html"):
        headers["Content-Type"] = "text/html; charset=utf-8"
        headers["Cache-Control"] = "no-store"
        # read per request: page tweaks apply without a bot restart
        return Response(HTTPStatus.OK, "OK", headers, PAGE_PATH.read_bytes())
    headers["Content-Type"] = "text/plain"
    return Response(HTTPStatus.NOT_FOUND, "Not Found", headers, b"404")


async def _session(bbs, bot, cfg, ws) -> None:
    # -- authenticate ------------------------------------------------------
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT)
        hello = json.loads(raw)
    except (TimeoutError, ValueError):
        return
    uid = None
    if cfg.web_dev and hello.get("dev"):
        uid = int(hello["dev"])  # test rig only; off unless BBS_WEB_DEV=1
    elif hello.get("auth"):
        uid = validate_init_data(str(hello["auth"]), cfg.token)
    if uid is None:
        await ws.send(json.dumps({"error": "auth failed. open this page "
                                           "through the bot's [W] button."}))
        return

    user = bbs.db.user(uid)
    if user and user["banned"]:
        await ws.send(json.dumps({"error": "NO CARRIER"}))
        return
    if not user and not cfg.new_users_open and not bbs.db.has_invite(uid):
        await ws.send(json.dumps({"error": f"this system is CLOSED. "
                                           f"your id: {uid}"}))
        return

    # -- attach to the session ---------------------------------------------
    s = bbs.sess(uid)
    queue: asyncio.Queue = asyncio.Queue()
    s["webq"] = queue
    up, cx = WebUpdate(uid), WebCtx(bot)
    if user:
        bbs.db.touch_call(uid)
        user = bbs.db.user(uid)
        nodelog.info("CALL %s (tg id %s) via CRT terminal, call #%s",
                     user["handle"], uid, user["calls"])
        await bbs.show(up, cx, *bbs.scr_main(user))
    else:
        s["await"] = "handle"
        await bbs.show(up, cx, *bbs.scr_welcome())

    async def pump_out():
        while True:
            await ws.send(json.dumps(await queue.get()))

    async def pump_in():
        async for raw_msg in ws:
            try:
                msg = json.loads(raw_msg)
            except ValueError:
                continue
            u = bbs.db.user(uid)
            try:
                if msg.get("data") and u and not u["banned"]:
                    data = str(msg["data"])[:64]
                    nodelog.info("%s @web: [%s]", u["handle"], data)
                    await bbs._act(up, cx, u, data)
                elif "text" in msg:
                    text = str(msg["text"])[:2000]
                    fup = WebUpdate(uid)
                    fup.message = SimpleNamespace(
                        text=text, delete=_noop, reply_text=_noop)
                    await bbs.on_text(fup, cx)
            except Exception:
                log.exception("web input failed for %s", uid)

    try:
        done, pending = await asyncio.wait(
            [asyncio.ensure_future(pump_out()),
             asyncio.ensure_future(pump_in())],
            return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    finally:
        if s.get("webq") is queue:
            s["webq"] = None
        u = bbs.db.user(uid)
        if u:
            await bbs._chat_leave(u, cx)
            nodelog.info("%s dropped carrier (web)", u["handle"])


async def _noop(*_a, **_k):
    return None


async def start(bbs, bot, cfg):
    """Start the local web-terminal server; returns the server object."""

    async def handler(ws):
        await _session(bbs, bot, cfg, ws)

    server = await serve(handler, "127.0.0.1", cfg.web_port,
                         process_request=_process_request)
    log.info("CRT terminal on http://127.0.0.1:%s -- tunnel it, e.g. "
             "cloudflared tunnel --url http://localhost:%s",
             cfg.web_port, cfg.web_port)
    return server


async def serve_forever(bbs, bot, cfg):
    await start(bbs, bot, cfg)
    await asyncio.Future()  # run until the app shuts down
