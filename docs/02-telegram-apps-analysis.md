# Telegram Interactive Apps: Analysis for a BBS-Style Experience

*Research date: 2026-07-18. Current Bot API: 10.2 (2026-07-14). Verified against core.telegram.org and library docs/PyPI.*

Goal: build a text-terminal-style, multiuser BBS in Python, hosted locally, with an ASCII aesthetic. Below are all realistic ways to run "interactive apps" inside Telegram, with capabilities, limits, and fit.

---

## 1. Bot API bots (the classic approach)

An HTTPS API served by Telegram (`api.telegram.org`). You never open a port yourself unless you choose webhooks.

### Update delivery: long polling vs webhooks
| | Long polling (`getUpdates`) | Webhooks (`setWebhook`) |
|---|---|---|
| Network requirements | **Outbound HTTPS only** — no public IP, no open ports, no TLS cert, works behind NAT/firewall | Public HTTPS endpoint (ports 443/80/88/8443), valid cert (self-signed allowed if uploaded) |
| Latency | ~instant with long-poll timeout (e.g. 30–50 s hanging request) | Instant push |
| Ops complexity | Trivial; ideal for a home server / Raspberry Pi | Reverse proxy, cert renewal, exposed surface |
| Scale | Fine to thousands of users | Better at very high volume |

For a locally hosted BBS, **long polling wins decisively**: zero inbound attack surface.

### Capabilities relevant to a BBS
- **Message editing** — `editMessageText` lets you redraw one message in place: the core trick for a "terminal screen". No hard documented edit-count limit, but messages older than 48 h historically can't be edited by bots in some contexts, and edits count against flood limits.
- **Formatting** — `parse_mode=HTML` or `MarkdownV2`. HTML is strongly preferred (MarkdownV2 requires escaping 18 special characters). `<pre>` and `<code>` render in **monospace** on all official clients; `<pre><code class="language-x">` gives syntax-highlight hints. This is how you fake a terminal.
- **Inline keyboards + callback queries** — buttons attached under a message; presses arrive as `callback_query` updates with **callback_data limited to 1–64 bytes**. Answering with `answerCallbackQuery` (optionally with a toast/alert) is mandatory to stop the client spinner. Pressing a button and editing the same message = flicker-free screen refresh.
- **Reply keyboards** — replace the user's system keyboard with custom buttons; more intrusive, send a real message per press. Useful for a persistent "command bar" but inferior to inline keyboards for menus.
- **ForceReply** — forces the client into reply-to mode; handy for prompting free-text input ("Enter message subject:") in group contexts or without state confusion.
- **Files** — download up to **20 MB** via `getFile`, upload up to **50 MB** (2 GB if you self-host the Bot API server, `telegram-bot-api` binary, which also lifts the download limit). Files are addressed by reusable `file_id` — re-sending a cached upload is free and instant. Good enough for a BBS "file area" of text files, small zips, door-game assets.
- **Rate limits** — ~**30 messages/second global**, ~**1 message/second per chat** (burst tolerated, sustained violations get 429 + `retry_after`), ~20 messages/minute to the same group. Message edits count toward these. Design consequence: per-chat screen redraws should be throttled/debounced to ~1/s.
- **Privacy mode** — in groups, bots by default only see commands, replies to them, and mentions. Disable via @BotFather if the BBS should have group features; irrelevant for 1:1 chats (bots see everything there).
- **Message size** — **4096 characters** of text per message (captions 1024). Note: Bot API 10.x (2026) introduced *Rich Messages* allowing much longer structured/streamed bot output, but classic `<pre>` screens should still budget for 4096.
- **New in 2025–2026, possibly useful later:** `sendMessageDraft` streaming (API 9.3), ephemeral per-user messages in groups (10.1+), checklists, Stars payments (paid door games?).

