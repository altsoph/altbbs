"""Offline smoke test: exercises DB + renders every screen without Telegram.

Run: python selftest.py
"""

import re
import tempfile
from pathlib import Path

from tgbbs.config import Config
from tgbbs.db import DB
from tgbbs.handlers import BBS


def strip_pre(html_text: str) -> str:
    return re.sub(r"</?pre>", "", html_text)


def main() -> None:
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    cfg = Config(token="x", db_path=tmp)
    db = DB(tmp)
    bbs = BBS(cfg, db)

    # simulate two callers
    sysop = db.create_user(1, "st0rmlord")
    assert sysop["level"] == 255, "first caller must be sysop"
    user = db.create_user(2, "phreak")
    assert user["level"] == 10

    mid = db.post(1, 1, "welcome to the tower\nfirst post. behave.")
    db.post(1, 2, "greets from node 2!", reply_to=mid)
    db.send_mail(2, 1, "yo sysop, nice board")
    fid = db.add_file(1, 2, "tg-file-id-xyz", "cracktro.zip", 123456)
    db.set_file_descr(fid, "final cut / 4kb intro")
    db.add_oneliner(2, "the tower never sleeps")

    # chat pit with some traffic
    bbs.sessions[1] = {"await": "chat", "ctx": {}, "term": 1, "chat": True,
                       "cid": 1, "ts": 1e12}
    bbs.chat_log.append(("*", "st0rmlord joined"))
    bbs.chat_log.append(("st0rmlord", "anyone alive on the nodes?"))
    bbs.chat_log.append(("phreak", "always. what did you break today"))

    screens = {
        "welcome": bbs.scr_welcome(),
        "chat": bbs.scr_chat(sysop),
        "main": bbs.scr_main(sysop),
        "boards": bbs.scr_boards(user),
        "board": bbs.scr_board(user, 1, 0),
        "msg": bbs.scr_msg(user, mid),
        "mail": bbs.scr_mail(sysop, 0),
        "mail_read": bbs.scr_mail_read(sysop, 1),
        "areas": bbs.scr_areas(user),
        "area": bbs.scr_area(user, 1, 0),
        "file": bbs.scr_file(user, fid),
        "ones": bbs.scr_ones(user),
        "who": bbs.scr_who(user),
        "users": bbs.scr_users(user, 0),
        "sysop": bbs.scr_sysop(sysop),
        "logoff": bbs.scr_logoff(user),
    }
    for name, (text, _kbd) in screens.items():
        plain = strip_pre(text)
        assert len(text) < 4096, f"{name}: screen exceeds telegram limit"
        assert plain.strip(), f"{name}: empty screen"
        print(f"===== {name} " + "=" * (60 - len(name)))
        print(plain)
        print()

    # access control: low-level user must not see staff board (min_level 100)
    visible = [b["id"] for b in db.boards(user["level"])]
    staff = [b for b in db.boards(255) if b["min_level"] >= 100]
    assert staff and all(b["id"] not in visible for b in staff), "ACL leak!"

    # sysop board is invisible in scr_boards for a normal user
    text, _ = bbs.scr_boards(user)
    assert "sysop office" not in text

    # ascii viewer: generated gradient image -> ascii lines that fit a screen
    from io import BytesIO

    from PIL import Image

    from tgbbs.asciiview import image_to_ascii
    img = Image.new("RGB", (200, 320))
    img.putdata([(3 * x % 256, y % 256, (x + y) % 256)
                 for y in range(320) for x in range(200)])
    buf = BytesIO()
    img.save(buf, "PNG")
    lines = image_to_ascii(buf.getvalue())
    assert 0 < len(lines) <= 42 and max(len(l) for l in lines) <= 34
    print("===== ascii viewer " + "=" * 47)
    text, _ = bbs.scr_ascii(user, lines, "gradient.png", "menu")
    print(strip_pre(text))

    # text preview: page through the bundled zine
    from tgbbs.asciiview import text_to_lines
    from tgbbs.config import FILES_DIR
    zdata = (FILES_DIR / "RAW_SYNAPSE-001.TXT").read_bytes()
    zid = db.add_file(2, 2, "local:RAW_SYNAPSE-001.TXT",
                      "RAW_SYNAPSE-001.TXT", len(zdata))
    zlines = text_to_lines(zdata)
    assert zlines and max(len(l) for l in zlines) <= 33
    text, _ = bbs.scr_text(user, db.file(zid), zlines, 0)
    assert len(text) < 4096
    print("===== text preview (zine, page 1) " + "=" * 31)
    print(strip_pre(text))

    print("ALL SELFTESTS PASSED")


if __name__ == "__main__":
    main()
