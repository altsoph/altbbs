"""HI-LO CASINO -- the timeless BBS money pit.

Guess whether the next card is higher or lower. Ties go to the house.
Aces high. The pit boss remembers your best streak.
"""

import random

RANKS = "23456789TJQKA"
SUITS = "shdc"  # ascii suits: safe in every monospace font


def _draw() -> list:
    return [random.randrange(13), random.randrange(4)]


def _face(card) -> str:
    r = RANKS[card[0]]
    return ("10" if r == "T" else r) + SUITS[card[1]]


def _card_art(card) -> list[str]:
    f = _face(card)
    return [
        "┌─────┐",
        f"│{f:<3}  │",
        "│  ?  │".replace("?", "·"),
        f"│  {f:>3}│",
        "└─────┘",
    ]


def _two_cards(a, b) -> list[str]:
    return [x + "  " + y for x, y in zip(_card_art(a), _card_art(b))]


class CasinoDoor:
    key = "casino"
    title = "hi-lo casino"
    diz = "guess hi/lo. ties feed the house"

    def handle(self, api, user, payload):
        uid = user["id"]
        cmd, _, arg = payload.partition(":")
        if cmd == "bet":
            return self._deal(api, uid, int(arg))
        if cmd in ("hi", "lo"):
            return self._resolve(api, uid, cmd)
        if cmd == "top":
            return self._top(api)
        if cmd == "beg":
            return self._beg(api, uid)
        return self._lobby(api, uid)  # enter / typed text / anything else

    # -- screens ----------------------------------------------------------
    def _lobby(self, api, uid, note: str = ""):
        bal = api.credits(uid)
        st = api.state(uid)
        body = [
            "  ▄▀▄ H I - L O ▄▀▄",
            "",
            "  next card higher or lower?",
            "  ties go to the house.",
            "  aces high. no mercy.",
            "",
            f"  credits: {bal}",
            f"  best streak: {st.get('best', 0)}",
        ]
        if note:
            body += ["", f"  {note}"]
        if bal <= 0:
            body += ["", "  you're BUSTED, caller."]
            rows = [[("[B] BEG THE PIT BOSS", "beg")]]
        else:
            rows = [[("[1] BET 10", "bet:10"), ("[2] BET 25", "bet:25")],
                    [("[3] BET 100", "bet:100"), ("[T] HIGH ROLLERS", "top")]]
        return "hi-lo casino", body, rows

    def _deal(self, api, uid, bet: int):
        bal = api.credits(uid)
        if bet <= 0 or bet > bal:
            return self._lobby(api, uid, note="you can't cover that bet.")
        st = api.state(uid)
        st["card"], st["bet"] = _draw(), bet
        api.save(uid, st)
        body = ["  the dealer flips:", ""]
        body += [f"    {l}" for l in _card_art(st["card"])]
        body += ["", f"  bet: {bet} · the next card is..."]
        rows = [[("[H] HIGHER", "hi"), ("[L] LOWER", "lo")]]
        return "hi-lo casino", body, rows

    def _resolve(self, api, uid, guess: str):
        st = api.state(uid)
        if "card" not in st:
            return self._lobby(api, uid)
        a, bet = st.pop("card"), st.pop("bet", 0)
        b = _draw()
        win = (b[0] > a[0]) if guess == "hi" else (b[0] < a[0])
        delta = bet if win else -bet
        bal = api.pay(uid, delta)
        st["streak"] = st.get("streak", 0) + 1 if win else 0
        st["best"] = max(st.get("best", 0), st["streak"])
        api.save(uid, st)
        if win:
            verdict = "░▒▓ YOU WIN ▓▒░"
        elif b[0] == a[0]:
            verdict = "a tie. the house smiles."
        else:
            verdict = "▓▒░ house wins ░▒▓"
        body = [f"  {l}" for l in _two_cards(a, b)]
        body += ["", f"  {verdict}",
                 f"  {'+' if delta > 0 else ''}{delta} credits · balance {bal}",
                 f"  streak {st['streak']} · best {st['best']}"]
        rows = [[(f"[A] AGAIN ({bet})", f"bet:{bet}"), ("[B] TABLE", "enter")],
                [("[T] HIGH ROLLERS", "top")]]
        return "hi-lo casino", body, rows

    def _top(self, api):
        body = ["  the high rollers:", ""]
        for i, r in enumerate(api.top(10), 1):
            handle = r["handle"][:12]
            body.append(f"  {i:>2}. {handle:<13} {r['amount']:>6}")
        if len(body) == 2:
            body.append("  nobody has played yet.")
        rows = [[("[B] BACK TO TABLE", "enter")]]
        return "high rollers", body, rows

    def _beg(self, api, uid):
        if api.credits(uid) <= 0:
            api.pay(uid, 20)
            note = "the pit boss sighs. +20. scram."
        else:
            note = "you're not broke. beat it."
        return self._lobby(api, uid, note=note)


door = CasinoDoor()
