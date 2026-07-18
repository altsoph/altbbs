"""Entry point: python -m tgbbs.main  (or run.py)."""

import logging
import sys

from .config import Config
from .handlers import build_app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = Config.load()
    if not cfg.token:
        print("No BBS_BOT_TOKEN. Copy .env.example to .env and set it "
              "(token from @BotFather).", file=sys.stderr)
        sys.exit(1)
    app = build_app(cfg)
    print(f"▓▒░ {cfg.bbs_name} ░▒▓  online (long polling, ctrl-c to hang up)")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
