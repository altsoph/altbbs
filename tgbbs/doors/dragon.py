"""THE DRAGON'S TOWER -- a LORD-flavoured daily-turns dungeon.

Climb the tower, slay what lurks on the stairs, level up, and one day
face the RED DRAGON on the roof. 8 fights a day; dying burns the rest
of today's turns and a quarter of your credits. Respect to Seth Able.
"""

import random
import time

#           name                 hp   dmg  xp   loot(credits)
MONSTERS = [
    ("a basement rat",           12,   3,  10,   4),
    ("a mangy modem dog",        20,   5,  18,   8),
    ("a script kiddie",          30,   7,  30,  14),
    ("a lamer with a crowbar",   42,   9,  45,  20),
    ("an ansi vandal",           56,  12,  65,  28),
    ("a spam golem",             72,  15,  90,  38),
    ("a trojan courier",         90,  18, 120,  50),
    ("an elite cracker",        110,  22, 160,  70),
    ("the sysop's cat",         135,  27, 210, 100),
    ("THE RED DRAGON",          200,  34, 400, 500),
]
FIGHTS_PER_DAY = 8


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _bar(cur: int, top: int, width: int = 10) -> str:
    cur = max(0, cur)
    full = 0 if top <= 0 else round(width * cur / top)
    return "▓" * full + "░" * (width - full)


