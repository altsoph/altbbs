"""Echomail federation over a shared Telegram channel.

Bots cannot message bots -- but bots CAN post to and read from a
channel they co-admin. So altBBS instances federate FidoNet-style:

- the sysops create ONE private channel and add every participating
  bot as an admin (needs "post messages"; admins receive all posts)
- each instance sets BBS_ECHO_CHANNEL (the channel id) and a unique
  BBS_ECHO_ID (its network name)
- a sysop flags boards as echoes with /echo <board_id> <TAG>
- posts by real callers on an echo board are published to the channel
  as JSON; every peer imports posts it hasn't seen into its board with
  the same tag, attributing them to ghost users like handle@ORIGIN
- dedup by msgid ("ORIGIN.localid"); reply chains are re-linked via
  the msgid<->local mapping, so threads survive the crossing

Zero servers, zero open ports: the hub is Telegram itself. Missed
posts survive in getUpdates for ~24h of downtime.
"""

import json
import logging

from .config import Config
from .db import DB

log = logging.getLogger("tgbbs.echonet")
nodelog = logging.getLogger("tgbbs.node")

PROTO = 1
MAX_BODY = 3000


def is_echo_chat(cfg: Config, chat) -> bool:
    want = str(cfg.echo_channel).strip()
    if not want:
        return False
    if str(chat.id) == want:
        return True
    uname = getattr(chat, "username", None)
    return bool(uname) and want.lstrip("@").lower() == uname.lower()


async def publish(bot, cfg: Config, db: DB, msg_id: int) -> None:
    """Push a locally-authored echo-board post to the channel."""
    if not (cfg.echo_channel and bot):
        return
    m = db.message(msg_id)
    if not m or m["author_id"] < 0:
        return  # ghosts (wire, imports) never echo -- no loops
    b = db.board(m["board_id"])
    if not b or not b["echo_tag"]:
        return
    msgid = f"{cfg.echo_id}.{m['id']}"
    ref = db.echo_msgid_for_local(m["reply_to"]) if m["reply_to"] else None
    payload = json.dumps({
        "v": PROTO,
        "net": "altnet",
        "echo": b["echo_tag"],
        "origin": cfg.echo_id,
        "msgid": msgid,
        "author": m["handle"],
        "body": m["body"][:MAX_BODY],
        "ts": m["created"],
        "re": ref,
    }, ensure_ascii=False)
    try:
        await bot.send_message(cfg.echo_channel, payload,
                               disable_notification=True)
        db.echo_mark(msgid, m["id"])
        nodelog.info("echo out: %s -> %s", msgid, b["echo_tag"])
    except Exception as e:
        log.warning("echo publish of %s failed: %s", msgid, e)


def import_post(cfg: Config, db: DB, text: str) -> int | None:
    """Import one channel payload; returns the new local msg id or None."""
    try:
        d = json.loads(text)
    except ValueError:
        return None  # not ours: humans may chat in the channel, fine
    if not isinstance(d, dict) or d.get("v") != PROTO:
        return None
    msgid, echo, origin = d.get("msgid"), d.get("echo"), d.get("origin")
    author, body = d.get("author"), d.get("body")
    if not all(isinstance(x, str) and x for x in (msgid, echo, origin,
                                                  author, body)):
        return None
    if origin == cfg.echo_id:
        return None  # our own post reflected back
    if db.echo_known(msgid):
        return None  # already imported
    board = db.board_by_echo(echo)
    if not board:
        db.echo_mark(msgid, None)  # not subscribed: remember, skip forever
        return None
    ghost = db.ensure_ghost(f"{author[:10]}@{origin[:8]}")
    reply_to = db.echo_local_for(d["re"]) if d.get("re") else None
    local_id = db.post(board["id"], ghost["id"], body[:MAX_BODY],
                       reply_to=reply_to)
    db.echo_mark(msgid, local_id)
    nodelog.info("echo in: %s -> %s as #%s", msgid, board["name"], local_id)
    return local_id


async def on_channel_post(bbs, update, ctx) -> None:
    post = update.channel_post
    if not post or not post.text:
        return
    if not is_echo_chat(bbs.cfg, post.chat):
        # discovery aid: the sysop needs this id for BBS_ECHO_CHANNEL
        nodelog.info("channel post from unconfigured chat id %s (%s) -- "
                     "set BBS_ECHO_CHANNEL=%s to make it the echo hub",
                     post.chat.id, post.chat.title or "?", post.chat.id)
        return
    import_post(bbs.cfg, bbs.db, post.text)
