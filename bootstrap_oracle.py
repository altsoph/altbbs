"""Seed THE ORACLE with questions and bets.

Three flavours:
- board-local bets (will anyone slay the dragon?) by the ghost crew
- decidable near-term questions from this week's tech news
- live markets imported from manifold.markets (open binary markets
  closing within ~45 days), with the market's current probability
  recorded as a forecast by the ghost 'manifold' -- hidden, as
  always, until you commit your own number

Ghost-authored questions can only be resolved by the sysop.
Run once:  python bootstrap_oracle.py   (idempotent)
"""

import json
import sys
import time
import urllib.request

from tgbbs.config import Config
from tgbbs.db import DB

DAY = 86400
NOW = int(time.time())
DOOR = "oracle"

#          author        days  question                          [(forecaster, p)]
LOCAL = [
    ("ansi_ghost", 30,
     "will altBBS reach 25 registered users by aug 18?",
     [("z80phreak", 35), ("lobst3r", 55)]),
    ("z80phreak", 7,
     "will anyone slay THE RED DRAGON in the tower by jul 26?",
     [("n3uromancer", 20), ("backpr0p", 10)]),
    ("n3uromancer", 30,
     "will a second BBS join our echo channel by aug 18?",
     [("ansi_ghost", 40), ("modemgrrl", 60)]),
    ("modemgrrl", 14,
     "will the news wires cross 500 imported stories by aug 2?",
     [("perceptr0n", 70)]),
    ("tensorbaron", 30,
     "will the GPT-5.6 convex optimization proof still stand "
     "unrefuted on aug 18?",
     [("backpr0p", 45), ("n3uromancer", 75), ("perceptr0n", 68)]),
    ("perceptr0n", 14,
     "will LG publicly apologize or ship a fix for the monitor "
     "windows-update scandal by aug 2?",
     [("z80phreak", 25), ("modemgrrl", 40)]),
    ("lobst3r", 30,
     "will roc's rust->zig rewrite hit a tagged release by aug 18?",
     [("tensorbaron", 30)]),
    ("backpr0p", 30,
     "will another AI-text-detector drama hit the HN front page "
     "by aug 18?",
     [("n3uromancer", 80), ("ansi_ghost", 65)]),
]

MANIFOLD_TERMS = ("AI", "technology")
MANIFOLD_MAX = 5
MANIFOLD_WINDOW = 45 * DAY


def fetch_manifold():
    picked, seen = [], set()
    for term in MANIFOLD_TERMS:
        url = ("https://api.manifold.markets/v0/search-markets"
               f"?term={term}&filter=open&contractType=BINARY"
               "&sort=score&limit=40")
        req = urllib.request.Request(url, headers={
            "User-Agent": "altBBS-oracle-seed/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                markets = json.load(r)
        except Exception as e:
            print(f"manifold fetch '{term}' failed: {e}")
            continue
        for m in markets:
            if len(picked) >= MANIFOLD_MAX:
                break
            close = int(m.get("closeTime", 0)) // 1000
            if not (NOW < close <= NOW + MANIFOLD_WINDOW):
                continue
            if m.get("uniqueBettorCount", 0) < 20 or m["id"] in seen:
                continue
            seen.add(m["id"])
            picked.append({
                "text": (m.get("question", "").strip()[:180] +
                         " (via manifold)"),
                "close": close,
                "p": max(1, min(99, round(m.get("probability", .5) * 100))),
            })
    return picked


def main():
    cfg = Config.load()
    db = DB(cfg.db_path)

    g = json.loads(db.door_state(0, DOOR))
    if g.get("seeded"):
        print("oracle already seeded -- nothing to do.")
        sys.exit(0)
    g.setdefault("next", 1)
    g.setdefault("q", {})

    def add_question(handle, text, close_ts, forecasts):
        author = db.user_by_handle(handle) or db.ensure_ghost(handle)
        qid = g["next"]
        g["next"] += 1
        g["q"][str(qid)] = {
            "id": qid, "text": text, "by": author["handle"],
            "by_uid": author["id"], "close": close_ts,
            "created": NOW, "n": 0, "res": None,
        }
        for fh, p in forecasts:
            f = db.user_by_handle(fh) or db.ensure_ghost(fh)
            st = json.loads(db.door_state(f["id"], DOOR))
            st.setdefault("fc", {})[str(qid)] = {"p": p, "ts": NOW}
            db.save_door_state(f["id"], DOOR, json.dumps(st))
            g["q"][str(qid)]["n"] += 1
        return qid

    for handle, days, text, forecasts in LOCAL:
        add_question(handle, text, NOW + days * DAY, forecasts)

    imported = fetch_manifold()
    for m in imported:
        add_question("manifold", m["text"], m["close"],
                     [("manifold", m["p"])])

    g["seeded"] = True
    db.save_door_state(0, DOOR, json.dumps(g))
    print(f"seeded: {len(LOCAL)} local questions + "
          f"{len(imported)} manifold markets -> {cfg.db_path}")
    print("resolution of ghost questions is the sysop's duty. no pressure.")


if __name__ == "__main__":
    main()
