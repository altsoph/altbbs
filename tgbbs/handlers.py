"""All bot logic: the state machine turning Telegram updates into BBS screens."""

import asyncio
import logging
import random
import re
import time
from collections import deque
from pathlib import Path

from telegram import (
    InlineKeyboardButton as Btn,
    InlineKeyboardMarkup as Kbd,
    Update,
    WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import art, asciiview, echonet
from .config import FILES_DIR, Config
from .db import DB
from .doors import DOORS, DoorAPI
from .render import esc, screen, status_line, trunc, ts, wrap

log = logging.getLogger("tgbbs")
nodelog = logging.getLogger("tgbbs.node")  # the classic sysop node log
chatlog = logging.getLogger("tgbbs.chatlog")  # full transcript (file handler)

HANDLE_RE = re.compile(r"^[a-zA-Z0-9._-]{2,16}$")


def web_payload(text: str, kbd: Kbd | None) -> dict:
    """Serialize a screen for the CRT web terminal."""
    rows = []
    if kbd:
        for r in kbd.inline_keyboard:
            row = [{"label": b.text, "data": b.callback_data}
                   for b in r if b.callback_data]
            if row:
                rows.append(row)
    return {"screen": text, "buttons": rows}

MAX_BODY = 2000  # keep posts well under Telegram's 4096-char screen limit
ONLINE_SECS = 300  # active within 5 min = online


class BBS:
    def __init__(self, cfg: Config, db: DB):
        self.cfg = cfg
        self.db = db
        self.sessions: dict[int, dict] = {}  # tg_id -> {'await': str|None, ...}
        self.chat_log: deque = deque(maxlen=200)  # (handle|'*', text)

    def sess(self, uid: int) -> dict:
        return self.sessions.setdefault(uid, {"await": None, "ctx": {}, "term": None})

    def touch_presence(self, update: Update) -> None:
        s = self.sess(update.effective_user.id)
        s["ts"] = time.time()
        s["cid"] = update.effective_chat.id

    def online_uids(self) -> list[int]:
        cut = time.time() - ONLINE_SECS
        return [uid for uid, s in self.sessions.items() if s.get("ts", 0) > cut]

    def chatters(self) -> list[int]:
        return [uid for uid, s in self.sessions.items() if s.get("chat")]

    @staticmethod
    def _hotkeys(kbd: Kbd | None) -> dict[str, str]:
        """Map button hotkey letters ([M], [Q], «/») to their actions."""
        keys: dict[str, str] = {}
        if not kbd:
            return keys
        for row in kbd.inline_keyboard:
            for b in row:
                label = b.text or ""
                if not b.callback_data:
                    # web_app buttons can't be triggered by typing (telegram
                    # needs a real tap) -- route the letter to the launcher
                    m = re.match(r"\[(\w)\]", label)
                    if m and b.web_app:
                        keys[m.group(1).upper()] = "crt"
                    continue
                m = re.match(r"\[(\w)\]", label)
                if m:
                    keys[m.group(1).upper()] = b.callback_data
                elif label.startswith("«"):
                    keys["<"] = b.callback_data
                elif label.endswith("»"):
                    keys[">"] = b.callback_data
        return keys

    # ── screen output ────────────────────────────────────────────────────
    async def show(self, update: Update, ctx, text: str, kbd: Kbd | None):
        """Edit the terminal message in place; fall back to sending a new one."""
        s = self.sess(update.effective_user.id)
        s["keys"] = self._hotkeys(kbd)  # typed hotkeys mirror this screen
        if getattr(update, "is_web", False):
            q = s.get("webq")
            if q is not None:
                q.put_nowait(web_payload(text, kbd))
            return
        chat_id = update.effective_chat.id
        if update.callback_query and update.callback_query.message:
            try:
                await update.callback_query.edit_message_text(
                    text, parse_mode=ParseMode.HTML, reply_markup=kbd)
                s["term"] = update.callback_query.message.message_id
                return
            except BadRequest as e:
                if "not modified" in str(e).lower():
                    return
        if s["term"]:
            try:
                await ctx.bot.edit_message_text(
                    text, chat_id=chat_id, message_id=s["term"],
                    parse_mode=ParseMode.HTML, reply_markup=kbd)
                return
            except BadRequest:
                pass
        msg = await ctx.bot.send_message(
            chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kbd)
        s["term"] = msg.message_id

    # ── auth ─────────────────────────────────────────────────────────────
    def caller(self, update: Update):
        u = self.db.user(update.effective_user.id)
        if u and u["banned"]:
            return None
        return u

    # ═════════════════════════ SCREENS ═══════════════════════════════════
    def scr_welcome(self, note: str = "  type your handle now:"):
        body = [
            trunc(f"  you have reached {self.cfg.bbs_name},", art.WIDTH),
            "  a private system inside the",
            "  telegram network.",
            "",
            trunc(f"  * {self.cfg.tagline} *", art.WIDTH),
        ] + art.WELCOME_LOGIN + [note, "  █"]
        return screen("carrier detected", body, logo=True), None

    def scr_main(self, user):
        st = self.db.stats()
        unread = self.db.inbox_count(user["id"], unread_only=True)
        body = [
            f"  welcome back, {trunc(user['handle'], 16)}",
            "",
            f"  callers: {st['calls']:<5} users: {st['users']}",
            f"  posts:   {st['msgs']:<5} files: {st['files']}",
            "",
            "  select from the menu below",
        ]
        mail_label = f"[E] MAIL ({unread})" if unread else "[E] MAIL"
        n_chat = len(self.chatters())
        chat_label = f"[C] CHAT ({n_chat})" if n_chat else "[C] CHAT"
        n_new = self.db.total_unread(user["id"], user["level"])
        scan_label = f"[N] NEWSCAN ({n_new})" if n_new else "[N] NEWSCAN"
        rows = [
            [Btn(scan_label, callback_data="scan"),
             Btn("[M] MSG BASES", callback_data="boards")],
            [Btn(mail_label, callback_data="mail:0"),
             Btn("[F] FILE AREAS", callback_data="areas")],
            [Btn("[D] DOORS", callback_data="doors"),
             Btn("[O] ONELINERS", callback_data="ones")],
            [Btn(chat_label, callback_data="chat"),
             Btn("[L] LAST CALLERS", callback_data="who")],
            [Btn("[U] USER LIST", callback_data="users:0")],
        ]
        if user["level"] >= 100:
            rows[-1].append(Btn("[S] SYSOP", callback_data="sysop"))
        if self.cfg.web_url:
            rows.append([Btn("[W] CRT TERMINAL",
                             web_app=WebAppInfo(url=self.cfg.web_url))])
        rows.append([Btn("[Q] QWK MAIL", callback_data="qwk"),
                     Btn("[G] LOGOFF", callback_data="logoff")])
        return screen("main menu", body, status_line(user), logo=True), Kbd(rows)

    # -- message bases ------------------------------------------------------
    def scr_boards(self, user):
        body = []
        rows = []
        for b in self.db.boards(user["level"]):
            mark = "≡" if b["echo_tag"] else " "
            body.append(f"{mark}{b['id']:>2} {trunc(b['name'], 18):<18} {b['n']:>4}")
            body.append(f"    {trunc(b['descr'], 28)}")
            rows.append([Btn(f"[{b['id']}] {b['name'].upper()}",
                             callback_data=f"board:{b['id']}:0")])
        body = [" ## base               msgs", " " + "·" * 30] + body
        rows.append([Btn("[Q] BACK", callback_data="menu")])
        return screen("message bases", body, status_line(user)), Kbd(rows)

    def scr_board(self, user, board_id: int, page: int):
        b = self.db.board(board_id)
        if not b or b["min_level"] > user["level"]:
            return self.scr_boards(user)
        n = self.db.board_msg_count(board_id)
        ps = self.cfg.page_size
        msgs = self.db.board_messages(board_id, ps, page * ps)
        body = [f"  «{trunc(b['name'], 24)}»  {n} msgs", ""]
        rows = []
        if not msgs:
            body += ["  no messages here yet.", "  be the first to post!"]
        for m in msgs:
            first = m["body"].splitlines()[0] if m["body"] else ""
            body.append(f" #{m['id']:<4} {trunc(m['handle'], 12):<12}"
                        f" {ts(m['created'], False)}")
            body.append(f"   {trunc(first, 30)}")
            rows.append([Btn(f"READ #{m['id']} · {trunc(first, 24)}",
                             callback_data=f"msg:{m['id']}")])
        nav = []
        if page > 0:
            nav.append(Btn("« PREV", callback_data=f"board:{board_id}:{page-1}"))
        if (page + 1) * ps < n:
            nav.append(Btn("NEXT »", callback_data=f"board:{board_id}:{page+1}"))
        if nav:
            rows.append(nav)
        rows.append([Btn("[P] POST", callback_data=f"post:{board_id}"),
                     Btn("[Q] BACK", callback_data="boards")])
        return screen(b["name"], body, status_line(user)), Kbd(rows)

    def scr_msg(self, user, msg_id: int):
        m = self.db.message(msg_id)
        if not m:
            return self.scr_boards(user)
        b = self.db.board(m["board_id"])
        if b["min_level"] > user["level"]:
            return self.scr_boards(user)
        body = [
            f"  msg  : #{m['id']} @ {trunc(b['name'], 16)}",
            f"  from : {m['handle']}",
            f"  date : {ts(m['created'])}",
        ]
        if m["reply_to"]:
            body.append(f"  re   : #{m['reply_to']}")
        body.append(" " + "·" * 30)
        body += wrap(m["body"], prefix=" ")[:40]
        prev_id, next_id = self.db.msg_neighbors(m)
        nav = []
        if prev_id:
            nav.append(Btn("« OLDER", callback_data=f"msg:{prev_id}"))
        if next_id:
            nav.append(Btn("NEWER »", callback_data=f"msg:{next_id}"))
        rows = []
        if nav:
            rows.append(nav)
        rows.append([Btn("[R] REPLY", callback_data=f"reply:{m['id']}"),
                     Btn("[Q] BACK", callback_data=f"board:{m['board_id']}:0")])
        return screen("read message", body, status_line(user)), Kbd(rows)

    # -- newscan: the unread-message loop -----------------------------------
    def _scan_next(self, user):
        """Advance to the next unread message across all visible boards."""
        for b in self.db.boards(user["level"]):
            m = self.db.next_unread(user["id"], b["id"])
            if m:
                self.db.set_ptr(user["id"], b["id"], m["id"])
                left = self.db.unread_count(user["id"], b["id"])
                return self.scr_scan_msg(user, b, m, left)
        return self.scr_scan_done(user)

    def scr_scan_msg(self, user, b, m, left: int):
        body = [
            f"  base : {trunc(b['name'], 16)} ({left} new)",
            f"  from : {m['handle']}",
            f"  date : {ts(m['created'])}",
        ]
        if m["reply_to"]:
            body.append(f"  re   : #{m['reply_to']}")
        body.append(" " + "·" * 30)
        body += wrap(m["body"], prefix=" ")[:36]
        rows = [
            [Btn("[N] NEXT", callback_data="scan"),
             Btn("[S] SKIP BASE", callback_data=f"scanskip:{b['id']}")],
            [Btn("[R] REPLY", callback_data=f"reply:{m['id']}"),
             Btn("[A] ALL READ", callback_data="scanall")],
            [Btn("[Q] STOP", callback_data="menu")],
        ]
        return screen("newscan", body, status_line(user)), Kbd(rows)

    def scr_scan_done(self, user):
        body = [
            "  ▄▄▄ newscan complete ▄▄▄",
            "",
            "  no new messages anywhere.",
            "  you are fully synchronized",
            "  with the tower.",
        ]
        rows = [[Btn("[Q] MENU", callback_data="menu")]]
        return screen("newscan", body, status_line(user)), Kbd(rows)

    def scr_input(self, user, title: str, prompt_lines: list[str], back: str):
        body = prompt_lines + ["", "  (or hit ABORT below)", "  █"]
        kbd = Kbd([[Btn("[A] ABORT", callback_data=back)]])
        return screen(title, body, status_line(user)), kbd

    # -- mail -----------------------------------------------------------------
    def scr_mail(self, user, page: int):
        n = self.db.inbox_count(user["id"])
        ps = self.cfg.page_size
        items = self.db.inbox(user["id"], ps, page * ps)
        body = [f"  private mail · {n} in box", ""]
        rows = []
        if not items:
            body.append("  your mailbox is empty.")
        for m in items:
            flag = " " if m["is_read"] else "*"
            first = m["body"].splitlines()[0] if m["body"] else ""
            body.append(f" {flag}#{m['id']:<4} {trunc(m['handle'], 12):<12}"
                        f" {ts(m['created'], False)}")
            body.append(f"   {trunc(first, 30)}")
            rows.append([Btn(f"{'· ' if m['is_read'] else '* '}#{m['id']} "
                             f"from {trunc(m['handle'], 14)}",
                             callback_data=f"rdml:{m['id']}")])
        nav = []
        if page > 0:
            nav.append(Btn("« PREV", callback_data=f"mail:{page-1}"))
        if (page + 1) * ps < n:
            nav.append(Btn("NEXT »", callback_data=f"mail:{page+1}"))
        if nav:
            rows.append(nav)
        rows.append([Btn("[W] WRITE", callback_data="sendml"),
                     Btn("[Q] BACK", callback_data="menu")])
        return screen("mail room", body, status_line(user)), Kbd(rows)

    def scr_mail_read(self, user, mail_id: int):
        m = self.db.mail_msg(mail_id)
        if not m or m["to_id"] != user["id"]:
            return self.scr_mail(user, 0)
        self.db.mark_read(mail_id)
        body = [
            f"  from : {m['handle']}",
            f"  date : {ts(m['created'])}",
            " " + "·" * 30,
        ] + wrap(m["body"], prefix=" ")[:40]
        rows = [[Btn("[R] REPLY", callback_data=f"replml:{m['from_id']}"),
                 Btn("[Q] BACK", callback_data="mail:0")]]
        return screen("private mail", body, status_line(user)), Kbd(rows)

    # -- files -----------------------------------------------------------------
    def scr_areas(self, user):
        body = [" ## area              files", " " + "·" * 30]
        rows = []
        for a in self.db.areas(user["level"]):
            body.append(f" {a['id']:>2} {trunc(a['name'], 18):<18} {a['n']:>4}")
            body.append(f"    {trunc(a['descr'], 28)}")
            rows.append([Btn(f"[{a['id']}] {a['name'].upper()}",
                             callback_data=f"area:{a['id']}:0")])
        rows.append([Btn("[Q] BACK", callback_data="menu")])
        return screen("file areas", body, status_line(user)), Kbd(rows)

    def scr_area(self, user, area_id: int, page: int):
        a = self.db.area(area_id)
        if not a or a["min_level"] > user["level"]:
            return self.scr_areas(user)
        n = self.db.area_file_count(area_id)
        ps = self.cfg.page_size
        fs = self.db.area_files(area_id, ps, page * ps)
        body = [f"  «{trunc(a['name'], 24)}»  {n} files", ""]
        rows = []
        if not fs:
            body.append("  no files yet. upload one!")
        for f in fs:
            kb = f["size"] // 1024
            diz1 = (f["descr"] or "(no description)").splitlines()[0]
            body.append(f" #{f['id']:<3} {trunc(f['name'], 20):<20} {kb:>5}k")
            body.append(f"   {trunc(diz1, 30)}")
            rows.append([Btn(f"#{f['id']} {trunc(f['name'], 24)}",
                             callback_data=f"file:{f['id']}")])
        nav = []
        if page > 0:
            nav.append(Btn("« PREV", callback_data=f"area:{area_id}:{page-1}"))
        if (page + 1) * ps < n:
            nav.append(Btn("NEXT »", callback_data=f"area:{area_id}:{page+1}"))
        if nav:
            rows.append(nav)
        rows.append([Btn("[U] UPLOAD", callback_data=f"upl:{area_id}"),
                     Btn("[Q] BACK", callback_data="areas")])
        return screen(a["name"], body, status_line(user)), Kbd(rows)

    def scr_upload(self, user, area):
        body = [
            f"  target: «{trunc(area['name'], 22)}»",
            "",
            "  the node is ready to receive.",
            "",
            "  send any DOCUMENT (as file,",
            "  not photo) to this chat now",
            "  and it lands in this area.",
            "",
            "  you'll be asked for a",
            "  FILE_ID.DIZ description after.",
            "",
            "  ▄▄▄ awaiting carrier ▄▄▄",
        ]
        rows = [[Btn("[A] ABORT", callback_data=f"area:{area['id']}:0")]]
        return screen("upload", body, status_line(user)), Kbd(rows)

    def scr_file(self, user, file_id: int):
        f = self.db.file(file_id)
        if not f:
            return self.scr_areas(user)
        a = self.db.area(f["area_id"])
        if a["min_level"] > user["level"]:
            return self.scr_areas(user)
        body = [
            f"  file : {trunc(f['name'], 24)}",
            f"  size : {f['size']//1024}k ({f['size']} bytes)",
            f"  from : {f['handle']}",
            f"  date : {ts(f['created'])}",
            f"  gets : {f['downloads']}",
            " " + "·" * 30,
            "  FILE_ID.DIZ:",
        ] + wrap(f["descr"] or "(no description)", prefix="  ")[:12]
        top = [Btn("[D] DOWNLOAD", callback_data=f"get:{f['id']}")]
        if asciiview.is_image_name(f["name"]):
            top.append(Btn("[V] VIEW ASCII", callback_data=f"view:{f['id']}"))
        elif asciiview.is_text_name(f["name"]):
            top.append(Btn("[V] PREVIEW", callback_data=f"txt:{f['id']}:0"))
        rows = [top]
        if user["level"] >= 100:
            rows.append([Btn("[X] DELETE", callback_data=f"delx:{f['id']}"),
                         Btn("[M] MOVE", callback_data=f"mv:{f['id']}"),
                         Btn("[E] DIZ", callback_data=f"ediz:{f['id']}")])
        elif user["id"] == f["uploader_id"]:
            rows.append([Btn("[E] EDIT DIZ", callback_data=f"ediz:{f['id']}")])
        rows.append([Btn("[Q] BACK", callback_data=f"area:{f['area_id']}:0")])
        return screen("file info", body, status_line(user)), Kbd(rows)

    def scr_del_confirm(self, user, f):
        body = [
            f"  file : #{f['id']} {trunc(f['name'], 20)}",
            f"  from : {f['handle']}",
            "",
            "  remove this file from the",
            "  board? (the record is gone,",
            "  the bytes stay on telegram)",
        ]
        rows = [[Btn("[Y] YES, NUKE IT", callback_data=f"delyes:{f['id']}"),
                 Btn("[N] KEEP", callback_data=f"file:{f['id']}")]]
        return screen("confirm delete", body, status_line(user)), Kbd(rows)

    def scr_move(self, user, f):
        body = [f"  moving #{f['id']} {trunc(f['name'], 18)}",
                "  pick the target area:"]
        rows = [[Btn(f"[{a['id']}] {a['name'].upper()}",
                     callback_data=f"mvto:{f['id']}:{a['id']}")]
                for a in self.db.areas(user["level"]) if a["id"] != f["area_id"]]
        rows.append([Btn("[Q] CANCEL", callback_data=f"file:{f['id']}")])
        return screen("move file", body, status_line(user)), Kbd(rows)

    # -- chat pit (multi-node teleconference) -----------------------------------
    def scr_chat(self, user):
        names = []
        for uid in self.chatters():
            u = self.db.user(uid)
            if u:
                names.append(u["handle"])
        body = wrap("in the pit: " + (", ".join(names) or "nobody"), prefix=" ")
        body.append(" " + "·" * 30)
        lines: list[str] = []
        for h, txt in self.chat_log:
            if h == "*":
                lines.append(f" * {trunc(txt, 30)}")
            else:
                lines += wrap(f"{h}> {txt}", prefix=" ")
        body += lines[-16:] if lines else ["", "  dead air. say something."]
        body += ["", "  just type to talk"]
        rows = [[Btn("[Q] LEAVE", callback_data="menu")]]
        return screen("chat pit", body, status_line(user)), Kbd(rows)

    async def _chat_broadcast(self, bot) -> None:
        """Live-update every chatter's terminal with the current chat screen."""
        for uid in self.chatters():
            s = self.sessions.get(uid)
            u = self.db.user(uid)
            if not (s and u):
                continue
            text, kbd = self.scr_chat(u)
            if s.get("webq") is not None:  # CRT terminal gets a live push
                s["webq"].put_nowait(web_payload(text, kbd))
                continue
            if not (s.get("term") and s.get("cid")):
                continue
            try:
                await bot.edit_message_text(
                    text, chat_id=s["cid"], message_id=s["term"],
                    parse_mode=ParseMode.HTML, reply_markup=kbd)
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    log.debug("chat broadcast to %s failed: %s", uid, e)

    def _chat_add(self, who: str, text: str) -> None:
        """Append to the in-memory chat + the on-disk transcript."""
        self.chat_log.append((who, text))
        if who == "*":
            chatlog.info("* %s", text)
        else:
            chatlog.info("<%s> %s", who, text)

    async def _chat_leave(self, user, ctx) -> None:
        s = self.sess(user["id"])
        if s.get("chat"):
            s["chat"] = False
            self._chat_add("*", f"{user['handle']} left")
            nodelog.info("%s left chat", user["handle"])
            await self._chat_broadcast(ctx.bot)

    # -- ascii viewer -------------------------------------------------------------
    def scr_ascii(self, user, lines: list[str], title: str, back: str):
        body = [f" {l}" for l in lines] or ["  (nothing to see)"]
        rows = [[Btn("[Q] BACK", callback_data=back)]]
        return screen(trunc(title, 24), body, status_line(user)), Kbd(rows)

    # -- QWK offline mail ------------------------------------------------------
    def scr_qwk(self, user, note: str = ""):
        n = self.db.total_unread(user["id"], user["level"])
        body = [
            "  offline mail, 1987 style:",
            "  a .QWK packet of everything",
            "  you haven't read, for any",
            "  period QWK reader.",
            "",
            f"  unread messages: {n}",
            "",
            "  downloading ADVANCES your",
            "  newscan pointers -- that is",
            "  the point of offline mail.",
        ]
        if note:
            body += ["", f"  {note}"]
        rows = []
        if n:
            rows.append([Btn("[D] DOWNLOAD PACKET", callback_data="qwkgo")])
        rows.append([Btn("[Q] BACK", callback_data="menu")])
        return screen("offline mail", body, status_line(user)), Kbd(rows)

    async def _qwk_send(self, update, ctx, user):
        from . import qwk
        data, count, advance = qwk.build_qwk(self.db, self.cfg, user)
        if not count:
            return self.scr_qwk(user, note="nothing unread. lucky you.")
        try:
            await ctx.bot.send_document(
                update.effective_chat.id, data,
                filename=f"{self.cfg.echo_id}.QWK",
                caption=f"{count} msgs · open with any QWK reader")
        except Exception as e:
            log.warning("qwk send failed: %s", e)
            return self.scr_qwk(user, note="transfer failed. try again.")
        for board_id, top in advance.items():
            self.db.set_ptr(user["id"], board_id, top)
        nodelog.info("%s downloaded a QWK packet (%s msgs)",
                     user["handle"], count)
        return self.scr_qwk(user, note=f"sent: {count} msgs packed. "
                                       "pointers advanced.")

    # -- CRT terminal launcher ---------------------------------------------
    def scr_crt(self, user):
        if not self.cfg.web_url:
            body = ["  the CRT terminal is offline.",
                    "  (sysop: run tunnel.ps1 and", "  restart the bot)"]
            rows = [[Btn("[Q] BACK", callback_data="menu")]]
        else:
            body = [
                "  the CRT terminal is a mini",
                "  app. telegram only launches",
                "  those from a real button tap,",
                "  so here it is -- one tap away:",
                "",
                "  ▄▀ phosphor · scanlines ▀▄",
                "  ▀▄ curvature · bloom    ▄▀",
            ]
            rows = [[Btn("░▒▓ JACK IN ▓▒░",
                         web_app=WebAppInfo(url=self.cfg.web_url))],
                    [Btn("[Q] BACK", callback_data="menu")]]
        return screen("crt terminal", body, status_line(user)), Kbd(rows)

    # -- door games -----------------------------------------------------------
    def scr_doors(self, user):
        bal = self.db.credits(user["id"])
        body = [
            "  step into the arcade.",
            "",
            f"  your credits: {bal}",
            "  earn: +5/call +2/post",
            "        +25/upload",
            "",
        ]
        rows = []
        for i, d in enumerate(DOORS.values(), 1):
            body.append(f"  [{i}] {trunc(d.title, 26)}")
            body.append(f"      {trunc(d.diz, 28)}")
            rows.append([Btn(f"[{i}] {d.title.upper()}",
                             callback_data=f"dr:{d.key}:enter")])
        if not DOORS:
            body.append("  the arcade is dark.")
        rows.append([Btn("[Q] BACK", callback_data="menu")])
        return screen("door games", body, status_line(user)), Kbd(rows)

    def _door_screen(self, user, key: str, payload: str):
        door = DOORS.get(key)
        if not door:
            return self.scr_doors(user)
        s = self.sess(user["id"])
        s["door"], s["await"] = key, "door"
        try:
            title, body, rows = door.handle(DoorAPI(self.db, key), user, payload)
        except Exception:
            log.exception("door %s crashed on %r", key, payload)
            return self.scr_doors(user)
        kbd = [[Btn(lbl, callback_data=act[1:] if act.startswith("!")
                    else f"dr:{key}:{act}")
                for lbl, act in row] for row in rows]
        kbd.append([Btn("[Q] LEAVE", callback_data="doors")])
        return screen(title, body, status_line(user)), Kbd(kbd)

    # -- social ------------------------------------------------------------------
    def scr_ones(self, user):
        body = ["  wisdom of the wall:", ""]
        for o in self.db.oneliners(10):
            body += wrap(f"«{o['text']}»", prefix=" ")
            body.append(f"{('-- ' + o['handle']).rjust(30)}")
        if len(body) == 2:
            body.append("  the wall is blank. tag it!")
        rows = [[Btn("[A] ADD YOURS", callback_data="addone"),
                 Btn("[Q] BACK", callback_data="menu")]]
        return screen("oneliners", body, status_line(user)), Kbd(rows)

    def scr_who(self, user):
        online = []
        for uid in self.online_uids():
            u = self.db.user(uid)
            if u:
                online.append(u["handle"])
        body = wrap("online now: " + (", ".join(online) or "just the wind"),
                    prefix=" ")
        body += ["", " handle        calls last seen", " " + "·" * 30]
        for u in self.db.last_callers(10):
            body.append(f" {trunc(u['handle'], 12):<13} {u['calls']:>4}"
                        f" {ts(u['last_call'], False)}")
        rows = [[Btn("[Q] BACK", callback_data="menu")]]
        return screen("last callers", body, status_line(user)), Kbd(rows)

    def scr_users(self, user, page: int):
        us = self.db.users()
        ps = 12
        chunk = us[page * ps:(page + 1) * ps]
        body = [" handle        lvl  joined", " " + "·" * 30]
        for u in chunk:
            mark = {255: "▓", 100: "▒"}.get(u["level"], "░")
            body.append(f" {mark}{trunc(u['handle'], 12):<13} {u['level']:>3}"
                        f"  {ts(u['joined'], False)}")
        nav = []
        if page > 0:
            nav.append(Btn("« PREV", callback_data=f"users:{page-1}"))
        if (page + 1) * ps < len(us):
            nav.append(Btn("NEXT »", callback_data=f"users:{page+1}"))
        rows = ([nav] if nav else []) + [[Btn("[Q] BACK", callback_data="menu")]]
        return screen("user list", body, status_line(user)), Kbd(rows)

    def scr_sysop(self, user):
        body = [
            "  sysop toolbox",
            "",
            "  commands (type in chat):",
            "  /setlevel handle n",
            "  /ban handle   /unban handle",
            "  /invite tg_user_id",
            "  /fetchnews (run wire now)",
            "  /echo board_id TAG (- clears)",
            "",
            "  file control lives on each",
            "  file's info screen:",
            "  [X] delete [M] move [E] diz",
            "",
            f"  system is {'OPEN' if self.cfg.new_users_open else 'CLOSED (invite)'}",
        ]
        rows = [[Btn("[B] NEW MSG BASE", callback_data="mkboard"),
                 Btn("[F] NEW FILE AREA", callback_data="mkarea")],
                [Btn("[Q] BACK", callback_data="menu")]]
        return screen("sysop office", body, status_line(user)), Kbd(rows)

    def scr_logoff(self, user):
        body = list(art.LOGOFF)
        ones = self.db.oneliners(50)
        if ones:
            o = random.choice(ones)
            body += ["   ░▒▓ parting wisdom ▓▒░", ""]
            body += wrap(f"«{o['text']}»", prefix="   ")
            body.append(("-- " + o["handle"]).rjust(30))
        rows = [[Btn("[R] RECONNECT", callback_data="reconnect")]]
        return screen("carrier lost", body, ""), Kbd(rows)

    def scr_text(self, user, f, lines: list[str], page: int):
        ps = 24
        pages = max(1, -(-len(lines) // ps))
        page = max(0, min(page, pages - 1))
        body = [f"  {trunc(f['name'], 22)} · pg {page + 1}/{pages}",
                " " + "·" * 30]
        body += [f" {l}" for l in lines[page * ps:(page + 1) * ps]] or \
                ["  (empty file)"]
        nav = []
        if page > 0:
            nav.append(Btn("« PREV", callback_data=f"txt:{f['id']}:{page-1}"))
        if page + 1 < pages:
            nav.append(Btn("NEXT »", callback_data=f"txt:{f['id']}:{page+1}"))
        rows = ([nav] if nav else []) + \
            [[Btn("[Q] BACK", callback_data=f"file:{f['id']}")]]
        return screen("text viewer", body, status_line(user)), Kbd(rows)

    async def _preview_file(self, ctx, user, file_id: int, page: int):
        """Paged text preview of a file-area file."""
        f = self.db.file(file_id)
        if not f:
            return self.scr_areas(user)
        a = self.db.area(f["area_id"])
        if a["min_level"] > user["level"]:
            return self.scr_areas(user)
        s = self.sess(user["id"])
        cached = s.get("preview")
        if not cached or cached[0] != file_id:
            src = f["tg_file_id"]
            try:
                if src.startswith("local:"):
                    data = (FILES_DIR / Path(src[6:]).name).read_bytes()
                else:
                    if (f["size"] or 0) > asciiview.MAX_BYTES:
                        return self.scr_text(user, f, ["too big to preview"], 0)
                    tg_file = await ctx.bot.get_file(src)
                    data = bytes(await tg_file.download_as_bytearray())
                lines = asciiview.text_to_lines(data)
                nodelog.info("%s previewed #%s %s",
                             user["handle"], f["id"], f["name"])
            except Exception as e:
                log.warning("preview of #%s failed: %s", file_id, e)
                lines = ["could not read that file."]
            s["preview"] = (file_id, lines)
            cached = s["preview"]
        return self.scr_text(user, f, cached[1], page)

    async def _view_file(self, update, ctx, user, file_id: int):
        """Render a file-area image as ASCII art."""
        f = self.db.file(file_id)
        if not f:
            return self.scr_areas(user)
        a = self.db.area(f["area_id"])
        if a["min_level"] > user["level"]:
            return self.scr_areas(user)
        back = f"file:{file_id}"
        src = f["tg_file_id"]
        try:
            if src.startswith("local:"):
                data = (FILES_DIR / Path(src[6:]).name).read_bytes()
            else:
                if (f["size"] or 0) > asciiview.MAX_BYTES:
                    return self.scr_ascii(user, ["too big for the viewer",
                                                 "(20 MB getFile limit)"],
                                          f["name"], back)
                tg_file = await ctx.bot.get_file(src)
                data = bytes(await tg_file.download_as_bytearray())
            lines = await asyncio.to_thread(asciiview.image_to_ascii, data)
            nodelog.info("%s viewed #%s %s as ascii",
                         user["handle"], f["id"], f["name"])
        except Exception as e:
            log.warning("ascii view of #%s failed: %s", file_id, e)
            lines = ["could not decode that image."]
        return self.scr_ascii(user, lines, f["name"], back)

    # ═════════════════════════ UPDATE HANDLERS ═══════════════════════════
    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private":
            return
        uid = update.effective_user.id
        user = self.db.user(uid)
        if user and user["banned"]:
            return
        s = self.sess(uid)
        s["term"] = None  # force a fresh terminal message on /start
        self.touch_presence(update)
        if user:
            self.db.touch_call(uid)
            user = self.db.user(uid)
            nodelog.info("CALL %s (tg id %s), call #%s",
                         user["handle"], uid, user["calls"])
            text, kbd = self.scr_main(user)
        else:
            if not self.cfg.new_users_open and not self.db.has_invite(uid):
                await update.message.reply_text(
                    "<pre>this system is CLOSED.\n"
                    "ask the sysop for an invite.\n"
                    f"your id: {uid}</pre>", parse_mode=ParseMode.HTML)
                return
            s["await"] = "handle"
            text, kbd = self.scr_welcome()
        await self.show(update, ctx, text, kbd)

    async def cmd_help(self, update: Update, ctx):
        await update.message.reply_text(
            "<pre>/start  - (re)connect to the BBS\n"
            "/menu   - redraw main menu\n"
            "everything else is buttons +\n"
            "typing when the BBS asks you.</pre>",
            parse_mode=ParseMode.HTML)

    async def cmd_menu(self, update: Update, ctx):
        user = self.caller(update)
        if not user:
            return await self.cmd_start(update, ctx)
        self.sess(user["id"])["await"] = None
        self.sess(user["id"])["term"] = None
        text, kbd = self.scr_main(user)
        await self.show(update, ctx, text, kbd)

    # sysop text commands ---------------------------------------------------
    async def cmd_setlevel(self, update: Update, ctx):
        user = self.caller(update)
        if not user or user["level"] < 255:
            return
        try:
            handle, lvl = ctx.args[0], int(ctx.args[1])
            target = self.db.user_by_handle(handle)
            assert target and 0 <= lvl <= 255
        except (IndexError, ValueError, AssertionError):
            await update.message.reply_text("usage: /setlevel handle 0-255")
            return
        self.db.set_level(target["id"], lvl)
        await update.message.reply_text(f"{target['handle']} -> level {lvl}")

    async def cmd_ban(self, update: Update, ctx, banned=True):
        user = self.caller(update)
        if not user or user["level"] < 100:
            return
        target = self.db.user_by_handle(ctx.args[0]) if ctx.args else None
        if not target or target["level"] >= user["level"]:
            await update.message.reply_text("usage: /ban handle (below your level)")
            return
        self.db.set_banned(target["id"], banned)
        await update.message.reply_text(
            f"{target['handle']} {'BANNED' if banned else 'unbanned'}")

    async def cmd_unban(self, update: Update, ctx):
        await self.cmd_ban(update, ctx, banned=False)

    async def cmd_echo(self, update: Update, ctx):
        """Sysop: /echo <board_id> <TAG>  (TAG '-' clears the echo flag)."""
        user = self.caller(update)
        if not user or user["level"] < 100:
            return
        try:
            board = self.db.board(int(ctx.args[0]))
            tag = ctx.args[1].upper()[:16]
            assert board and (tag == "-" or re.match(r"^[A-Z0-9._-]+$", tag))
        except (IndexError, ValueError, AssertionError):
            await update.message.reply_text(
                "usage: /echo <board_id> <TAG>   (- clears)")
            return
        self.db.set_echo_tag(board["id"], "" if tag == "-" else tag)
        nodelog.info("%s set echo tag of board %s to %s",
                     user["handle"], board["id"], tag)
        echoes = "\n".join(f"{b['id']:>3} {b['name']:<16} {b['echo_tag']}"
                           for b in self.db.echo_boards()) or "(none)"
        await update.message.reply_text(
            f"<pre>▓▒░ echo boards ░▒▓\n{echoes}</pre>",
            parse_mode=ParseMode.HTML)

    async def on_channel_post(self, update: Update, ctx):
        await echonet.on_channel_post(self, update, ctx)

    async def cmd_fetchnews(self, update: Update, ctx):
        user = self.caller(update)
        if not user or user["level"] < 100:
            return
        from . import newsfeed
        await update.message.reply_text("dialing the wire services...")
        counts = await newsfeed.run_import(self.db, self.cfg)
        report = "\n".join(
            f"{src:<10} {'FETCH FAILED' if n < 0 else f'{n} new'}"
            for src, n in counts.items())
        await update.message.reply_text(
            f"<pre>▓▒░ news wire ░▒▓\n{report}</pre>", parse_mode=ParseMode.HTML)

    async def cmd_invite(self, update: Update, ctx):
        user = self.caller(update)
        if not user or user["level"] < 100:
            return
        try:
            self.db.add_invite(int(ctx.args[0]))
            await update.message.reply_text("invite recorded.")
        except (IndexError, ValueError):
            await update.message.reply_text("usage: /invite tg_user_id")

    # button presses ---------------------------------------------------------
    async def on_button(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        user = self.caller(update)
        if not user:
            await q.answer("no carrier. /start to log in.")
            return
        nodelog.info("%s: [%s]", user["handle"], q.data)
        # ACK the button press NOW: slow work (getFile, image conversion)
        # can outlive the callback's validity window, and a failed late
        # answer() would abort before the screen is drawn
        try:
            await q.answer()
        except BadRequest:
            pass
        await self._act(update, ctx, user, q.data or "menu")

    async def _act(self, update: Update, ctx, user, data: str) -> None:
        """Route an action -- button press or typed hotkey -- and render."""
        self.touch_presence(update)
        s = self.sess(user["id"])
        cmd, *args = data.split(":")
        s["await"] = None  # any navigation aborts pending input
        if cmd != "chat":
            await self._chat_leave(user, ctx)
        if cmd != "dr":
            s["door"] = None

        try:
            if cmd == "menu":
                out = self.scr_main(user)
            elif cmd == "reconnect":
                # coming back from the logoff screen counts as a new call
                self.db.touch_call(user["id"])
                user = self.db.user(user["id"])
                out = self.scr_main(user)
            elif cmd == "scan":
                out = self._scan_next(user)
            elif cmd == "scanskip":
                b = self.db.board(int(args[0]))
                if b:
                    top = self.db.conn.execute(
                        "SELECT MAX(id) m FROM messages WHERE board_id=?",
                        (b["id"],)).fetchone()["m"]
                    if top:
                        self.db.set_ptr(user["id"], b["id"], top)
                out = self._scan_next(user)
            elif cmd == "scanall":
                self.db.mark_all_read(user["id"], user["level"])
                nodelog.info("%s marked all read", user["handle"])
                out = self.scr_main(user)
            elif cmd == "qwk":
                out = self.scr_qwk(user)
            elif cmd == "qwkgo":
                out = await self._qwk_send(update, ctx, user)
            elif cmd == "crt":
                out = self.scr_crt(user)
            elif cmd == "doors":
                out = self.scr_doors(user)
            elif cmd == "dr":
                out = self._door_screen(user, args[0],
                                        ":".join(args[1:]) or "enter")
            elif cmd == "boards":
                out = self.scr_boards(user)
            elif cmd == "board":
                out = self.scr_board(user, int(args[0]), int(args[1]))
            elif cmd == "msg":
                out = self.scr_msg(user, int(args[0]))
            elif cmd == "post":
                s["await"], s["ctx"] = "post", {"board": int(args[0])}
                out = self.scr_input(user, "post message", [
                    "  type your message now.",
                    "  first line works as subject.",
                    f"  (max {MAX_BODY} chars)"],
                    back=f"board:{args[0]}:0")
            elif cmd == "reply":
                m = self.db.message(int(args[0]))
                s["await"], s["ctx"] = "reply", {"msg": int(args[0])}
                out = self.scr_input(user, "reply", [
                    f"  replying to #{args[0]}",
                    f"  by {m['handle'] if m else '?'}",
                    "", "  type your reply now."],
                    back=f"msg:{args[0]}")
            elif cmd == "mail":
                out = self.scr_mail(user, int(args[0]))
            elif cmd == "rdml":
                out = self.scr_mail_read(user, int(args[0]))
            elif cmd == "sendml":
                s["await"], s["ctx"] = "ml_to", {}
                out = self.scr_input(user, "write mail", [
                    "  send private mail.",
                    "", "  type the recipient's handle:"],
                    back="mail:0")
            elif cmd == "replml":
                to = self.db.user(int(args[0]))
                if to:
                    s["await"], s["ctx"] = "ml_body", {"to": to["id"]}
                    out = self.scr_input(user, "write mail", [
                        f"  to: {to['handle']}",
                        "", "  type your message now."],
                        back="mail:0")
                else:
                    out = self.scr_mail(user, 0)
            elif cmd == "areas":
                s["ctx"].pop("area", None)
                out = self.scr_areas(user)
            elif cmd == "area":
                s["ctx"]["area"] = int(args[0])  # uploads land here
                out = self.scr_area(user, int(args[0]), int(args[1]))
            elif cmd == "file":
                out = self.scr_file(user, int(args[0]))
            elif cmd == "get":
                f = self.db.file(int(args[0]))
                if f:
                    a = self.db.area(f["area_id"])
                    if a["min_level"] <= user["level"]:
                        self.db.bump_downloads(f["id"])
                        src = f["tg_file_id"]
                        if src.startswith("local:"):
                            # bundled file served from disk (bootstrap content)
                            path = FILES_DIR / Path(src[6:]).name
                            src = path.open("rb") if path.is_file() else None
                        if src is not None:
                            await ctx.bot.send_document(
                                update.effective_chat.id, src,
                                filename=f["name"],
                                caption=f"#{f['id']} {f['name']} · "
                                        f"{f['downloads'] + 1} gets")
                            nodelog.info("%s downloaded #%s %s",
                                         user["handle"], f["id"], f["name"])
                out = self.scr_file(user, int(args[0]))
            elif cmd == "view":
                out = await self._view_file(update, ctx, user, int(args[0]))
            elif cmd == "txt":
                out = await self._preview_file(ctx, user,
                                               int(args[0]), int(args[1]))
            elif cmd == "upl":
                a = self.db.area(int(args[0]))
                if a and a["min_level"] <= user["level"]:
                    s["ctx"]["area"] = a["id"]
                    out = self.scr_upload(user, a)
                else:
                    out = self.scr_areas(user)
            elif cmd == "delx" and user["level"] >= 100:
                f = self.db.file(int(args[0]))
                out = self.scr_del_confirm(user, f) if f else self.scr_areas(user)
            elif cmd == "delyes" and user["level"] >= 100:
                f = self.db.file(int(args[0]))
                if f:
                    self.db.delete_file(f["id"])
                    nodelog.info("%s DELETED file #%s %s",
                                 user["handle"], f["id"], f["name"])
                    out = self.scr_area(user, f["area_id"], 0)
                else:
                    out = self.scr_areas(user)
            elif cmd == "mv" and user["level"] >= 100:
                f = self.db.file(int(args[0]))
                out = self.scr_move(user, f) if f else self.scr_areas(user)
            elif cmd == "mvto" and user["level"] >= 100:
                f = self.db.file(int(args[0]))
                a = self.db.area(int(args[1]))
                if f and a:
                    self.db.move_file(f["id"], a["id"])
                    nodelog.info("%s moved file #%s to area %s",
                                 user["handle"], f["id"], a["name"])
                    out = self.scr_file(user, f["id"])
                else:
                    out = self.scr_areas(user)
            elif cmd == "ediz":
                f = self.db.file(int(args[0]))
                if f and (user["level"] >= 100 or user["id"] == f["uploader_id"]):
                    s["await"] = "filedesc"
                    s["ctx"] = {"area": f["area_id"], "file": f["id"]}
                    out = self.scr_input(user, "edit file_id.diz", [
                        f"  file: {trunc(f['name'], 22)}",
                        "", "  type the new description:"],
                        back=f"file:{f['id']}")
                else:
                    out = self.scr_areas(user)
            elif cmd == "chat":
                if not s.get("chat"):
                    s["chat"] = True
                    self._chat_add("*", f"{user['handle']} joined")
                    nodelog.info("%s joined chat", user["handle"])
                s["await"] = "chat"
                out = self.scr_chat(user)
                await self.show(update, ctx, *out)
                await self._chat_broadcast(ctx.bot)
                return
            elif cmd == "ones":
                out = self.scr_ones(user)
            elif cmd == "addone":
                s["await"] = "one"
                out = self.scr_input(user, "tag the wall", [
                    "  one line, max 60 chars.",
                    "  make it count."], back="ones")
            elif cmd == "who":
                out = self.scr_who(user)
            elif cmd == "users":
                out = self.scr_users(user, int(args[0]))
            elif cmd == "sysop" and user["level"] >= 100:
                out = self.scr_sysop(user)
            elif cmd == "mkboard" and user["level"] >= 100:
                s["await"] = "mkboard"
                out = self.scr_input(user, "new msg base", [
                    "  type: name | description"], back="sysop")
            elif cmd == "mkarea" and user["level"] >= 100:
                s["await"] = "mkarea"
                out = self.scr_input(user, "new file area", [
                    "  type: name | description"], back="sysop")
            elif cmd == "logoff":
                out = self.scr_logoff(user)
            else:
                out = self.scr_main(user)
        except (ValueError, IndexError):
            out = self.scr_main(user)

        await self.show(update, ctx, *out)

    # typed text ---------------------------------------------------------------
    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private":
            return
        uid = update.effective_user.id
        user = self.db.user(uid)
        if user and user["banned"]:
            return
        self.touch_presence(update)
        s = self.sess(uid)
        mode = s["await"]
        text = (update.message.text or "").strip()
        if not mode:
            # typed hotkey acts like pressing the matching button
            if user and len(text) == 1:
                keys = s.get("keys")
                if not keys:
                    # fresh session (bot restarted): fall back to the main
                    # menu map so letters never silently dead-end
                    keys = self._hotkeys(self.scr_main(user)[1])
                    s["keys"] = keys
                data = keys.get(text.upper())
                if data:
                    try:
                        await update.message.delete()
                    except BadRequest:
                        pass
                    nodelog.info("%s typed %s -> [%s]",
                                 user["handle"], text.upper(), data)
                    await self._act(update, ctx, user, data)
            return

        # eat the input line to keep the terminal clean
        try:
            await update.message.delete()
        except BadRequest:
            pass

        if mode == "chat" and user:
            self._chat_add(user["handle"], text[:200])
            nodelog.info("%s @chat: %s", user["handle"], trunc(text, 60))
            await self._chat_broadcast(ctx.bot)
            return

        out = None
        if mode == "handle":
            if self.db.user(uid):
                out = self.scr_main(self.db.user(uid))
            elif not HANDLE_RE.match(text):
                out = self.scr_welcome()
            elif self.db.user_by_handle(text):
                out = self.scr_welcome("  handle taken! try another:")
            else:
                user = self.db.create_user(uid, text)
                s["await"] = None
                nodelog.info("NEW USER %s (tg id %s, level %s)",
                             user["handle"], uid, user["level"])
                out = self.scr_main(user)
        elif not user:
            return
        elif mode == "door" and s.get("door"):
            out = self._door_screen(user, s["door"], "text:" + text[:60])
        elif mode == "post":
            mid = self.db.post(s["ctx"]["board"], uid, text[:MAX_BODY])
            s["await"] = None
            self.db.add_credits(uid, 2)
            nodelog.info("%s posted msg #%s to board %s",
                         user["handle"], mid, s["ctx"]["board"])
            await echonet.publish(ctx.bot, self.cfg, self.db, mid)
            out = self.scr_msg(user, mid)
        elif mode == "reply":
            orig = self.db.message(s["ctx"]["msg"])
            if orig:
                mid = self.db.post(orig["board_id"], uid, text[:MAX_BODY],
                                   reply_to=orig["id"])
                self.db.add_credits(uid, 2)
                await echonet.publish(ctx.bot, self.cfg, self.db, mid)
                out = self.scr_msg(user, mid)
            else:
                out = self.scr_boards(user)
            s["await"] = None
        elif mode == "ml_to":
            target = self.db.user_by_handle(text)
            if target:
                s["await"], s["ctx"] = "ml_body", {"to": target["id"]}
                out = self.scr_input(user, "write mail", [
                    f"  to: {target['handle']}",
                    "", "  type your message now."], back="mail:0")
            else:
                out = self.scr_input(user, "write mail", [
                    f"  no such handle: {trunc(text, 16)}",
                    "", "  type the recipient's handle:"], back="mail:0")
        elif mode == "ml_body":
            to_id = s["ctx"]["to"]
            self.db.send_mail(uid, to_id, text[:MAX_BODY])
            s["await"] = None
            nodelog.info("%s mailed user %s", user["handle"], to_id)
            out = self.scr_mail(user, 0)
            await self._notify_mail(ctx, to_id, user["handle"])
        elif mode == "one":
            self.db.add_oneliner(uid, text[:60])
            s["await"] = None
            out = self.scr_ones(user)
        elif mode == "filedesc":
            self.db.set_file_descr(s["ctx"]["file"], text[:300])
            s["await"] = None
            out = self.scr_file(user, s["ctx"]["file"])
        elif mode in ("mkboard", "mkarea") and user["level"] >= 100:
            name, _, descr = text.partition("|")
            name, descr = name.strip()[:24], descr.strip()[:60]
            if name:
                (self.db.add_board if mode == "mkboard" else self.db.add_area)(
                    name, descr)
            s["await"] = None
            out = self.scr_sysop(user)
        else:
            s["await"] = None
            out = self.scr_main(user)

        if out:
            await self.show(update, ctx, *out)

    async def _notify_mail(self, ctx, to_id: int, from_handle: str):
        """Ping the recipient -- a new send, not a screen edit."""
        try:
            await ctx.bot.send_message(
                to_id,
                f"<pre>▓▒░ you've got mail! ░▒▓\nfrom: {esc(from_handle)}\n"
                f"/start and hit [E] MAIL</pre>",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass  # recipient may have blocked the bot

    async def _ascii_reply(self, update, ctx, user, tg_file_id: str,
                           size: int | None, title: str) -> None:
        """Convert a sent image to ASCII and show it on the terminal."""
        try:
            await update.message.delete()
        except BadRequest:
            pass
        if (size or 0) > asciiview.MAX_BYTES:
            lines = ["too big for the viewer", "(20 MB getFile limit)"]
        else:
            try:
                tg_file = await ctx.bot.get_file(tg_file_id)
                data = bytes(await tg_file.download_as_bytearray())
                lines = await asyncio.to_thread(asciiview.image_to_ascii, data)
                nodelog.info("%s ascii-viewed a sent image (%s)",
                             user["handle"], title)
            except Exception as e:
                log.warning("ascii view failed: %s", e)
                lines = ["could not decode that image."]
        out = self.scr_ascii(user, lines, title, back="menu")
        await self.show(update, ctx, *out)

    # photos: instant ascii viewer -------------------------------------------------
    async def on_photo(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private":
            return
        user = self.caller(update)
        if not user:
            return
        self.touch_presence(update)
        photo = update.message.photo[-1]  # largest rendition
        await self._ascii_reply(update, ctx, user, photo.file_id,
                                photo.file_size, "your photo")

    # documents (uploads) --------------------------------------------------------
    async def on_document(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private":
            return
        user = self.caller(update)
        if not user:
            return
        self.touch_presence(update)
        s = self.sess(user["id"])
        area_id = s["ctx"].get("area")
        doc = update.message.document
        if not area_id:
            # not in a file area: image documents go to the ascii viewer
            if asciiview.is_image_name(doc.file_name or ""):
                await self._ascii_reply(update, ctx, user, doc.file_id,
                                        doc.file_size, doc.file_name or "image")
                return
            await update.message.reply_text(
                "<pre>open a FILE AREA first, then\nsend the document again.</pre>",
                parse_mode=ParseMode.HTML)
            return
        a = self.db.area(area_id)
        if not a or a["min_level"] > user["level"]:
            return
        fid = self.db.add_file(area_id, user["id"], doc.file_id,
                               doc.file_name or "unnamed.bin", doc.file_size or 0)
        self.db.add_credits(user["id"], 25)
        nodelog.info("%s uploaded #%s %s (%sk) to area %s", user["handle"],
                     fid, doc.file_name, (doc.file_size or 0) // 1024, area_id)
        s["await"], s["ctx"] = "filedesc", {"area": area_id, "file": fid}
        try:
            await update.message.delete()
        except BadRequest:
            pass
        out = self.scr_input(user, "upload ok", [
            f"  received: {trunc(doc.file_name or '?', 22)}",
            f"  size: {(doc.file_size or 0)//1024}k",
            "",
            "  now type a FILE_ID.DIZ style",
            "  description for it:"], back=f"area:{area_id}:0")
        await self.show(update, ctx, *out)


def build_app(cfg: Config) -> Application:
    db = DB(cfg.db_path)
    bbs = BBS(cfg, db)

    async def _post_init(application: Application) -> None:
        if cfg.feed_enabled:
            from . import newsfeed
            application.create_task(newsfeed.feed_loop(db, cfg))
        if cfg.web_enabled:
            from . import webterm
            application.create_task(
                webterm.serve_forever(bbs, application.bot, cfg))

    app = Application.builder().token(cfg.token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", bbs.cmd_start))
    app.add_handler(CommandHandler("help", bbs.cmd_help))
    app.add_handler(CommandHandler("menu", bbs.cmd_menu))
    app.add_handler(CommandHandler("setlevel", bbs.cmd_setlevel))
    app.add_handler(CommandHandler("ban", bbs.cmd_ban))
    app.add_handler(CommandHandler("unban", bbs.cmd_unban))
    app.add_handler(CommandHandler("invite", bbs.cmd_invite))
    app.add_handler(CommandHandler("fetchnews", bbs.cmd_fetchnews))
    app.add_handler(CommandHandler("echo", bbs.cmd_echo))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST,
                                   bbs.on_channel_post))
    app.add_handler(CallbackQueryHandler(bbs.on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bbs.on_text))
    app.add_handler(MessageHandler(filters.Document.ALL, bbs.on_document))
    app.add_handler(MessageHandler(filters.PHOTO, bbs.on_photo))
    return app
