"""Screen rendering: every BBS 'screen' is one HTML <pre> block."""

import html
import textwrap
import time

from . import art

WIDTH = art.WIDTH


def esc(s: str) -> str:
    return html.escape(str(s), quote=False)


def ts(t: int, with_time: bool = True) -> str:
    fmt = "%y-%m-%d %H:%M" if with_time else "%y-%m-%d"
    return time.strftime(fmt, time.localtime(t))


def wrap(body: str, width: int = WIDTH, prefix: str = "") -> list[str]:
    """Wrap user text to screen width, preserving blank lines."""
    out: list[str] = []
    for para in body.splitlines() or [""]:
        if not para.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(
            para, width - len(prefix),
            initial_indent=prefix, subsequent_indent=prefix,
            break_long_words=True) or [prefix])
    return out


def trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def screen(title: str, body: list[str], status: str = "",
           logo: bool = False) -> str:
    """Compose a full screen and return it as a <pre> HTML string."""
    lines: list[str] = []
    if logo:
        lines += art.LOGO
    lines.append(art.gradient_title(title))
    lines.append("")
    lines += body
    lines.append("")
    lines.append(art.bar())
    if status:
        lines.append(trunc(status, WIDTH))
    text = "\n".join(l[:WIDTH + 6] for l in lines)  # box chars may pad a bit
    return f"<pre>{esc(text)}</pre>"


def status_line(user) -> str:
    lvl = {255: "SYSOP", 100: "CO-SYS"}.get(user["level"], f"lvl {user['level']}")
    return f"{user['handle']} · {lvl} · call #{user['calls']}"
