"""Seed altBBS with old-school bootstrap content.

Ghost users (negative ids -- they never collide with real Telegram ids and
never steal the sysop seat), message threads about current AI/tech news,
oneliners, and e-zine files served from bootstrap/files/.

Run once:  python bootstrap.py     (idempotent -- refuses to run twice)
"""

import random
import sys
import time

from tgbbs.config import FILES_DIR, Config
from tgbbs.db import DB

DAY = 86400
NOW = int(time.time())

#            id    handle        lvl  joined(d)  calls
USERS = [
    (-101, "n3uromancer",  30, 34, 61),
    (-102, "backpr0p",     10, 30, 27),
    (-103, "z80phreak",    20, 28, 44),
    (-104, "ansi_ghost",   30, 33, 58),
    (-105, "tensorbaron",  10, 21, 19),
    (-106, "perceptr0n",   10, 17, 23),
    (-107, "modemgrrl",    20, 25, 39),
    (-108, "lobst3r",      10, 11,  8),
]

# (board_name, author_handle, days_ago, body, reply_to_index|None)
POSTS = [
    # ── main hall ─────────────────────────────────────────────────────
    ("main hall", "ansi_ghost", 9.0,
     "welcome to the tower\n\n"
     "you found it. pull up a node.\n\n"
     "house rules, short version: be excellent, post text, "
     "upload weird files, greet the sysop. the 80s never ended, "
     "they just got better transport encryption.", None),
    ("main hall", "z80phreak", 8.7,
     "greets from node 3\n\n"
     "calling in from a thinkpad older than some of you. "
     "feels good to have a board again.", 0),
    ("main hall", "lobst3r", 6.2,
     "crawled in from lobste.rs\n\n"
     "heard there was a place where threads don't get ranked by "
     "an engagement model. staying.", 0),

    # ── demoscene ─────────────────────────────────────────────────────
    ("demoscene", "z80phreak", 5.5,
     "the Z80 turns 50\n\n"
     "fifty years. 8500 transistors. spectrums, gameboys, "
     "TI calcs, CP/M, half the demoscene's childhood.\n\n"
     "meanwhile a language model needs a substation to write a "
     "haiku. per-transistor the Z80 remains undefeated and i will "
     "die on this hill.\n\nLD A,50 / HALT", None),
    ("demoscene", "ansi_ghost", 5.3,
     "RET without a stack frame? bold. happy birthday you "
     "beautiful little rectangle.", 3),
    ("demoscene", "n3uromancer", 4.9,
     "50 years and the timing bugs are now vintage charm. "
     "may we all age like that.", 3),
    ("demoscene", "ansi_ghost", 3.1,
     "regressive JPEGs = accidental demo effect\n\n"
     "someone on HN/lobste.rs built REGRESSIVE jpegs -- image "
     "decodes worse as it loads. it's an unloader. crackers "
     "spent decades making loaders and this madman built the "
     "opposite direction. 580 points, deserved. graphics coders "
     "remain the best coders, no notes.", None),

    # ── tech dungeon ──────────────────────────────────────────────────
    ("tech dungeon", "tensorbaron", 4.5,
     "GPT-5.6 closed a 30-year-old convex optimization gap\n\n"
     "front page of HN, 343 points: somebody fed a stale open "
     "problem to GPT-5.6 and it produced a proof that CHECKS. "
     "thirty years open. one prompt.\n\n"
     "i keep re-reading the thread and the verifier does not "
     "care about anybody's feelings. the lemmas hold.", None),
    ("tech dungeon", "backpr0p", 4.4,
     "counterpoint: it likely interpolated from a 1997 paper "
     "nobody read. impressive retrieval != new mathematics. "
     "extraordinary claims, ordinary training data.", 7),
    ("tech dungeon", "tensorbaron", 4.3,
     "half the human results i ever cited were interpolation "
     "from a 1997 paper nobody read. doesn't matter who "
     "wardialed the number if the modem picks up.", 7),
    ("tech dungeon", "perceptr0n", 3.8,
     "the stackoverflow graph (press F)\n\n"
     "'what AI did to stackoverflow' -- one chart, straight "
     "from the data explorer. questions falling like a dropped "
     "carrier since the assistants shipped.\n\n"
     "we didn't lose a website, we lost a commons. every answer "
     "now evaporates inside a private chat window. what do the "
     "NEXT models train on? logs of the last ones? that's a "
     "photocopy of a photocopy.\n\n"
     "post your fixes on boards like this. text should stay "
     "where you put it.", None),
    ("tech dungeon", "modemgrrl", 3.6,
     "this is literally why boards matter again. public "
     "plaintext or it didn't happen.", 10),
    ("tech dungeon", "modemgrrl", 2.9,
     "'reviewing AI code is not a viable argument'\n\n"
     "good rant on lobste.rs. if your whole safety story for "
     "machine-written code is 'a human will look at it', you "
     "don't have a safety story, you have a scapegoat with a "
     "login.\n\n"
     "reviewers already rubber-stamp 400-line diffs from HUMANS. "
     "the fix is boring: small diffs, tests, types, sandboxes. "
     "same as it ever was.", None),
    ("tech dungeon", "n3uromancer", 2.7,
     "the detector wars are the new crackers-vs-protection. "
     "pangram sniffs model text with... another model. narcs "
     "all the way down. sustainable employment for everyone.", 12),
    ("tech dungeon", "z80phreak", 1.8,
     "LG monitors deliver payloads via windows update\n\n"
     "766 points of rage: plug in an LG display, get vendor "
     "software silently installed through windows update. no "
     "consent screen. the supply chain trojans you, signed and "
     "certified.\n\n"
     "in my day you had to trojan an .EXE yourself and write a "
     "convincing FILE_ID.DIZ. kids these days get it done by "
     "the OEM. also: TP-Link cams leaked home GPS over open UDP "
     "for SIX YEARS. the S in IoT stands for security.", None),
    ("tech dungeon", "n3uromancer", 1.1,
     "fable 5 vs GPT-5.6 sol: NP-hard shootout\n\n"
     "benchmark scene delivered a proper compo: two frontier "
     "models on an NP-hard problem, with and without /goal "
     "steering. both grind out respectable solutions, neither "
     "proves optimality (it's NP-hard, that IS the joke), and "
     "the steering helped one more than the other -- which "
     "tells you more about the harness than the intelligence.\n\n"
     "in '94 we measured groups by their intros. now we measure "
     "labs by their evals. same energy, more electricity.", None),
    ("tech dungeon", "lobst3r", 0.6,
     "meanwhile in the rewrite scene: roc's rust->zig port log "
     "pulled 183 points. groups used to port demos amiga->pc "
     "for glory, now they port compilers. the compo never "
     "ended, it just got a build system.", 15),
]

