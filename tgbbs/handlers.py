"""All bot logic: the state machine turning Telegram updates into BBS screens."""

import logging
import random
import re
from pathlib import Path

from telegram import (
    InlineKeyboardButton as Btn,
    InlineKeyboardMarkup as Kbd,
    Update,
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

from . import art
from .config import FILES_DIR, Config
from .db import DB
from .render import esc, screen, status_line, trunc, ts, wrap

log = logging.getLogger("tgbbs")

HANDLE_RE = re.compile(r"^[a-zA-Z0-9._-]{2,16}$")
MAX_BODY = 2000  # keep posts well under Telegram's 4096-char screen limit


class BBS:
    def __init__(self, cfg: Config, db: DB):
        self.cfg = cfg
        self.db = db
        self.sessions: dict[int, dict] = {}  # tg_id -> {'await': str|None, ...}

    def sess(self, uid: int) -> dict:
        return self.sessions.setdefault(uid, {"await": None, "ctx": {}, "term": None})

    # ── screen output ────────────────────────────────────────────────────
    async def show(self, update: Update, ctx, text: str, kbd: Kbd | None):
        """Edit the terminal message in place; fall back to sending a new one."""
        s = self.sess(update.effective_user.id)
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
        rows = [
            [Btn("[M] MSG BASES", callback_data="boards"),
             Btn(mail_label, callback_data="mail:0")],
            [Btn("[F] FILE AREAS", callback_data="areas"),
             Btn("[O] ONELINERS", callback_data="ones")],
            [Btn("[L] LAST CALLERS", callback_data="who"),
             Btn("[U] USER LIST", callback_data="users:0")],
        ]
        if user["level"] >= 100:
            rows.append([Btn("[S] SYSOP", callback_data="sysop")])
        rows.append([Btn("[G] LOGOFF", callback_data="logoff")])
        return screen("main menu", body, status_line(user), logo=True), Kbd(rows)

    # -- message bases ------------------------------------------------------
    def scr_boards(self, user):
        body = []
        rows = []
        for b in self.db.boards(user["level"]):
            body.append(f" {b['id']:>2} {trunc(b['name'], 18):<18} {b['n']:>4}")
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
        body = [f"  «{trunc(a['name'], 24)}»  {n} files",
                "  to upload: just send the bot",
                "  a document while you are here", ""]
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
        rows.append([Btn("[Q] BACK", callback_data="areas")])
        return screen(a["name"], body, status_line(user)), Kbd(rows)

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
        rows = [[Btn("[D] DOWNLOAD", callback_data=f"get:{f['id']}"),
                 Btn("[Q] BACK", callback_data=f"area:{f['area_id']}:0")]]
        return screen("file info", body, status_line(user)), Kbd(rows)

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
        body = [" handle        calls last seen", " " + "·" * 30]
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
        if user:
            self.db.touch_call(uid)
            user = self.db.user(uid)
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
        s = self.sess(user["id"])
        data = q.data or "menu"
        cmd, *args = data.split(":")
        s["await"] = None  # any navigation aborts pending input

        try:
            if cmd == "menu":
                out = self.scr_main(user)
            elif cmd == "reconnect":
                # coming back from the logoff screen counts as a new call
                self.db.touch_call(user["id"])
                user = self.db.user(user["id"])
                out = self.scr_main(user)
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
                        await q.answer("transferring...")
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
                out = self.scr_file(user, int(args[0]))
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

        await q.answer()
        await self.show(update, ctx, *out)

    # typed text ---------------------------------------------------------------
    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private":
            return
        uid = update.effective_user.id
        user = self.db.user(uid)
        if user and user["banned"]:
            return
        s = self.sess(uid)
        mode = s["await"]
        text = (update.message.text or "").strip()
        if not mode:
            return  # stray chatter: the BBS only listens when it asked

        # eat the input line to keep the terminal clean
        try:
            await update.message.delete()
        except BadRequest:
            pass

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
                out = self.scr_main(user)
        elif not user:
            return
        elif mode == "post":
            mid = self.db.post(s["ctx"]["board"], uid, text[:MAX_BODY])
            s["await"] = None
            out = self.scr_msg(user, mid)
        elif mode == "reply":
            orig = self.db.message(s["ctx"]["msg"])
            if orig:
                mid = self.db.post(orig["board_id"], uid, text[:MAX_BODY],
                                   reply_to=orig["id"])
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

    # documents (uploads) --------------------------------------------------------
    async def on_document(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private":
            return
        user = self.caller(update)
        if not user:
            return
        s = self.sess(user["id"])
        area_id = s["ctx"].get("area")
        doc = update.message.document
        if not area_id:
            await update.message.reply_text(
                "<pre>open a FILE AREA first, then\nsend the document again.</pre>",
                parse_mode=ParseMode.HTML)
            return
        a = self.db.area(area_id)
        if not a or a["min_level"] > user["level"]:
            return
        fid = self.db.add_file(area_id, user["id"], doc.file_id,
                               doc.file_name or "unnamed.bin", doc.file_size or 0)
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

    app = Application.builder().token(cfg.token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", bbs.cmd_start))
    app.add_handler(CommandHandler("help", bbs.cmd_help))
    app.add_handler(CommandHandler("menu", bbs.cmd_menu))
    app.add_handler(CommandHandler("setlevel", bbs.cmd_setlevel))
    app.add_handler(CommandHandler("ban", bbs.cmd_ban))
    app.add_handler(CommandHandler("unban", bbs.cmd_unban))
    app.add_handler(CommandHandler("invite", bbs.cmd_invite))
    app.add_handler(CommandHandler("fetchnews", bbs.cmd_fetchnews))
    app.add_handler(CallbackQueryHandler(bbs.on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bbs.on_text))
    app.add_handler(MessageHandler(filters.Document.ALL, bbs.on_document))
    return app
