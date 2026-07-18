"""SQLite storage. Everything lives in one local file -- no cloud, no server."""

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,          -- telegram user id
    handle     TEXT UNIQUE COLLATE NOCASE,
    level      INTEGER NOT NULL DEFAULT 10,  -- 10 user, 100 co-sysop, 255 sysop
    joined     INTEGER NOT NULL,
    last_call  INTEGER NOT NULL,
    calls      INTEGER NOT NULL DEFAULT 1,
    banned     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS invites (
    tg_id      INTEGER PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS boards (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    descr      TEXT NOT NULL DEFAULT '',
    min_level  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id   INTEGER NOT NULL REFERENCES boards(id),
    author_id  INTEGER NOT NULL REFERENCES users(id),
    reply_to   INTEGER,
    body       TEXT NOT NULL,
    created    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mail (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id    INTEGER NOT NULL REFERENCES users(id),
    to_id      INTEGER NOT NULL REFERENCES users(id),
    body       TEXT NOT NULL,
    created    INTEGER NOT NULL,
    is_read    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS file_areas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    descr      TEXT NOT NULL DEFAULT '',
    min_level  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id     INTEGER NOT NULL REFERENCES file_areas(id),
    uploader_id INTEGER NOT NULL REFERENCES users(id),
    tg_file_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    size        INTEGER NOT NULL DEFAULT 0,
    descr       TEXT NOT NULL DEFAULT '',
    created     INTEGER NOT NULL,
    downloads   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scan_ptr (
    user_id    INTEGER NOT NULL,
    board_id   INTEGER NOT NULL,
    last_seen  INTEGER NOT NULL DEFAULT 0,  -- highest message id read
    PRIMARY KEY (user_id, board_id)
);
CREATE TABLE IF NOT EXISTS feed_seen (
    key        TEXT PRIMARY KEY,             -- normalized url
    source     TEXT NOT NULL,
    seen       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS oneliners (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id  INTEGER NOT NULL REFERENCES users(id),
    text       TEXT NOT NULL,
    created    INTEGER NOT NULL
);
"""

SEED_BOARDS = [
    ("main hall", "general chatter", 0),
    ("demoscene", "gfx / sfx / code / parties", 0),
    ("tech dungeon", "hardware, code & retro", 0),
    ("sysop office", "staff only", 100),
]
SEED_AREAS = [
    ("incoming", "fresh uploads", 0),
    ("ansi+ascii art", "art packs & logos", 0),
    ("utils", "tools & tiny apps", 0),
]


def now() -> int:
    return int(time.time())


class DB:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._seed()

    def _seed(self) -> None:
        cur = self.conn.execute("SELECT COUNT(*) c FROM boards")
        if cur.fetchone()["c"] == 0:
            self.conn.executemany(
                "INSERT INTO boards(name, descr, min_level) VALUES (?,?,?)", SEED_BOARDS)
            self.conn.executemany(
                "INSERT INTO file_areas(name, descr, min_level) VALUES (?,?,?)", SEED_AREAS)
            self.conn.commit()

    # -- users ------------------------------------------------------------
    def user(self, tg_id: int):
        return self.conn.execute("SELECT * FROM users WHERE id=?", (tg_id,)).fetchone()

    def user_by_handle(self, handle: str):
        return self.conn.execute(
            "SELECT * FROM users WHERE handle=? COLLATE NOCASE", (handle,)).fetchone()

    def create_user(self, tg_id: int, handle: str):
        # very first real caller becomes the sysop
        # (bootstrap/system users have negative ids and don't count)
        first = self.conn.execute(
            "SELECT COUNT(*) c FROM users WHERE id > 0").fetchone()["c"] == 0
        level = 255 if first else 10
        ts = now()
        self.conn.execute(
            "INSERT INTO users(id, handle, level, joined, last_call) VALUES (?,?,?,?,?)",
            (tg_id, handle, level, ts, ts))
        self.conn.commit()
        return self.user(tg_id)

    def touch_call(self, tg_id: int) -> None:
        self.conn.execute(
            "UPDATE users SET last_call=?, calls=calls+1 WHERE id=?", (now(), tg_id))
        self.conn.commit()

    def set_level(self, tg_id: int, level: int) -> None:
        self.conn.execute("UPDATE users SET level=? WHERE id=?", (level, tg_id))
        self.conn.commit()

    def set_banned(self, tg_id: int, banned: bool) -> None:
        self.conn.execute("UPDATE users SET banned=? WHERE id=?", (int(banned), tg_id))
        self.conn.commit()

    def users(self, limit=200):
        return self.conn.execute(
            "SELECT * FROM users ORDER BY last_call DESC LIMIT ?", (limit,)).fetchall()

    def last_callers(self, limit=10):
        return self.conn.execute(
            "SELECT * FROM users ORDER BY last_call DESC LIMIT ?", (limit,)).fetchall()

    def add_invite(self, tg_id: int) -> None:
        self.conn.execute("INSERT OR IGNORE INTO invites(tg_id) VALUES (?)", (tg_id,))
        self.conn.commit()

    def has_invite(self, tg_id: int) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM invites WHERE tg_id=?", (tg_id,)).fetchone() is not None

    # -- boards / messages -------------------------------------------------
    def boards(self, max_level: int):
        return self.conn.execute(
            "SELECT b.*, (SELECT COUNT(*) FROM messages m WHERE m.board_id=b.id) n "
            "FROM boards b WHERE min_level<=? ORDER BY id", (max_level,)).fetchall()

    def board(self, board_id: int):
        return self.conn.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()

    def add_board(self, name: str, descr: str = "", min_level: int = 0) -> None:
        self.conn.execute(
            "INSERT INTO boards(name, descr, min_level) VALUES (?,?,?)",
            (name, descr, min_level))
        self.conn.commit()

    def board_by_name(self, name: str):
        return self.conn.execute(
            "SELECT * FROM boards WHERE name=? COLLATE NOCASE", (name,)).fetchone()

    def board_messages(self, board_id: int, limit: int, offset: int):
        return self.conn.execute(
            "SELECT m.*, u.handle FROM messages m JOIN users u ON u.id=m.author_id "
            "WHERE board_id=? ORDER BY m.created DESC, m.id DESC LIMIT ? OFFSET ?",
            (board_id, limit, offset)).fetchall()

    def board_msg_count(self, board_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE board_id=?", (board_id,)).fetchone()["c"]

    def message(self, msg_id: int):
        return self.conn.execute(
            "SELECT m.*, u.handle FROM messages m JOIN users u ON u.id=m.author_id "
            "WHERE m.id=?", (msg_id,)).fetchone()

    def msg_neighbors(self, msg):
        prev = self.conn.execute(
            "SELECT id FROM messages WHERE board_id=? "
            "AND (created<? OR (created=? AND id<?)) "
            "ORDER BY created DESC, id DESC LIMIT 1",
            (msg["board_id"], msg["created"], msg["created"], msg["id"])).fetchone()
        nxt = self.conn.execute(
            "SELECT id FROM messages WHERE board_id=? "
            "AND (created>? OR (created=? AND id>?)) "
            "ORDER BY created, id LIMIT 1",
            (msg["board_id"], msg["created"], msg["created"], msg["id"])).fetchone()
        return (prev["id"] if prev else None, nxt["id"] if nxt else None)

    def post(self, board_id: int, author_id: int, body: str, reply_to=None) -> int:
        cur = self.conn.execute(
            "INSERT INTO messages(board_id, author_id, reply_to, body, created) "
            "VALUES (?,?,?,?,?)", (board_id, author_id, reply_to, body, now()))
        self.conn.commit()
        return cur.lastrowid

    # -- newscan --------------------------------------------------------------
    def _ptr(self, uid: int, board_id: int) -> int:
        r = self.conn.execute(
            "SELECT last_seen FROM scan_ptr WHERE user_id=? AND board_id=?",
            (uid, board_id)).fetchone()
        return r["last_seen"] if r else 0

    def set_ptr(self, uid: int, board_id: int, msg_id: int) -> None:
        self.conn.execute(
            "INSERT INTO scan_ptr(user_id, board_id, last_seen) VALUES (?,?,?) "
            "ON CONFLICT(user_id, board_id) DO UPDATE SET "
            "last_seen=MAX(last_seen, excluded.last_seen)",
            (uid, board_id, msg_id))
        self.conn.commit()

    def next_unread(self, uid: int, board_id: int):
        return self.conn.execute(
            "SELECT m.*, u.handle FROM messages m JOIN users u ON u.id=m.author_id "
            "WHERE m.board_id=? AND m.id>? ORDER BY m.id LIMIT 1",
            (board_id, self._ptr(uid, board_id))).fetchone()

    def unread_count(self, uid: int, board_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE board_id=? AND id>?",
            (board_id, self._ptr(uid, board_id))).fetchone()["c"]

    def total_unread(self, uid: int, level: int) -> int:
        return sum(self.unread_count(uid, b["id"]) for b in self.boards(level))

    def mark_all_read(self, uid: int, level: int) -> None:
        for b in self.boards(level):
            top = self.conn.execute(
                "SELECT MAX(id) m FROM messages WHERE board_id=?",
                (b["id"],)).fetchone()["m"]
            if top:
                self.set_ptr(uid, b["id"], top)

    # -- mail ---------------------------------------------------------------
    def inbox(self, user_id: int, limit: int, offset: int):
        return self.conn.execute(
            "SELECT m.*, u.handle FROM mail m JOIN users u ON u.id=m.from_id "
            "WHERE to_id=? ORDER BY m.id DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset)).fetchall()

    def inbox_count(self, user_id: int, unread_only=False) -> int:
        q = "SELECT COUNT(*) c FROM mail WHERE to_id=?"
        if unread_only:
            q += " AND is_read=0"
        return self.conn.execute(q, (user_id,)).fetchone()["c"]

    def mail_msg(self, mail_id: int):
        return self.conn.execute(
            "SELECT m.*, u.handle FROM mail m JOIN users u ON u.id=m.from_id "
            "WHERE m.id=?", (mail_id,)).fetchone()

    def send_mail(self, from_id: int, to_id: int, body: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO mail(from_id, to_id, body, created) VALUES (?,?,?,?)",
            (from_id, to_id, body, now()))
        self.conn.commit()
        return cur.lastrowid

    def mark_read(self, mail_id: int) -> None:
        self.conn.execute("UPDATE mail SET is_read=1 WHERE id=?", (mail_id,))
        self.conn.commit()

    # -- files ----------------------------------------------------------------
    def areas(self, max_level: int):
        return self.conn.execute(
            "SELECT a.*, (SELECT COUNT(*) FROM files f WHERE f.area_id=a.id) n "
            "FROM file_areas a WHERE min_level<=? ORDER BY id", (max_level,)).fetchall()

    def area(self, area_id: int):
        return self.conn.execute(
            "SELECT * FROM file_areas WHERE id=?", (area_id,)).fetchone()

    def add_area(self, name: str, descr: str = "", min_level: int = 0) -> None:
        self.conn.execute(
            "INSERT INTO file_areas(name, descr, min_level) VALUES (?,?,?)",
            (name, descr, min_level))
        self.conn.commit()

    def area_files(self, area_id: int, limit: int, offset: int):
        return self.conn.execute(
            "SELECT f.*, u.handle FROM files f JOIN users u ON u.id=f.uploader_id "
            "WHERE area_id=? ORDER BY f.created DESC, f.id DESC LIMIT ? OFFSET ?",
            (area_id, limit, offset)).fetchall()

    def area_file_count(self, area_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) c FROM files WHERE area_id=?", (area_id,)).fetchone()["c"]

    def file(self, file_id: int):
        return self.conn.execute(
            "SELECT f.*, u.handle FROM files f JOIN users u ON u.id=f.uploader_id "
            "WHERE f.id=?", (file_id,)).fetchone()

    def add_file(self, area_id, uploader_id, tg_file_id, name, size) -> int:
        cur = self.conn.execute(
            "INSERT INTO files(area_id, uploader_id, tg_file_id, name, size, created) "
            "VALUES (?,?,?,?,?,?)", (area_id, uploader_id, tg_file_id, name, size, now()))
        self.conn.commit()
        return cur.lastrowid

    def set_file_descr(self, file_id: int, descr: str) -> None:
        self.conn.execute("UPDATE files SET descr=? WHERE id=?", (descr, file_id))
        self.conn.commit()

    def delete_file(self, file_id: int) -> None:
        self.conn.execute("DELETE FROM files WHERE id=?", (file_id,))
        self.conn.commit()

    def move_file(self, file_id: int, area_id: int) -> None:
        self.conn.execute(
            "UPDATE files SET area_id=? WHERE id=?", (area_id, file_id))
        self.conn.commit()

    def bump_downloads(self, file_id: int) -> None:
        self.conn.execute(
            "UPDATE files SET downloads=downloads+1 WHERE id=?", (file_id,))
        self.conn.commit()

    # -- oneliners ---------------------------------------------------------
    def oneliners(self, limit=10):
        return self.conn.execute(
            "SELECT o.*, u.handle FROM oneliners o JOIN users u ON u.id=o.author_id "
            "ORDER BY o.id DESC LIMIT ?", (limit,)).fetchall()

    def add_oneliner(self, author_id: int, text: str) -> None:
        self.conn.execute(
            "INSERT INTO oneliners(author_id, text, created) VALUES (?,?,?)",
            (author_id, text, now()))
        self.conn.commit()

    # -- news feed dedup -----------------------------------------------------
    def feed_seen(self, key: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM feed_seen WHERE key=?", (key,)).fetchone() is not None

    def feed_mark(self, key: str, source: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO feed_seen(key, source, seen) VALUES (?,?,?)",
            (key, source, now()))
        self.conn.commit()

    # -- stats -------------------------------------------------------------
    def stats(self) -> dict:
        g = lambda q: self.conn.execute(q).fetchone()["c"]
        return {
            "users": g("SELECT COUNT(*) c FROM users"),
            "msgs": g("SELECT COUNT(*) c FROM messages"),
            "files": g("SELECT COUNT(*) c FROM files"),
            "calls": g("SELECT COALESCE(SUM(calls),0) c FROM users"),
        }
