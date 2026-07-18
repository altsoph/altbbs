"""ONE-ARMED BANDIT -- ascii slot machine. The house always wins, slowly."""

import random

SYMBOLS = "7$*@#%"
WEIGHTS = (1, 2, 3, 4, 5, 6)  # 7 is rare, % is everywhere


def _spin() -> list[str]:
    return random.choices(SYMBOLS, weights=WEIGHTS, k=3)


def _payout(reels: list[str], bet: int) -> tuple[int, str]:
    a, b, c = reels
    if a == b == c == "7":
        return bet * 100, "░▒▓ J A C K P O T ▓▒░"
    if a == b == c:
        return bet * 10, "three of a kind!"
    if [a, b, c].count("7") == 2:
        return bet * 5, "double sevens!"
    return 0, "the machine hums, unmoved."


def _reel_art(reels: list[str]) -> list[str]:
    r = reels
    return [
        "┌───┬───┬───┐",
        f"│ {r[0]} │ {r[1]} │ {r[2]} │",
        "└───┴───┴───┘",
    ]


class SlotsDoor:
    key = "slots"
    title = "one-armed bandit"
    diz = "three reels, no mercy. 777 pays"

    def handle(self, api, user, payload):
        uid = user["id"]
        cmd, _, arg = payload.partition(":")
        if cmd == "bet":
            return self._pull(api, uid, int(arg))
        return self._lobby(api, uid)

    def _lobby(self, api, uid, note: str = ""):
        bal = api.credits(uid)
        st = api.state(uid)
        body = [
            "  ▄▀▄ THE BANDIT ▄▀▄",
            "",
            "  777          pays 100x",
            "  3 of a kind  pays  10x",
            "  double 7     pays   5x",
            "",
            f"  credits: {bal}",
            f"  best hit: {st.get('best', 0)}",
        ]
        if note:
            body += ["", f"  {note}"]
        if bal <= 0:
            body += ["", "  busted. earn credits on the",
                     "  board: post, upload, call."]
            return "one-armed bandit", body, []
        rows = [[("[1] PULL FOR 5", "bet:5"), ("[2] PULL FOR 10", "bet:10")],
                [("[3] PULL FOR 25", "bet:25")]]
        return "one-armed bandit", body, rows

    def _pull(self, api, uid, bet: int):
        bal = api.credits(uid)
        if bet <= 0 or bet > bal:
            return self._lobby(api, uid, note="you can't cover that pull.")
        reels = _spin()
        win, verdict = _payout(reels, bet)
        bal = api.pay(uid, win - bet)
        st = api.state(uid)
        if win > st.get("best", 0):
            st["best"] = win
            api.save(uid, st)
        body = ["  the reels tumble...", ""]
        body += [f"    {l}" for l in _reel_art(reels)]
        body += ["", f"  {verdict}",
                 f"  {'+' if win - bet > 0 else ''}{win - bet} credits "
                 f"· balance {bal}"]
        rows = [[(f"[A] AGAIN ({bet})", f"bet:{bet}"),
                 ("[B] CHANGE BET", "enter")]]
        return "one-armed bandit", body, rows


door = SlotsDoor()
