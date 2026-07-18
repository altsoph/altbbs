"""QWK offline mail packets -- the real 1987 binary format.

A packet is a zip holding CONTROL.DAT (system + conference list),
MESSAGES.DAT (128-byte records: header block + 0xE3-separated body
blocks, cp437) and a HELLO screen. Readable by period QWK readers
(MultiMail, and with luck the originals). Driven by the same per-user
newscan pointers -- downloading a packet reads your mail, which is
the entire point of offline mail.
"""

import io
import struct
import time
import zipfile

from . import art

E3 = b"\xe3"          # QWK line separator
MAX_MSGS = 500        # packet cap


def _field(value, width: int) -> bytes:
    b = str(value).encode("cp437", "replace")[:width]
    return b.ljust(width)


def _message_record(num, created, to, frm, subj, body, conf, logical) -> bytes:
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    raw = E3.join(line.encode("cp437", "replace")
                  for line in text.split("\n")) + E3
    blocks = -(-len(raw) // 128)
    raw = raw.ljust(blocks * 128)
    t = time.localtime(created)
    header = b"".join([
        b" ",                                   # status: public
        _field(num, 7),                         # message number
        _field(time.strftime("%m-%d-%y", t), 8),
        _field(time.strftime("%H:%M", t), 5),
        _field(to, 25),
        _field(frm, 25),
        _field(subj, 25),
        b" " * 12,                              # password
        _field("", 8),                          # reference number
        _field(blocks + 1, 6),                  # blocks incl. this header
        b"\xe1",                                # active
        struct.pack("<H", conf),                # conference (board id)
        struct.pack("<H", logical),             # logical number in packet
        b" ",                                   # net tag
    ])
    assert len(header) == 128
    return header + raw


def build_qwk(db, cfg, user) -> tuple[bytes, int, dict[int, int]]:
    """Return (zip bytes, message count, {board_id: max_msg_id to advance})."""
    bbsid = cfg.echo_id
    boards = db.boards(user["level"])
    records = []
    confs = []
    advance: dict[int, int] = {}
    total = 0
    for b in boards:
        confs.append((b["id"], b["name"][:13]))
        if total >= MAX_MSGS:
            continue
        msgs = db.unread_messages(user["id"], b["id"], MAX_MSGS - total)
        for m in msgs:
            total += 1
            subj = (m["body"].splitlines() or [""])[0][:25]
            records.append(_message_record(
                m["id"], m["created"], "ALL", m["handle"], subj,
                m["body"], b["id"], total))
            advance[b["id"]] = m["id"]

    messages_dat = f"Produced by {cfg.bbs_name} via altBBS".encode(
        "cp437", "replace").ljust(128) + b"".join(records)

    control = [
        cfg.bbs_name,
        "the telegram network",
        "000-000-0000",
        "sysop, Sysop",
        f"00000,{bbsid}",
        time.strftime("%m-%d-%Y,%H:%M:%S"),
        user["handle"].upper(),
        "",
        "0",
        str(total),
        str(len(confs) - 1),
    ]
    for cid, name in confs:
        control += [str(cid), name]
    control += ["HELLO", "NEWS", "GOODBYE"]

    hello = "\n".join(art.LOGO + [art.gradient_title("offline mail"),
                                  "", f"  {cfg.tagline}", ""])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("CONTROL.DAT", "\r\n".join(control) + "\r\n")
        z.writestr("MESSAGES.DAT", messages_dat)
        z.writestr("HELLO", hello.encode("cp437", "replace"))
    return buf.getvalue(), total, advance
