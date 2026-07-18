"""THE ORACLE -- a prediction exchange, metaculus-style, 34 cols wide.

Callers open binary questions with a closing date; everyone forecasts
a probability (the crowd number stays hidden until you commit your
own -- no anchoring); the author or a co-sysop resolves YES/NO/VOID.
Scoring is Brier-based: points = round((0.25 - (p - outcome)^2) * 100),
so a coin-flip 50% scores zero, a confident right call earns up to
+25, and a confident wrong one burns up to -75. Positive points pay
out as credits; the rating keeps the full signed sum. Calibration is
a virtue. The tower remembers.

Shared questions live in the door_state row of user 0 (the "global"
slot); each caller's forecasts live in their own state.
"""

import time

HORIZONS = [("1 DAY", 1), ("3 DAYS", 3), ("1 WEEK", 7), ("1 MONTH", 30)]
QUICK_P = [5, 10, 25, 40, 50, 60, 75, 90, 95]
PAGE = 5
MAX_Q = 200  # question text cap


def _eta(ts: float) -> str:
    left = int(ts - time.time())
    if left <= 0:
        return "closed"
    if left >= 86400:
        return f"{left // 86400}d {left % 86400 // 3600}h"
    if left >= 3600:
        return f"{left // 3600}h {left % 3600 // 60}m"
    return f"{left // 60}m"


def _points(p: int, outcome: int) -> int:
    brier = (p / 100 - outcome) ** 2
    return round((0.25 - brier) * 100)


