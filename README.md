# altBBS — an old-school BBS inside Telegram

```
        █   █   ▛▀▀▄ ▛▀▀▄ ▄▀▀▀▄
   ▄▀▀▄ █  ▀█▀  ▙▄▄▀ ▙▄▄▀ ▀▄▄
   █▄▄█ █▄  █▄  ▌  ▐ ▌  ▐ ▄  ▝▌
   ▄▄▄▄▄▄▄▄▄▄▄▄▄▙▄▄▀▄▙▄▄▀▄▝▄▄▄▀
      ▓▒░ CARRIER DETECTED ░▒▓
```

A multiuser bulletin board system that lives in a Telegram bot: message
bases, private mail, file areas with FILE_ID.DIZ descriptions, oneliners,
last callers, user levels and a sysop — rendered as 34-column monospace
ASCII screens with demoscene-style gradients, one edited `<pre>` message
acting as your terminal.

Design is modeled on **Synchronet** (see `docs/01-bbs-software-analysis.md`);
the Telegram platform survey is in `docs/02-telegram-apps-analysis.md`.

## Why it is locally secure

- **Long polling** — the bot makes only *outbound* HTTPS connections to
  Telegram. No webhook, no open ports, no public IP, runs behind NAT.
- **All data local** — one SQLite file in `data/bbs.db`. Files are stored
  as Telegram `file_id` references, exchanged peer→Telegram→peer.
- **Token hygiene** — token lives in `.env`, which is git-ignored.
- **Access levels** — Synchronet-style 0–255 security levels gate boards
  and file areas; `BBS_NEW_USERS=closed` turns it into an invite-only
  system; `/ban` for misbehaving callers.
- All user text is HTML-escaped before rendering.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # then paste your token from @BotFather
.\.venv\Scripts\python run.py
```

(Linux/macOS: `.venv/bin/python` instead.)

1. Talk to **@BotFather** → `/newbot` → copy the token into `.env`.
2. Start the bot, then open your bot in Telegram and send `/start`.
3. **The first caller to register becomes the sysop (level 255).**

## Using the board

- `/start` connects; new callers pick a *handle* (2–16 chars).
- Everything else is inline buttons — the classic hotkey menu:
  `[M]` message bases · `[E]` mail · `[F]` files · `[O]` oneliners ·
  `[L]` last callers · `[U]` users · `[G]` logoff (`+++ATH0`).
- **Posting**: open a base → `[P] POST` → type your message
  (first line acts as the subject).
- **Mail**: `[E]` → `[W] WRITE` → recipient handle → text. Recipients
  get a "you've got mail!" ping.
- **Files**: open a file area, then just *send the bot any document* —
  it lands in that area; you'll be asked for a FILE_ID.DIZ description.
  `[D] DOWNLOAD` sends it back to any caller. (Bot API: up to ~50 MB
  per file, plenty for art packs and intros.)

## Sysop

- Sysop office button (level ≥ 100): create message bases / file areas
  (`name | description`).
- Text commands: `/setlevel <handle> <0-255>`, `/ban <handle>`,
  `/unban <handle>`, `/invite <tg_user_id>` (for closed systems).
- Level 100+ sees the staff-only *sysop office* board.

## Configuration (`.env`)

| var             | default                   | meaning                       |
|-----------------|---------------------------|-------------------------------|
| `BBS_BOT_TOKEN` | —                         | bot token (required)          |
| `BBS_NAME`      | `altBBS`                  | system name                   |
| `BBS_TAGLINE`   | `est. 2026 * 34 cols ...` | shown around the place        |
| `BBS_NEW_USERS` | `open`                    | `closed` = invite-only        |

## Development

```powershell
.\.venv\Scripts\python selftest.py   # offline: renders every screen, checks ACLs
```

Code layout: `tgbbs/config.py` (env), `db.py` (SQLite schema + queries),
`art.py` (logo, bars, ANSI-ish assets), `render.py` (screen composer),
`handlers.py` (state machine: screens, buttons, typed input, uploads),
`main.py` (long-polling entry point).

## Roadmap ideas

- newscan (unread-message loop with per-user scan pointers)
- door games API (simple turn-based modules)
- Mini App front-end with a real CRT terminal look
- QWK-style export / federation between boards
