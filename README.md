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
  **Typing the hotkey letter works too** (`m`, `q`, `<`/`>` for
  prev/next page) — just like a real terminal.
- **Posting**: open a base → `[P] POST` → type your message
  (first line acts as the subject).
- **Mail**: `[E]` → `[W] WRITE` → recipient handle → text. Recipients
  get a "you've got mail!" ping.
- **Files**: open a file area, then just *send the bot any document* —
  it lands in that area; you'll be asked for a FILE_ID.DIZ description.
  `[D] DOWNLOAD` sends it back to any caller. (Bot API: up to ~50 MB
  per file, plenty for art packs and intros.)
- **Newscan** (`[N]`): the classic unread-message loop. Per-user scan
  pointers per board; the menu badge shows how much is waiting, and
  the loop steps through every new message across all your boards —
  `[N]` next, `[S]` skip base, `[R]` reply, `[A]` mark all read.
- **Door games** (`[D]`): drop-in turn-based modules with persistent
  state and a board-wide credit economy (earn +5/call, +2/post,
  +25/upload). Ships with four doors: **HI-LO CASINO** (ties feed
  the house), the **ONE-ARMED BANDIT** (777 pays 100x), **THE
  DRAGON'S TOWER** (LORD-style daily-turns dungeon — 8 fights a day,
  level up, heal for credits, hall of fame, and a RED DRAGON on the
  roof), and **THE GALLOWS** (hangman over scene vocabulary — type
  your letters). Write your own door in ~50 lines: see
  `tgbbs/doors/__init__.py`.
- **Chat pit** (`[C]`): live multi-node chat. Everyone currently in the
  pit sees new lines appear on their terminal in real time; joins and
  leaves are announced. The main menu shows how many are chatting.
- **ASCII image viewer**: send the bot any photo and it comes back as
  monochrome ASCII art on your terminal. Image files in file areas get
  a `[V] VIEW ASCII` button (up to 20 MB, the Bot API getFile limit).
- **Node log**: the console prints a classic sysop log of real caller
  activity — calls, registrations, navigation, posts, mail, chat
  lines, uploads, downloads and ascii views. The same detailed log is
  appended to `data/bbs.log` (flushed per record), and the full chat
  transcript goes to `data/chat.log`.

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

## Bootstrap content

A fresh board is a lonely board. Seed it with old-school life:

```powershell
.\.venv\Scripts\python bootstrap.py
```

This adds (idempotently, and it never touches real users or the sysop
seat — ghost users live on negative ids):

- 8 ghost callers (`n3uromancer`, `ansi_ghost`, `z80phreak`, ...)
- ~17 posts across the boards: threads about current AI/tech news
  (frontier-model math results, the StackOverflow decline, AI code
  review discourse, supply-chain scandals, Z80 at 50)
- e-zine files in the file areas, served from `bootstrap/files/`:
  `RAW_SYNAPSE-001.TXT` (the neural underground e-zine),
  `NEURAL_UNDERGROUND-007.NFO`, an altBBS ascii logo pack, and
  2026-edition modem init strings
- a wall of oneliners

## News wire (scheduled import)

So there's always something real to read, the bot imports headlines on a
schedule into three auto-created boards, posted by the ghost user
`newswire`:

- **hn wire** — Hacker News front page (score ≥ 100)
- **lobsters wire** — lobste.rs hottest
- **trends wire** — [shir-man.com](https://shir-man.com/homepage/)
  merged top-of-day dashboard (RSS)

On top of that, drop an **OPML file** (e.g. a Feedly export) into the
repo root — or point `BBS_FEED_OPML` at one — and every category in it
becomes its own wire board (`tech wire`, `ml/ai wire`, ...) fed by
those RSS/Atom feeds. Entries older than `BBS_FEED_MAX_AGE_DAYS`
(default 45) are ignored, and dead feeds are skipped with a log line.

Every story is deduplicated by normalized URL *across all sources*
(tracking params, `www.`, scheme and trailing slashes ignored), so an
HN story that also surfaces on the trends dashboard is posted once.
Imports run 30 s after boot and then every `BBS_FEED_INTERVAL_MIN`
(default 3 h), capped at `BBS_FEED_MAX_PER_SOURCE` new posts per source
per run. Sysops can trigger a run any time with `/fetchnews`, or turn
the whole thing off with `BBS_FEED=off`.

## Development

```powershell
.\.venv\Scripts\python selftest.py   # offline: renders every screen, checks ACLs
```

Code layout: `tgbbs/config.py` (env), `db.py` (SQLite schema + queries),
`art.py` (logo, bars, ANSI-ish assets), `render.py` (screen composer),
`handlers.py` (state machine: screens, buttons, typed input, uploads),
`main.py` (long-polling entry point).

## Roadmap ideas

- more doors (tradewars? inter-user duels?)
- Mini App front-end with a real CRT terminal look
- QWK-style export / federation between boards
