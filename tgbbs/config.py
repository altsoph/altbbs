"""Configuration: .env file + environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
    bbs_name: str = "MIDNIGHT TOWER"
    tagline: str = "est. 2026 * 34 cols * node 1"
    new_users_open: bool = True
    width: int = 34               # screen width in monospace columns
    page_size: int = 7            # list items per page
    db_path: Path = field(default_factory=lambda: ROOT / "data" / "bbs.db")

    @classmethod
    def load(cls) -> "Config":
        _load_dotenv(ROOT / ".env")
        cfg = cls(
            token=os.environ.get("BBS_BOT_TOKEN", ""),
            bbs_name=os.environ.get("BBS_NAME", cls.bbs_name),
            tagline=os.environ.get("BBS_TAGLINE", cls.tagline),
            new_users_open=os.environ.get("BBS_NEW_USERS", "open").lower() != "closed",
        )
        cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        return cfg
