"""THE GALLOWS -- hangman with scene vocabulary. Type letters to guess."""

import random

WORDS = """
modem carrier sysop handle ansi ascii demoscene tracker chiptune
phreaker wardialer baudrate terminal netmail echomail fidonet
doorgame oneliner shareware crackscreen keygen intro cracktro
scroller raster plasma copper sprite blitter assembler
mainframe acoustic handshake protocol xmodem zmodem kermit
bulletin gateway node ratio leech elite lamer courier warez
"""
WORDS = [w for w in WORDS.split() if len(w) >= 4]

STAGES = [
    ["  ┌───┐", "  │", "  │", "  │", " ═╧═══"],
    ["  ┌───┐", "  │   O", "  │", "  │", " ═╧═══"],
    ["  ┌───┐", "  │   O", "  │   │", "  │", " ═╧═══"],
    ["  ┌───┐", "  │   O", "  │  /│", "  │", " ═╧═══"],
    ["  ┌───┐", "  │   O", "  │  /│\\", "  │", " ═╧═══"],
    ["  ┌───┐", "  │   O", "  │  /│\\", "  │  /", " ═╧═══"],
    ["  ┌───┐", "  │   O", "  │  /│\\", "  │  / \\", " ═╧═══"],
]
MAX_MISS = 6


class GallowsDoor:
    key = "gallows"
    title = "the gallows"
    diz = "hangman. type letters to guess"

    def handle(self, api, user, payload):
        uid = user["id"]
        cmd, _, arg = payload.partition(":")
        if cmd == "new":
            return self._new_word(api, uid)
        if cmd == "text":
            return self._guess(api, uid, arg.strip().lower())
        st = api.state(uid)
        if st.get("word") and not st.get("over"):
            return self._board(api, uid, st)
        return self._new_word(api, uid) if st.get("word") else self._intro(api, uid)

    def _intro(self, api, uid):
        st = api.state(uid)
        body = [
            "  ▄▀▄ THE GALLOWS ▄▀▄",
            "",
            "  the executioner picks a word",
            "  from the scene's vocabulary.",
            "  TYPE a letter to guess, or",
            "  type the whole word if you",
            "  dare. six misses and swing.",
            "",
            f"  saved necks: {st.get('wins', 0)}"
            f" · hangings: {st.get('losses', 0)}",
            "  win pays 2 credits a letter.",
        ]
        return "the gallows", body, [[("[N] NEW WORD", "new")]]

    def _new_word(self, api, uid):
        st = api.state(uid)
        st["word"] = random.choice(WORDS)
        st["hits"], st["miss"], st["over"] = [], [], False
        api.save(uid, st)
        return self._board(api, uid, st)

    def _board(self, api, uid, st, note: str = ""):
        word, hits, miss = st["word"], st["hits"], st["miss"]
        shown = " ".join(c if c in hits else "_" for c in word)
        body = [f"  {l}" for l in STAGES[min(len(miss), MAX_MISS)]]
        body += ["", f"   {shown}", "",
                 f"  missed: {' '.join(sorted(miss)) or '-'}"
                 f"  ({MAX_MISS - len(miss)} left)"]
        if note:
            body += [f"  {note}"]
        rows = []
        if st.get("over"):
            rows.append([("[N] ANOTHER WORD", "new")])
        else:
            body += ["", "  type your letter..."]
        return "the gallows", body, rows

    def _guess(self, api, uid, g):
        st = api.state(uid)
        if not st.get("word") or st.get("over"):
            return self._new_word(api, uid)
        word = st["word"]
        if not g or not g.isalpha():
            return self._board(api, uid, st, note="letters only, friend.")
        if len(g) > 1:  # full-word attempt: bold, binding
            if g == word:
                st["hits"] = list(set(word))
                return self._win(api, uid, st)
            st["miss"].append("*")
            return self._check_hang(api, uid, st,
                                    note=f"'{g[:12]}' is not it.")
        if g in st["hits"] or g in st["miss"]:
            return self._board(api, uid, st, note="already tried that one.")
        if g in word:
            st["hits"].append(g)
            if all(c in st["hits"] for c in word):
                return self._win(api, uid, st)
            api.save(uid, st)
            return self._board(api, uid, st, note="it's there!")
        st["miss"].append(g)
        return self._check_hang(api, uid, st, note="the rope creaks...")

    def _win(self, api, uid, st):
        st["over"] = True
        st["wins"] = st.get("wins", 0) + 1
        api.save(uid, st)
        prize = 2 * len(st["word"])
        bal = api.pay(uid, prize)
        return self._board(api, uid, st,
                           note=f"░▒▓ SAVED! '{st['word']}' ▓▒░ "
                                f"+{prize}c (bal {bal})")

    def _check_hang(self, api, uid, st, note: str):
        if len(st["miss"]) >= MAX_MISS:
            st["over"] = True
            st["losses"] = st.get("losses", 0) + 1
            api.save(uid, st)
            return self._board(api, uid, st,
                               note=f"▓▒░ HANGED. it was "
                                    f"'{st['word']}'. ░▒▓")
        api.save(uid, st)
        return self._board(api, uid, st, note=note)


door = GallowsDoor()