class OracleDoor:
    key = "oracle"
    title = "the oracle"
    diz = "predict. resolve. be calibrated"

    # -- shared question store (global slot: uid 0) -------------------------
    def _g(self, api) -> dict:
        g = api.state(0)
        g.setdefault("next", 1)
        g.setdefault("q", {})
        return g

    def handle(self, api, user, payload):
        uid = user["id"]
        st = api.state(uid)
        cmd, _, arg = payload.partition(":")
        if cmd == "list":
            return self._list(api, uid, int(arg or 0))
        if cmd == "q":
            return self._question(api, user, arg)
        if cmd == "fc":
            qid, _, p = arg.partition(":")
            return self._forecast(api, user, qid, p)
        if cmd == "new":
            st["compose"] = ""
            api.save(uid, st)
            return ("new question", [
                "  ask the network something",
                "  with a YES/NO answer and a",
                "  deadline. keep it decidable.",
                "",
                f"  (max {MAX_Q} chars)",
                "",
                "  type your question now:",
                "  █",
            ], [[("[B] NEVERMIND", "enter")]])
        if cmd == "horizon" and st.get("compose"):
            return self._create(api, user, int(arg))
        if cmd == "text":
            return self._typed(api, user, arg.strip())
        if cmd == "resolve":
            qid, _, how = arg.partition(":")
            return self._resolve(api, user, qid, how)
        if cmd == "my":
            return self._mine(api, uid)
        if cmd == "top":
            return self._top(api)
        return self._lobby(api, uid)

    # -- screens -------------------------------------------------------------
    def _lobby(self, api, uid, note: str = ""):
        g = self._g(api)
        st = api.state(uid)
        open_q = [q for q in g["q"].values() if q.get("res") is None]
        body = [
            "  ▄▀▄ THE ORACLE ▄▀▄",
            "",
            "  the prediction exchange.",
            "  crowd numbers stay hidden",
            "  until you commit your own.",
            "",
            f"  open questions: {len(open_q)}",
            f"  your rating: {st.get('rating', 0):+d}"
            f" over {st.get('n_res', 0)} calls",
            "",
            "  scoring: 50% = 0 pts, right",
            "  and confident = +25, wrong",
            "  and confident = -75. points",
            "  above zero pay credits.",
        ]
        if note:
            body += ["", f"  {note}"]
        rows = [[("[L] OPEN QUESTIONS", "list:0"),
                 ("[N] ASK ONE", "new")],
                [("[M] MY FORECASTS", "my"),
                 ("[T] RATINGS", "top")]]
        return "the oracle", body, rows

    def _list(self, api, uid, page: int):
        g = self._g(api)
        open_q = sorted(
            (q for q in g["q"].values() if q.get("res") is None),
            key=lambda q: q["close"])
        body = ["  open questions:", ""]
        rows = []
        chunk = open_q[page * PAGE:(page + 1) * PAGE]
        if not chunk:
            body.append("  none. ask one!")
        for q in chunk:
            first = q["text"][:28]
            body.append(f"  #{q['id']:<3} {_eta(q['close']):<8} {q['n']:>2} fc")
            body.append(f"    {first}")
            rows.append([(f"#{q['id']} {first[:22]}", f"q:{q['id']}")])
        nav = []
        if page > 0:
            nav.append(("« PREV", f"list:{page - 1}"))
        if (page + 1) * PAGE < len(open_q):
            nav.append(("NEXT »", f"list:{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([("[B] BACK", "enter")])
        return "the oracle", body, rows

    def _question(self, api, user, qid: str, note: str = ""):
        uid = user["id"]
        g = self._g(api)
        q = g["q"].get(str(qid))
        if not q:
            return self._lobby(api, uid, note="that question is gone.")
        st = api.state(uid)
        st["viewing"] = q["id"]
        api.save(uid, st)
        mine = st.get("fc", {}).get(str(q["id"]))
        closed = time.time() > q["close"] or q.get("res") is not None
        body = [f"  #{q['id']} · by {q['by'][:14]}", " " + "·" * 30]
        body += [f"  {l}" for l in _wrap(q["text"])]
        body += [" " + "·" * 30,
                 f"  closes: {_eta(q['close'])} · {q['n']} forecasts"]
        if q.get("res") is not None:
            body.append(f"  RESOLVED: {'YES' if q['res'] else 'NO'}")
        if mine:
            body.append(f"  your call: {mine['p']}%")
            ps = self._crowd(api, q["id"])
            if ps:
                body.append(f"  the crowd: {sum(ps) // len(ps)}%"
                            f" ({len(ps)} oracles)")
        else:
            body.append("  crowd hidden: forecast first.")
        if note:
            body += ["", f"  {note}"]
        rows = []
        if not closed:
            body += ["", "  your probability of YES?",
                     "  tap below or type 0-100"]
            rows.append([(f"{p}%", f"fc:{q['id']}:{p}") for p in QUICK_P[:5]])
            rows.append([(f"{p}%", f"fc:{q['id']}:{p}") for p in QUICK_P[5:]])
        can_resolve = (uid == q.get("by_uid") or user["level"] >= 100)
        if can_resolve and q.get("res") is None:
            rows.append([("[Y] RES: YES", f"resolve:{q['id']}:1"),
                         ("[N] RES: NO", f"resolve:{q['id']}:0"),
                         ("[V] VOID", f"resolve:{q['id']}:void")])
        rows.append([("[B] BACK", "list:0")])
        return f"oracle #{q['id']}", body, rows

    def _crowd(self, api, qid) -> list[int]:
        return [s["fc"][str(qid)]["p"]
                for _uid, _h, s in api.states_full()
                if str(qid) in s.get("fc", {})]

    def _forecast(self, api, user, qid: str, p_raw: str):
        uid = user["id"]
        g = self._g(api)
        q = g["q"].get(str(qid))
        if not q or q.get("res") is not None or time.time() > q["close"]:
            return self._lobby(api, uid, note="too late for that one.")
        try:
            p = max(1, min(99, int(p_raw)))
        except ValueError:
            return self._question(api, user, qid, note="0-100, oracle.")
        st = api.state(uid)
        fresh = str(q["id"]) not in st.get("fc", {})
        st.setdefault("fc", {})[str(q["id"])] = {"p": p, "ts": int(time.time())}
        api.save(uid, st)
        if fresh:
            q["n"] += 1
            api.save(0, g)
        return self._question(api, user, qid,
                              note=f"logged: {p}%. update anytime.")

    def _typed(self, api, user, text: str):
        uid = user["id"]
        st = api.state(uid)
        if st.get("compose") == "":  # awaiting question text
            if len(text) < 8:
                return self._lobby(api, uid, note="too short to decide.")
            st["compose"] = text[:MAX_Q]
            api.save(uid, st)
            return ("new question",
                    ["  deadline for resolution?"],
                    [[(f"[{i + 1}] {label}", f"horizon:{days}")
                      for i, (label, days) in enumerate(HORIZONS[:2])],
                     [(f"[{i + 3}] {label}", f"horizon:{days}")
                      for i, (label, days) in enumerate(HORIZONS[2:])]])
        if text.isdigit() and st.get("viewing"):
            return self._forecast(api, user, str(st["viewing"]), text)
        return self._lobby(api, uid)

    def _create(self, api, user, days: int):
        uid = user["id"]
        st = api.state(uid)
        text = st.pop("compose", "") or ""
        api.save(uid, st)
        g = self._g(api)
        qid = g["next"]
        g["next"] += 1
        g["q"][str(qid)] = {
            "id": qid, "text": text, "by": user["handle"], "by_uid": uid,
            "close": int(time.time()) + days * 86400,
            "created": int(time.time()), "n": 0, "res": None,
        }
        api.save(0, g)
        return self._question(api, user, str(qid),
                              note="question is live. forecast it!")

    def _resolve(self, api, user, qid: str, how: str):
        uid = user["id"]
        g = self._g(api)
        q = g["q"].get(str(qid))
        if not q or q.get("res") is not None:
            return self._lobby(api, uid)
        if uid != q.get("by_uid") and user["level"] < 100:
            return self._question(api, user, qid, note="not your call.")
        if how == "void":
            del g["q"][str(qid)]
            api.save(0, g)
            return self._lobby(api, uid, note=f"#{qid} voided. never mind.")
        outcome = 1 if how == "1" else 0
        q["res"] = outcome
        api.save(0, g)
        paid = 0
        for fuid, _h, s in api.states_full():
            fc = s.get("fc", {}).pop(str(q["id"]), None)
            if not fc:
                continue
            pts = _points(fc["p"], outcome)
            s["rating"] = s.get("rating", 0) + pts
            s["n_res"] = s.get("n_res", 0) + 1
            api.save(fuid, s)
            if pts > 0:
                api.pay(fuid, pts)
            paid += 1
        return self._lobby(
            api, uid, note=f"#{qid} resolved {'YES' if outcome else 'NO'}. "
                           f"{paid} oracles scored.")

    def _mine(self, api, uid):
        g = self._g(api)
        st = api.state(uid)
        body = ["  your open calls:", ""]
        rows = []
        fc = st.get("fc", {})
        if not fc:
            body.append("  none. the future is unread.")
        for qid, f in sorted(fc.items(), key=lambda kv: int(kv[0])):
            q = g["q"].get(qid)
            if not q:
                continue
            body.append(f"  #{qid:<3} {f['p']:>3}% · {_eta(q['close'])}")
            rows.append([(f"#{qid} · {q['text'][:24]}", f"q:{qid}")])
        body += ["", f"  rating {st.get('rating', 0):+d}"
                     f" over {st.get('n_res', 0)} resolved"]
        rows.append([("[B] BACK", "enter")])
        return "my forecasts", body, rows

    def _top(self, api):
        seers = sorted(api.states(),
                       key=lambda hs: hs[1].get("rating", 0), reverse=True)
        body = ["  the well-calibrated:", ""]
        for h, s in seers[:10]:
            if not s.get("n_res"):
                continue
            body.append(f"  {h[:12]:<13} {s.get('rating', 0):>+5}"
                        f" /{s.get('n_res', 0)}")
        if len(body) == 2:
            body.append("  nothing resolved yet.")
        return "oracle ratings", body, [[("[B] BACK", "enter")]]


def _wrap(text: str, width: int = 30) -> list[str]:
    import textwrap
    out = []
    for para in text.splitlines():
        out += textwrap.wrap(para, width) or [""]
    return out


door = OracleDoor()