class DragonDoor:
    key = "dragon"
    title = "the dragon's tower"
    diz = "daily-turn dungeon. dragon waits"

    # -- character sheet ----------------------------------------------------
    def _char(self, api, uid) -> dict:
        st = api.state(uid)
        st.setdefault("lvl", 1)
        st.setdefault("xp", 0)
        st.setdefault("maxhp", 40)
        st.setdefault("hp", st["maxhp"])
        st.setdefault("kills", 0)
        st.setdefault("dragon_kills", 0)
        if st.get("day") != _today():
            st["day"] = _today()
            st["fights"] = FIGHTS_PER_DAY
            st["hp"] = st["maxhp"]
        return st

    def _xp_next(self, lvl: int) -> int:
        return lvl * 80

    def handle(self, api, user, payload):
        uid = user["id"]
        cmd = payload.split(":")[0]
        if cmd == "fight":
            return self._fight_start(api, uid)
        if cmd == "atk":
            return self._fight_round(api, uid, run=False)
        if cmd == "run":
            return self._fight_round(api, uid, run=True)
        if cmd == "heal":
            return self._heal(api, uid)
        if cmd == "fame":
            return self._fame(api)
        return self._lobby(api, uid)

    # -- screens -------------------------------------------------------------
    def _lobby(self, api, uid, note: str = ""):
        st = self._char(api, uid)
        st.pop("mon", None)  # walking away from a fight resets it
        st.pop("mhp", None)
        api.save(uid, st)
        bal = api.credits(uid)
        body = [
            "  ▄▀▄ THE DRAGON'S TOWER ▄▀▄",
            "",
            f"  level {st['lvl']} warrior of the board",
            f"  hp {_bar(st['hp'], st['maxhp'])} {st['hp']}/{st['maxhp']}",
            f"  xp {st['xp']}/{self._xp_next(st['lvl'])}"
            f" · kills {st['kills']}",
            f"  fights left today: {st['fights']}",
            f"  credits: {bal}",
        ]
        if st["dragon_kills"]:
            body.append(f"  ░▒▓ DRAGONSLAYER x{st['dragon_kills']} ▓▒░")
        if note:
            body += ["", f"  {note}"]
        rows = []
        if st["fights"] > 0:
            rows.append([(f"[F] FIGHT ({st['fights']} left)", "fight")])
        else:
            body += ["", "  the stairs are dark. come",
                     "  back tomorrow, warrior."]
        heal_cost = max(0, (st["maxhp"] - st["hp"]) // 2)
        if heal_cost and bal >= heal_cost:
            rows.append([(f"[H] HEAL ({heal_cost}c)", "heal")])
        rows.append([("[T] HALL OF FAME", "fame")])
        return "dragon's tower", body, rows

    def _fight_start(self, api, uid):
        st = self._char(api, uid)
        if st["fights"] <= 0:
            return self._lobby(api, uid, note="no fights left today.")
        st["fights"] -= 1
        tier = min(len(MONSTERS) - 1,
                   max(0, st["lvl"] - 1 + random.randint(-1, 1)))
        if st["lvl"] >= 8 and random.random() < 0.25:
            tier = len(MONSTERS) - 1  # the roof beckons
        st["mon"], st["mhp"] = tier, MONSTERS[tier][1]
        api.save(uid, st)
        name = MONSTERS[tier][0]
        body = ["  on the stairs you meet...", "",
                f"  {name}!", "",
                f"  its hp {_bar(st['mhp'], MONSTERS[tier][1])}",
                f"  your hp {_bar(st['hp'], st['maxhp'])}"
                f" {st['hp']}/{st['maxhp']}"]
        return "dragon's tower", body, [
            [("[A] ATTACK", "atk"), ("[R] RUN", "run")]]

    def _fight_round(self, api, uid, run: bool):
        st = self._char(api, uid)
        if "mon" not in st:
            return self._lobby(api, uid)
        tier = st["mon"]
        name, mhp_max, mdmg, xp, loot = MONSTERS[tier]
        if run:
            st.pop("mon"), st.pop("mhp")
            dmg = random.randint(0, mdmg // 2)
            st["hp"] = max(1, st["hp"] - dmg)
            api.save(uid, st)
            return self._lobby(api, uid,
                               note=f"you flee. {name} claws you for "
                                    f"{dmg} on the way out.")
        # your swing
        pdmg = 6 + st["lvl"] * 3 + random.randint(0, 4)
        st["mhp"] -= pdmg
        lines = [f"  you hit {name}", f"  for {pdmg} damage!"]
        if st["mhp"] <= 0:
            st.pop("mon"), st.pop("mhp")
            st["kills"] += 1
            st["xp"] += xp
            if tier == len(MONSTERS) - 1:
                st["dragon_kills"] += 1
            api.pay(uid, loot)
            note = f"you slew {name}! +{xp}xp +{loot}c"
            while st["xp"] >= self._xp_next(st["lvl"]):
                st["xp"] -= self._xp_next(st["lvl"])
                st["lvl"] += 1
                st["maxhp"] += 12
                st["hp"] = st["maxhp"]
                note += f" ░▒▓ DING! level {st['lvl']} ▓▒░"
            api.save(uid, st)
            return self._lobby(api, uid, note=note)
        # its swing back
        dmg = random.randint(mdmg // 2, mdmg)
        st["hp"] -= dmg
        lines += [f"  it rips back for {dmg}!"]
        if st["hp"] <= 0:
            st.pop("mon"), st.pop("mhp")
            st["hp"], st["fights"] = st["maxhp"], 0
            api.save(uid, st)
            lost = api.credits(uid) // 4
            api.pay(uid, -lost)
            return self._lobby(api, uid,
                               note=f"YOU DIED. {name} takes {lost} "
                                    "credits off your corpse. "
                                    "tomorrow, revenge.")
        api.save(uid, st)
        body = lines + ["",
                        f"  its hp  {_bar(st['mhp'], mhp_max)}",
                        f"  your hp {_bar(st['hp'], st['maxhp'])}"
                        f" {st['hp']}/{st['maxhp']}"]
        return "dragon's tower", body, [
            [("[A] ATTACK", "atk"), ("[R] RUN", "run")]]

    def _heal(self, api, uid):
        st = self._char(api, uid)
        cost = max(0, (st["maxhp"] - st["hp"]) // 2)
        if cost == 0:
            return self._lobby(api, uid, note="you're already whole.")
        if api.credits(uid) < cost:
            return self._lobby(api, uid, note="the healer wants cash up front.")
        api.pay(uid, -cost)
        st["hp"] = st["maxhp"]
        api.save(uid, st)
        return self._lobby(api, uid, note=f"patched up. -{cost} credits.")

    def _fame(self, api):
        heroes = sorted(api.states(),
                        key=lambda hs: (hs[1].get("dragon_kills", 0),
                                        hs[1].get("lvl", 0),
                                        hs[1].get("kills", 0)),
                        reverse=True)[:10]
        body = ["  the tower remembers:", ""]
        for h, s in heroes:
            drag = "▓" * s.get("dragon_kills", 0)
            body.append(f"  lv{s.get('lvl', 1):>2} {h[:12]:<13}"
                        f" {s.get('kills', 0):>3}k {drag}")
        if len(body) == 2:
            body.append("  no one has dared the stairs.")
        rows = [[("[B] BACK", "enter")]]
        return "hall of fame", body, rows


door = DragonDoor()
