# Classic BBS Software Analysis

Research document for the TG_BBS project: a survey of classic and still-maintained BBS
software, selection of a primary reference model, and design takeaways for re-implementing
the BBS experience inside Telegram.

Researched: 2026-07-18. Sources: synchro.net + wiki, Wikipedia, project GitHub repos,
mysticbbs.com, wwivbbs.org, citadel.org, renegade.sourceforge.net / renegadebbs.info.

---

## 1. Landscape survey

### Synchronet
- **License:** GPLv2 (core), LGPL for support libraries (SMBLIB, CIOLIB, XPDEV, etc.). Open-sourced in 2000; genuinely FOSS.
- **Language:** C/C++ core with an embedded SpiderMonkey **JavaScript** engine; legacy Baja scripting language.
- **Maintenance:** Very active. Rob Swindell ("Digital Man") still leads; v3.20 series current (3.20b Jan 2025, 3.20d Win32 Mar 2025). Git repo at gitlab.synchro.net.
- **Architecture:** Multi-node, multi-threaded daemon bundling its own Telnet/SSH/RLogin, FTP, SMTP/POP3, HTTP, NNTP, IRC servers. Terminal server + JS services model. Runs on Windows, Linux, BSD.
- **Features:** Full message bases (JAM-era style, own SMB format), FidoNet echomail (SBBSecho) and native QWK networking (DOVE-Net), file areas with credits/ratios, DOS/Win/native door support (DOOR32, socket doors, DOSEMU on Linux), fully scriptable command shells and menus, web UI. Probably the most feature-complete BBS package alive.

### Mystic BBS
- **Language/License:** Free Pascal. **Closed source freeware** since v1.10 (a 1.10a30 source snapshot exists on GitHub, but current builds are proprietary). Single author (g00r00 / James Coyle).
- **Maintenance:** Slow but alive; last stable 1.12 A48 (Jan 2023), alphas since. Popular in the hobby scene (fsxNet).
- **Architecture/Features:** Self-contained binary for Win/Linux/macOS/RPi; excellent stock ANSI theming, built-in FidoNet tosser (MUTIL), MPL scripting language, doors, QWK. Very sysop-friendly, but the closed license disqualifies it as a code-level reference.

### ENiGMA½
- **License:** **BSD 2-Clause** — genuinely open source.
- **Language:** Node.js (JavaScript).
- **Maintenance:** Active-ish; NuSkooler (Bryan Ashby) + community, github.com/NuSkooler/enigma-bbs.
- **Architecture:** Modern single Node process; Telnet/SSH/WebSocket servers; SQLite storage; menus and theming driven entirely by HJSON config + MCI codes; message areas as "conferences > areas"; FTN echomail support; door support (including DOSBox); ACS (access condition strings) modeled on classic ARS.
- **Features:** Deliberate "modern re-implementation of classic concepts" — the closest existing analog to what TG_BBS is attempting, just targeting terminals instead of chat.

### WWIV
- **License:** **Apache 2.0** since going open source; active repo at github.com/wwivbbs/wwiv (v5.x).
- **Language:** C++ (originally BASIC then Pascal then C++ over its 1984+ history).
- **Notes:** Historically enormously influential (Telegard and Renegade descend from leaked WWIV source); own WWIVnet network. Maintained but smaller community than Synchronet.

### Citadel / Citadel-UX
- **License:** GPL (v2 historically, now GPLv3). Open source.
- **Language:** C.
- **Notes:** A different lineage: "room"-centric navigation (rooms > floors) instead of menu trees; evolved into a Linux groupware/email suite. Its room-based UX (join room, read new messages, goto next room with unread) is a genuinely interesting interaction model for a chat app.