**Pros:** free, no infrastructure exposure, stateful conversations are entirely your code, monospace + inline keyboards ≈ a real terminal with softkeys.
**Cons:** 4096-char screens, ~1 edit/s/chat, no true keystroke input (users type lines or press buttons), rendering varies slightly per client.

## 2. Telegram Mini Apps (Web Apps / TWA)

Full HTML/JS/CSS apps opened in a webview inside Telegram, launched from a keyboard button, menu button, inline button, or `t.me/bot/app` direct link.

- **Auth:** Telegram passes `initData` (user id, name, etc.) signed with HMAC-SHA-256 keyed by your bot token — verify server-side before trusting it. Since July 2026 Telegram also enforces same-origin restrictions on Mini App methods (security hardening).
- **Requirements:** you must **host the app over public HTTPS** — which contradicts the "no open ports, local-only" goal (tunnels like Cloudflare/ngrok are a workaround with their own trust trade-offs).
- **Capabilities:** full canvas/DOM — you could render a pixel-perfect CRT terminal with a blinking cursor, custom fonts (real 80-column!), sounds, WebSocket to your server for true real-time multiuser interaction. `MainButton`/`SecondaryButton`, haptics, theming, fullscreen mode.
- **When worth it:** when the chat-message medium is the bottleneck — real-time chat rooms, ANSI art viewers, door games needing keyboard/canvas. **When not:** menu-driven boards, posting, mail — plain bot messages do this fine with far less infrastructure.

Verdict: excellent **optional phase-2 enhancement**, wrong choice as the foundation for a locally hosted project.

## 3. MTProto client libraries (Telethon, Pyrogram/Kurigram)

These speak Telegram's native protocol directly and can log in either as a **bot** (with a bot token — legitimate, ToS-safe) or as a **user account** (a "userbot").

- **Bigger files:** up/download up to **2 GB** (4 GB for Premium accounts) without self-hosting anything.
- **Vs Bot API:** access to APIs bots can't reach (full history reading as a user, joining arbitrary chats, richer typing events), no Bot API middleman, but also: you manage sessions/keys, need `api_id`/`api_hash`, and the surface is far larger and less documented.
- **Userbot ToS risk:** automating a *user* account for a public service violates Telegram ToS in spirit and frequently triggers **account bans**, especially on fresh accounts/VoIP numbers. A BBS serving strangers from a userbot is asking for a ban. **Do not build on userbots.**
- Using MTProto libs *with a bot token* is legitimate and mainly buys you the 2 GB file limit — a niche win here.

## 4. Brief mentions

