"""Door games: drop-in turn-based modules, like BBS doors of old.

Writing a door
--------------
Create `tgbbs/doors/<name>.py` with a class exposing:

    key    -- short unique slug (used in callback routing)
    title  -- shown in the doors menu (lowercase, keep it short)
    diz    -- one-line description for the menu

    def handle(self, api, user, payload) -> (title, body_lines, rows)

and a module-level instance named `door`. The framework calls
`handle()` with:

    payload  "enter" on entry, your own action strings from buttons,
             or "text:<line>" when the caller types something
    api      a DoorAPI bound to your door (state + credits, see below)
    user     the sqlite user row (id, handle, level, ...)

Return the screen: `rows` is a list of button rows, each button a
`(label, action)` tuple. Actions are routed back to your `handle()`;
prefix an action with `!` to emit a raw BBS callback instead (e.g.
`("[Q] OUT", "!menu")`). A `[Q] LEAVE` button is appended for free.
State is any JSON-able dict; credits are the board-wide currency.
"""

import importlib
import json
import pkgutil

from ..db import DB


class DoorAPI:
    """What a door is allowed to touch: its own state + the credit bank."""

    def __init__(self, db: DB, door_key: str):
        self._db = db
        self._key = door_key

    def state(self, uid: int) -> dict:
        return json.loads(self._db.door_state(uid, self._key))

    def save(self, uid: int, state: dict) -> None:
        self._db.save_door_state(uid, self._key, json.dumps(state))

    def credits(self, uid: int) -> int:
        return self._db.credits(uid)

    def pay(self, uid: int, delta: int) -> int:
        """Adjust the caller's credits (floored at 0); returns new balance."""
        return self._db.add_credits(uid, delta)

    def top(self, limit: int = 10):
        return self._db.top_credits(limit)

    def states(self) -> list[tuple[str, dict]]:
        """(handle, state) for every user who has played this door."""
        rows = self._db.conn.execute(
            "SELECT u.handle, ds.state FROM door_state ds "
            "JOIN users u ON u.id=ds.user_id WHERE ds.door=?",
            (self._key,)).fetchall()
        return [(r["handle"], json.loads(r["state"])) for r in rows]

    def states_full(self) -> list[tuple[int, str, dict]]:
        """(user_id, handle, state) -- for doors that need to pay users."""
        rows = self._db.conn.execute(
            "SELECT ds.user_id, u.handle, ds.state FROM door_state ds "
            "JOIN users u ON u.id=ds.user_id WHERE ds.door=?",
            (self._key,)).fetchall()
        return [(r["user_id"], r["handle"], json.loads(r["state"]))
                for r in rows]


def _load_doors() -> dict:
    doors = {}
    for mod_info in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{mod_info.name}")
        door = getattr(mod, "door", None)
        if door is not None:
            doors[door.key] = door
    return doors


DOORS = _load_doors()