### RemoteAccess / Renegade / Telegard era (DOS classics)
- **RemoteAccess (RA):** shareware, Pascal, DOS; abandoned (last 2.62 in 1990s); source never opened. Defined the QuickBBS/Hudson message base era and FidoNet sysop culture.
- **Renegade:** Turbo Pascal + asm, freeware; WWIV-derived via Telegard; source escaped in 2005; surprisingly still maintained (v1.40, Mar 2026, Renegade Dev Team). The archetype of the "ANSI-heavy, hotkey menu, door-game" 90s board.
- **Telegard, PCBoard, Wildcat!, MajorBBS/Worldgroup:** all effectively dead/proprietary; relevant only as feature vocabulary (PCBoard's PPEs = precursor of door/scripting plugins; MajorBBS = multi-line chat culture).

### Selection: Synchronet as primary reference
Criteria: popularity (largest live install base per Telnet BBS Guide), flexibility (everything is a replaceable JS module), and license (GPLv2 — verified genuinely open source with 25 years of public history). ENiGMA½ is the secondary reference: its BSD license is friendlier for borrowing code, and its config-driven menu/theme engine is the best modern blueprint. But Synchronet defines the canonical concept set, so it is the model to mirror.

---

## 2. Deep dive: Synchronet's core concepts

### 2.1 User system
- **Handle/alias culture:** users are known by an alias (handle); real name stored separately and usually hidden. Aliases are unique per board and are identity — mirror this 1:1.
- **Security levels:** integer 0–99. Stock convention: new users ~50, trusted users 60–80, co-sysop 90+, **sysop = 99**. Levels gate time/day, calls/day, and area access.
- **Flags/exemptions/restrictions:** four 26-bit flag sets (A–Z) for fine-grained grants; exemptions (e.g. exempt from ratios) and restrictions (e.g. can't post) as separate bitfields.
- **ARS (Access Requirement Strings):** boolean expressions like `LEVEL 60 AND FLAG A OR USER 1` attached to any sub-board, file area, door, or menu command. This single mechanism is the whole permission system — extremely worth re-implementing.
- **New-user flow:** connect → optional matrix/prelogin screen → "NEW" → questionnaire (alias, password, location, terminal caps) → optional sysop verification / feedback message → newuser level and default settings applied. Guest account convention for lurkers.
- **Sysop role:** user #1; sees waiting feedback ("You have mail waiting"), can edit users, read logs, and use sysop hotkeys from any node.

### 2.2 Message bases
- **Hierarchy:** message **groups** contain **sub-boards** (e.g. group "Local" → subs "General", "Chat"; group "DOVE-Net" → networked subs). Each sub has its own ARS for read/post.
- **Networked vs local:** subs can be linked to **FidoNet echomail** (echo tag per sub, tossed by SBBSecho) or **QWK networks** (DOVE-Net). The BBS is a node in a store-and-forward federation — messages written locally propagate out.
- **Threading:** messages carry `to`, `from`, `subject`, reply-linkage (reply-to id / FTN REPLY kludge); readers offer "read new since last scan" per sub (scan pointers per user per sub) — the *newscan* is the core reading loop.
- **Private mail:** local e-mail between users plus **netmail** (private FTN message to a user on another node). Distinct from public subs.

### 2.3 File areas
- **Hierarchy:** file **libraries** contain **directories**, each with ARS for list/download/upload.
- **Metadata:** each file has uploader, date, size, download count, and a description; on upload the archive is scanned and an embedded **FILE_ID.DIZ** (up to ~10 lines x 45 cols) auto-fills the extended description.
- **Economy:** upload/download **ratios** and a **credit** system (uploads and posts earn credits; downloads spend them); leech prevention as gameplay. Exemptions for favored users.
- **Protocols:** X/Y/ZMODEM historically; irrelevant to Telegram (native file transfer) but the *catalog + DIZ + credits* layer translates directly.

### 2.4 Menus, navigation, presentation
- **Command shell model:** navigation is a scriptable shell (Baja or JS) rendering an ANSI menu screen, then blocking on a **single-key hotkey** (`M` messages, `F` files, `X` externals/doors, `G` goodbye/logoff, `!` sysop menu). Menus form a shallow tree, 1 keystroke per hop.
- **Display files:** screens are `.asc`/`.ans`/`.msg` art files in a text directory, chosen per user terminal; **@-codes** (`@USER@`, `@BBS@`, `@TIMELEFT@`) interpolate live data into art. Mystic uses `|XX` pipe codes; ENiGMA uses MCI codes — same idea: art with template variables.
- **Theming:** swap the display-file set + shell = new look, no logic change. Random login art rotation is a scene tradition.
- **Pause/more prompts**, configurable per user; hot or "expert mode" (no menus, just prompts) for veterans.

### 2.5 Doors, social features, culture
- **Doors (external programs):** BBS drops a **drop file** (DOOR.SYS, DORINFO1.DEF, DOOR32.SYS) with user name/handle/level/time-left, hands over the I/O stream, and resumes when the door exits. Door games — LORD, TradeWars 2002, Usurper, Barren Realms Elite — with daily-turn mechanics and inter-BBS leagues were the killer feature.
- **Oneliners:** a rolling wall of single-line quips shown at logon (big in Mystic/ENiGMA culture; Synchronet's "auto-message" is the equivalent).
- **Last callers / who's online:** logon shows the last N callers (alias, location, actions); a node list shows who's on which node right now, with node-to-node messaging/paging and sysop chat.
- **BBS list culture:** every board kept a list of *other* boards (name, number/address, sysop) — mutual advertisement; also user polls/voting booths, logon bulletins, and "your stats" screens (calls, posts, uploads, time online).

### 2.6 Screen and art conventions
- **80x24/25 characters** is the canonical canvas (Telnet default; some art at 80xN scrolling). Everything — menus, FILE_ID.DIZ at 45 cols, message quoting at ~79 cols — assumes fixed-width.
- **CP437:** the IBM PC charset with box-drawing (`─│┌┐└┘═║╔╗╚╝`), shade blocks (`░▒▓█`) and half-blocks — the raw material of ANSI art. 16 foreground / 8 background ANSI colors, blink.
- **ANSI-art scene:** art groups **ACiD** and **iCE** (and Fire, Blocktronics today) produced monthly "artpacks" of BBS logon screens, menus and DIZ art; SAUCE metadata records artist/group. A board's identity *was* its art. Modern terminals: SyncTERM, NetRunner. This aesthetic — not just the features — is what a nostalgia project must reproduce.

---

## 3. Design takeaways for a Telegram BBS

Concrete mapping checklist, ordered roughly by build priority:

1. **Terminal = one edited message.** Render each "screen" as a single bot message in a `<pre>`/monospace block and **edit it in place** on navigation — that message is the terminal. No scrollback spam.
2. **Hotkeys = inline keyboard.** One-letter hotkey commands map to inline keyboard buttons (`[M]essages [F]iles [D]oors [G]oodbye`); callback data = the keystroke. Keep menus one-tap deep like the classics. Text input still accepted for "expert mode".
3. **Narrow canvas.** Mobile Telegram monospace fits roughly **30–36 chars**; design all art/menus to a fixed ~34-col grid (a "40-col mode" like C64/Atari boards had), not 80. Keep an 80-col render option for desktop.
4. **Character set.** Telegram is UTF-8: map CP437 box-drawing/shade blocks to their Unicode equivalents (`░▒▓█ ─│┌┐╔═╗` all exist). No ANSI colors in messages — substitute with emoji accents sparingly, or ship color art as rendered PNGs for logon screens.
5. **@-code templating.** Implement display "art files" as templates with `@USER@`-style substitutions; theming = swappable template packs. Steal SAUCE-style artist credits.
6. **User model:** unique **handle** chosen at first /start (new-user questionnaire flow), Telegram ID as the account key, **security level 0–99 + flags + ARS-style expressions** gating every area/door/menu item. User #1 = sysop; feedback-to-sysop command.
7. **Message bases:** groups → sub-boards, each a threaded forum inside the bot; per-user **scan pointers** and a `[N]ewscan` command that walks all subs showing unread — this loop is the product. Private "netmail" = bot-mediated user-to-user mail.
8. **Federation later:** design message storage with echomail-style export/import (even actual FTN gating via binkd is feasible) so multiple TG-BBS instances can network — the store-and-forward model fits bots well.
9. **File areas:** Telegram file uploads into libraries/directories with descriptions and FILE_ID.DIZ parsing from archives; download counters; optional credit/ratio economy as a game mechanic, not a real restriction.
10. **Doors as bot modules:** a door API (user context in, text I/O loop out) so mini-games (LORD-likes with daily turns) plug in; daily-turn mechanics suit async chat perfectly.
11. **Social glue:** oneliners wall, last-10-callers on logon, who's-online (recently active), voting booth, logon bulletins, user stats screen, and a BBS-list directory of other Telegram BBSes.
12. **Session feel:** keep artifacts like the logon sequence (art → bulletins → oneliners → last callers → menu), "time left" (fake or real quota), and a proper `[G]oodbye` logoff screen. The ritual is the nostalgia.

**Reference stack:** mirror **Synchronet's** concept model (ARS, groups/subs, libraries/dirs, shells, @-codes); borrow implementation ideas from **ENiGMA½** (BSD-2, config-driven menus/themes, ACS, SQLite persistence) since its license permits direct reuse; borrow *UX* ideas from **Citadel** (room-hopping with unread counts) for the newscan loop.