- **tdlib** — Telegram's official C++ client library (Python via wrappers like `python-telegram` / pytdbot). Heavyweight; same userbot caveats; overkill for this project.
- **Telegram Business** — lets bots act on behalf of business accounts (auto-replies in the owner's DMs). Not relevant to a BBS.
- **Inline mode** — `@yourbot query` in any chat returns pickable results. Cute for "share a BBS post into another chat", not a UI foundation.
- **t.me deep links** — `t.me/yourbot?start=<payload>` (64-char payload) gives you shareable links that land users on a specific BBS screen (board, thread, invite). Cheap and very useful.

## 5. Python library landscape (July 2026)

| Library | Status | Notes |
|---|---|---|
| **python-telegram-bot (PTB)** | **v22.8 (2026-06)**, very active | Fully async since v20; `Application`/handlers, built-in `ConversationHandler` (state machines!), `JobQueue`, persistence layer. Best docs in the ecosystem. |
| **aiogram 3.x** | **v3.30 (2026-07)**, very active | Async-first, Router/middleware architecture, FSM with pluggable storage, `aiogram_dialog` add-on purpose-built for stateful menu screens. Slightly steeper curve. |
| **Telethon** | v1.44 (2026-06); v1 in **maintenance mode**, main repo archived Feb 2026, v2 long in alpha | MTProto. Fine, but not where you want a new project's foundation. |
| **Pyrogram** | **Abandoned** upstream | Use forks: **Kurigram** (active, drop-in) or PyroTGFork. |

**Best fit for a stateful menu-driven bot:** **python-telegram-bot** (ConversationHandler + persistence + docs) or **aiogram 3 + aiogram_dialog**. Either is a sound choice; PTB has the gentler learning curve, aiogram_dialog maps almost 1:1 onto "screens with buttons". Tie-breaker: pick PTB unless you already like aiogram's style.

## 6. BBS-specific UI craft

- **One edited "screen" vs. new messages:** keep a single pinned-in-practice message per user session and `editMessageText` it on every navigation — no scrollback spam, feels like a terminal. Send *new* messages only for events that deserve history (new mail notification, sysop broadcast). Handle `Message is not modified` errors (edit with identical content throws 400).
- **4096-char budget:** a screen of 40 cols × 20 rows plus HTML tags fits comfortably; still, truncate/paginate long post bodies.
- **Monospace width on mobile:** inside `<pre>`, phones realistically show **~30–40 characters per line** before wrapping (depends on device, font-size setting, portrait vs landscape). Design the "terminal" for **32–38 columns**, not 80. Desktop clients show far more — design for the phone floor.
- **callback_data ≤ 64 bytes:** encode navigation as compact tokens (`b:12:p3` = board 12, page 3), or store an id into SQLite and pass just the key. Never JSON-encode state into callback_data.
- **Box-drawing vs emoji:** box-drawing chars (`─ │ ┌ ┐ └ ┘ ├ ┤`) are monospaced inside `<pre>` and render reliably — perfect for frames. **Emoji are proportional/double-width and break column alignment inside `<pre>`** — keep emoji out of ASCII layouts, use them only in button labels. Avoid mixing full-width CJK punctuation. Stick to ASCII + box-drawing + block elements (`░▒▓█`) for the retro look.
- **Local security posture:** long polling = **no open ports, no public IP, no TLS cert, no reverse proxy** — the box only makes outbound HTTPS calls. Keep the bot token out of git (env var / `.env` with tight perms; rotate via @BotFather if leaked — the token is full control of the bot). Store all state in **SQLite** locally (WAL mode; it easily handles a BBS's write rate); back up the single DB file. Validate/limit user input lengths server-side; escape user text before embedding in HTML parse mode (`html.escape`).

## 7. Recommendation

**Architecture: Bot API + long polling + edited `<pre>` screens + inline keyboards + SQLite.**

1. **Transport:** official Bot API via **long polling** — zero inbound exposure, ideal for local hosting.
2. **Framework:** **python-telegram-bot v22** (async), using `ConversationHandler`/callback routing for the menu state machine. (aiogram 3 + aiogram_dialog is the equally valid alternative.)
3. **UI:** one session "screen" message per user, redrawn with `editMessageText`, content in `<pre>` (HTML parse mode), **~36-column** ASCII/box-drawing layout, navigation via **inline keyboards** (compact `callback_data` tokens), `ForceReply` for free-text entry (post bodies, mail).
4. **Storage:** **SQLite** (users, boards, threads, posts, mail, sessions), file areas as local files re-shared by cached `file_id`.
5. **Throttling:** debounce redraws to ≤1 edit/s per chat; queue sysop broadcasts under the ~30 msg/s global cap.
6. **Explicitly rejected:** userbots (ban risk), webhooks (open ports), Mini App as foundation (needs public HTTPS).
7. **Future enhancements:** a **Mini App** "graphics terminal" (real 80-col CRT rendering, WebSocket realtime) once you're willing to expose an HTTPS endpoint; self-hosted `telegram-bot-api` if file areas ever need >20/50 MB; `t.me/bot?start=` deep links for invites and thread permalinks from day one (they're free).

This is the classic, proven stack for exactly this genre of bot, and every element degrades gracefully: nothing in it locks you out of the Mini App upgrade later.
