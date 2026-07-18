"""Entry point: python -m tgbbs.main  (or run.py)."""

import logging
import sys

from .config import Config
from .handlers import build_app


def main() -> None:
    cfg = Config.load()
    logdir = cfg.db_path.parent

    # console + full log on disk (append mode; logging flushes per record)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    filelog = logging.FileHandler(logdir / "bbs.log", mode="a",
                                  encoding="utf-8")
    filelog.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[console, filelog])
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # full chat transcript in its own file (file only, no console double-up)
    chat_fh = logging.FileHandler(logdir / "chat.log", mode="a",
                                  encoding="utf-8")
    chat_fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    chatlog = logging.getLogger("tgbbs.chatlog")
    chatlog.addHandler(chat_fh)
    chatlog.propagate = False
    if not cfg.token:
        print("No BBS_BOT_TOKEN. Copy .env.example to .env and set it "
              "(token from @BotFather).", file=sys.stderr)
        sys.exit(1)
    app = build_app(cfg)
    print(f"▓▒░ {cfg.bbs_name} ░▒▓  online (long polling, ctrl-c to hang up)")
    app.run_polling(
        allowed_updates=["message", "callback_query", "channel_post"])


if __name__ == "__main__":
    main()