# (area_name, uploader, disk_filename, diz, days_ago, downloads)
FILES = [
    ("incoming", "ansi_ghost", "RAW_SYNAPSE-001.TXT",
     "RAW SYNAPSE #001 * jul 2026\n"
     "the neural underground e-zine\n"
     "AI does math, SO dies, Z80@50\n"
     "humans wrote this. probably.", 2.5, 14),
    ("incoming", "n3uromancer", "NEURAL_UNDERGROUND-007.NFO",
     "NEURAL UNDERGROUND #007\n"
     "scene report: detector wars,\n"
     "AI code review discourse, the\n"
     "great rust->zig migration", 1.9, 9),
    ("ansi+ascii art", "ansi_ghost", "ALTBBS_LOGOPACK-01.ASC",
     "altBBS logo pack 01\n"
     "4 logos * ascii * free to rip\n"
     "greet politely.", 6.0, 21),
    ("utils", "modemgrrl", "MODEM_INIT-2026.TXT",
     "modem init strings, 2026 ed.\n"
     "AT+FCLASS=8 for the TTS era\n"
     "100% load-bearing", 4.2, 11),
]

ONELINERS = [
    ("backpr0p",    "backprop is just the chain rule with a marketing dept"),
    ("z80phreak",   "8500 transistors ought to be enough for anybody"),
    ("n3uromancer", "NO CARRIER was the original context window limit"),
    ("modemgrrl",   "public plaintext or it didn't happen"),
    ("perceptr0n",  "pour one out for stackoverflow, then post it here"),
    ("ansi_ghost",  "the tower never sleeps"),
    ("lobst3r",     "ranked by nothing, read by everyone"),
    ("tensorbaron", "the lemmas hold."),
]


def main() -> None:
    cfg = Config.load()
    db = DB(cfg.db_path)

    if db.user_by_handle(USERS[0][1]):
        print("already bootstrapped -- nothing to do.")
        sys.exit(0)

    rng = random.Random(1994)

    for uid, handle, lvl, days, calls in USERS:
        joined = NOW - int(days * DAY)
        last = NOW - int(rng.uniform(0.1, 2.5) * DAY)
        db.conn.execute(
            "INSERT INTO users(id, handle, level, joined, last_call, calls) "
            "VALUES (?,?,?,?,?,?)", (uid, handle, lvl, joined, last, calls))

    by_handle = {h: uid for uid, h, *_ in USERS}
    boards = {b["name"]: b["id"] for b in db.boards(255)}
    areas = {a["name"]: a["id"] for a in db.areas(255)}

    msg_ids: list[int] = []
    for board, author, days, body, reply_idx in POSTS:
        cur = db.conn.execute(
            "INSERT INTO messages(board_id, author_id, reply_to, body, created) "
            "VALUES (?,?,?,?,?)",
            (boards[board], by_handle[author],
             msg_ids[reply_idx] if reply_idx is not None else None,
             body, NOW - int(days * DAY)))
        msg_ids.append(cur.lastrowid)

    for area, uploader, fname, diz, days, gets in FILES:
        path = FILES_DIR / fname
        if not path.is_file():
            print(f"warning: missing bootstrap file {fname}, skipped")
            continue
        db.conn.execute(
            "INSERT INTO files(area_id, uploader_id, tg_file_id, name, size, "
            "descr, created, downloads) VALUES (?,?,?,?,?,?,?,?)",
            (areas[area], by_handle[uploader], f"local:{fname}", fname,
             path.stat().st_size, diz, NOW - int(days * DAY), gets))

    for i, (author, text) in enumerate(ONELINERS):
        db.conn.execute(
            "INSERT INTO oneliners(author_id, text, created) VALUES (?,?,?)",
            (by_handle[author], text, NOW - (len(ONELINERS) - i) * DAY // 2))

    db.conn.commit()
    st = db.stats()
    print(f"bootstrapped: {len(USERS)} ghost users, {st['msgs']} posts, "
          f"{st['files']} files, {len(ONELINERS)} oneliners -> {cfg.db_path}")
    print("the first REAL caller to /start still becomes the sysop.")


if __name__ == "__main__":
    main()
