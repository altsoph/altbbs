"""ASCII / ANSI-style art assets. 34 columns, CP437-flavoured, demoscene at heart."""

WIDTH = 34

# ── logo: "altBBS" in half-block style ──────────────────────────────────
LOGO = [
    "        █   █   ▛▀▀▄ ▛▀▀▄ ▄▀▀▀▄",
    "   ▄▀▀▄ █  ▀█▀  ▙▄▄▀ ▙▄▄▀ ▀▄▄  ",
    "   █▄▄█ █▄  █▄  ▌  ▐ ▌  ▐ ▄  ▝▌",
    "   ▄▄▄▄▄▄▄▄▄▄▄▄▄▙▄▄▀▄▙▄▄▀▄▝▄▄▄▀",
]

BAR = "░▒▓█▓▒░" * 5            # gradient bar, cut to width
THIN = "─" * WIDTH
DOTS = "·" * WIDTH

LOGOFF = [
    "",
    "      ▄▄▄ NO CARRIER ▄▄▄",
    "",
    "   ░▒▓ thanks for calling ▓▒░",
    "",
    "   the tower never sleeps.",
    "   your node is now free for",
    "   the next caller.",
    "",
    "   +++ATH0",
    "",
]

WELCOME_LOGIN = [
    "",
    "  to log in, choose a HANDLE",
    "  (2-16 chars: a-z 0-9 . _ -)",
    "",
]


def bar(width: int = WIDTH) -> str:
    return BAR[:width]


def gradient_title(text: str, width: int = WIDTH) -> str:
    """'▓▒░ TEXT ░▒▓' centered to width."""
    core = f"▓▒░ {text.upper()} ░▒▓"
    if len(core) >= width:
        return core[:width]
    return core.center(width)
