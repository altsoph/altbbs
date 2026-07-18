"""Configuration: .env file + environment variables."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# bundled bootstrap files, served when a DB record's tg_file_id is "local:<name>"
FILES_DIR = ROOT / "bootstrap" / "files"


def _load_dotenv(path: Path) -> None:
    """Tiny .env parser -- KEY=VALUE lines, # comments. No dependency needed."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


@dataclass
class Config:
    token: str = ""
    bbs_name: str = "altBBS"
    tagline: str = "est. 2026 * 34 cols * node 1"
    new_users_open: bool = True
    width: int = 34               # screen width in monospace columns
    page_size: int = 7            # list items per page
    db_path: Path = field(default_factory=lambda: ROOT / "data" / "bbs.db")
    # news wire
    feed_enabled: bool = True
    feed_interval_min: int = 180
    feed_max_per_source: int = 5
    feed_hn_min_score: int = 100
    feed_opml: str = ""           # OPML path; empty = first *.opml in repo root
    feed_max_age_days: int = 45   # ignore OPML feed entries older than this
    # CRT web terminal (Mini App)
    web_url: str = ""             # public https URL of the tunnel
    web_port: int = 8737          # local bind port (127.0.0.1 only)
    web_enabled: bool = False
    web_dev: bool = False         # auth bypass for the local test rig
    # echomail federation (shared Telegram channel as the hub)
    echo_channel: str = ""        # channel id (-100...) or @username
    echo_id: str = "ALTBBS"       # this system's unique network name
    eliza_enabled: bool = True    # the chat pit's resident (1966, no AI)

    @classmethod
    def load(cls) -> "Config":
        _load_dotenv(ROOT / ".env")
        cfg = cls(
            token=os.environ.get("BBS_BOT_TOKEN", ""),
            bbs_name=os.environ.get("BBS_NAME", cls.bbs_name),
            tagline=os.environ.get("BBS_TAGLINE", cls.tagline),
            new_users_open=os.environ.get("BBS_NEW_USERS", "open").lower() != "closed",
            feed_enabled=os.environ.get("BBS_FEED", "on").lower() not in ("off", "0", "no"),
            feed_interval_min=int(os.environ.get("BBS_FEED_INTERVAL_MIN", "180")),
            feed_max_per_source=int(os.environ.get("BBS_FEED_MAX_PER_SOURCE", "5")),
            feed_hn_min_score=int(os.environ.get("BBS_FEED_HN_MIN_SCORE", "100")),
            feed_opml=os.environ.get("BBS_FEED_OPML", ""),
            feed_max_age_days=int(os.environ.get("BBS_FEED_MAX_AGE_DAYS", "45")),
            web_url=os.environ.get("BBS_WEB_URL", ""),
            web_port=int(os.environ.get("BBS_WEB_PORT", "8737")),
            web_dev=os.environ.get("BBS_WEB_DEV", "") == "1",
        )
        web = os.environ.get("BBS_WEB", "auto").lower()
        cfg.web_enabled = web == "on" or (web != "off" and bool(cfg.web_url))
        cfg.eliza_enabled = os.environ.get(
            "BBS_ELIZA", "on").lower() not in ("off", "0", "no")
        cfg.echo_channel = os.environ.get("BBS_ECHO_CHANNEL", "")
        cfg.echo_id = (os.environ.get("BBS_ECHO_ID", "") or
                       re.sub(r"[^A-Z0-9]", "",
                              cfg.bbs_name.upper())[:8] or "ALTBBS")
        cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        return cfg
