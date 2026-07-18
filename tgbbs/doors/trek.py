"""SUPER STAR TREK -- the 1971 classic, multiuser, as a BBS door.

Wraps the vendored FSM engine (see _trek_engine.py for the lineage).
Every caller commands their own Enterprise; the mission survives
logoffs and bot restarts because the entire game state is JSON in the
door_state table. Winning pays credits. Dying pays a lesson.
"""

import textwrap

from ._trek_engine import TrekGame

WIN_PAY = 100

MAIN_KEYS = [
    [("[1] HELM", "cmd:1"), ("[2] SCAN", "cmd:2")],
    [("[3] PHASERS", "cmd:3"), ("[4] TORPS", "cmd:4")],
    [("[5] SHIELDS", "cmd:5"), ("[0] HELP", "cmd:0")],
    [("[R] RESIGN", "cmd:6")],
]
DIR_KEYS = [
    [("[7]↖", "cmd:7"), ("[8]↑", "cmd:8"), ("[9]↗", "cmd:9")],
    [("[4]←", "cmd:4"), ("[6]→", "cmd:6")],
    [("[1]↙", "cmd:1"), ("[2]↓", "cmd:2"), ("[3]↘", "cmd:3")],
]
WARP_KEYS = [[("[1] WARP 1", "cmd:1"), ("[2] WARP 2", "cmd:2")],
             [("[4] WARP 4", "cmd:4"), ("[8] WARP 8", "cmd:8")]]
PHASER_KEYS = [[("100", "cmd:100"), ("250", "cmd:250"), ("500", "cmd:500")]]
SHIELD_KEYS = [[("250", "cmd:250"), ("500", "cmd:500"),
                ("1000", "cmd:1000")]]

HOW_TO = [
    "  you command the Enterprise.",
    "  hunt every klingon (>!<) in",
    "  an 8x8 galaxy of 8x8 sectors.",
    "",
    "  -O- you   <O> starbase",
    "  >!< enemy  *  star",
    "",
    "  dock beside a starbase to",
    "  refuel. phasers fade with",
    "  distance; torpedoes fly",
    "  straight and need aiming:",
    "",
    "       7 8 9",
    "        \\|/",
    "       4-o-6",
    "        /|\\",
    "       1 2 3",
    "",
    "  raise shields EARLY. klingons",
    "  shoot back. good hunting.",
]


class TrekDoor:
    key = "trek"
    title = "super star trek"
    diz = "1971. klingons. no mercy"

    def handle(self, api, user, payload):
        uid = user["id"]
        st = api.state(uid)
        cmd, _, arg = payload.partition(":")
        if cmd == "new":
            st.pop("game", None)
            return self._run(api, uid, st, "")
        if cmd == "resume" and st.get("game"):
            body = self._wrap(st.get("last", ""))
            return ("super star trek", body,
                    self._buttons(st["game"].get("fsm_state", "main_cmd")))
        if cmd in ("cmd", "text") and st.get("game"):
            return self._run(api, uid, st, arg.strip())
        if cmd == "how":
            return "how to play", list(HOW_TO), [[("[B] BACK", "enter")]]
        if cmd == "top":
            return self._fame(api)
        return self._lobby(api, uid, st)

    # -- screens -----------------------------------------------------------
    def _lobby(self, api, uid, st, note: str = ""):
        w, l = st.get("wins", 0), st.get("losses", 0)
        body = [
            "  ▄▀▄ SUPER STAR TREK ▄▀▄",
            "",
            "  space... the final frontier.",
            "  the 1971 game, one Enterprise",
            "  per caller, saved between",
            "  calls.",
            "",
            f"  your record: {w} won / {l} lost",
            f"  victory pays {WIN_PAY} credits.",
        ]
        if note:
            body += ["", f"  {note}"]
        rows = []
        if st.get("game"):
            body += ["", "  a mission is IN PROGRESS."]
            rows.append([("[R] RESUME MISSION", "resume")])
        rows.append([("[N] NEW MISSION", "new")])
        rows.append([("[H] HOW TO PLAY", "how"),
                     ("[T] HALL OF FAME", "top")])
        return "super star trek", body, rows

    def _run(self, api, uid, st, inp: str):
        g = TrekGame()
        saved = st.get("game")
        if saved:
            g.__dict__.update(saved)
            g.step(inp)
        else:
            g.step("")  # fresh mission: init + first prompt
        if g.get_state() == "main_cmd":
            g.step(clear=False)  # the classic re-prompt, per the dispatcher
        out = g.result()

        if g.get_state() == "init":  # mission over, engine reset itself
            won = g.klingons == 0
            st["wins" if won else "losses"] = st.get(
                "wins" if won else "losses", 0) + 1
            st.pop("game", None)
            st.pop("last", None)
            api.save(uid, st)
            body = self._wrap(out) + [""]
            if won:
                bal = api.pay(uid, WIN_PAY)
                body.append(f"  ░▒▓ +{WIN_PAY}c · bal {bal} ▓▒░")
            else:
                body.append("  the federation mourns.")
            rows = [[("[N] NEW MISSION", "new")],
                    [("[T] HALL OF FAME", "top")]]
            return "super star trek", body, rows

        st["game"] = {k: v for k, v in g.__dict__.items() if k != "BUF"}
        st["last"] = out
        api.save(uid, st)
        return ("super star trek", self._wrap(out),
                self._buttons(g.get_state()))

    def _fame(self, api):
        heroes = sorted(api.states(),
                        key=lambda hs: (hs[1].get("wins", 0),
                                        -hs[1].get("losses", 0)),
                        reverse=True)[:10]
        body = ["  starfleet's finest:", ""]
        for h, s in heroes:
            if not (s.get("wins") or s.get("losses")):
                continue
            body.append(f"  {h[:12]:<13} {s.get('wins', 0):>3}w"
                        f" {s.get('losses', 0):>3}l")
        if len(body) == 2:
            body.append("  no missions flown yet.")
        return "hall of fame", body, [[("[B] BACK", "enter")]]

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _wrap(text: str) -> list[str]:
        lines = []
        for raw in text.splitlines():
            raw = raw.rstrip()
            if len(raw) <= 32:
                lines.append(" " + raw)
            else:
                lines += [" " + w for w in textwrap.wrap(raw, 31)]
        return lines

    @staticmethod
    def _buttons(state: str):
        if state in ("helm1", "torpedoes1"):
            return DIR_KEYS
        if state == "helm2":
            return WARP_KEYS
        if state == "phasers1":
            return PHASER_KEYS
        if state == "shields1":
            return SHIELD_KEYS
        return MAIN_KEYS


door = TrekDoor()
