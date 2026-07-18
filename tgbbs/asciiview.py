"""ASCII image viewer -- images become terminal art, like nature intended.

Uses ascii-magic (which rides on Pillow) for the actual conversion.
"""

from io import BytesIO

from ascii_magic import AsciiArt
from PIL import Image

IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
TEXT_EXTS = (".txt", ".nfo", ".diz", ".asc", ".ans", ".md", ".rst", ".log",
             ".csv", ".json", ".xml", ".ini", ".cfg", ".toml", ".yml",
             ".yaml", ".py", ".js", ".c", ".h", ".sh", ".bat", ".ps1",
             ".diff", ".patch")
MAX_BYTES = 20 * 1024 * 1024   # Bot API getFile limit
PREVIEW_BYTES = 65536          # decode at most this much for a preview


def is_image_name(name: str) -> bool:
    return name.lower().endswith(IMG_EXTS)


def is_text_name(name: str) -> bool:
    return name.lower().endswith(TEXT_EXTS)


def decode_text(data: bytes) -> str:
    """utf-8 first, then cp437 (the one true NFO codepage), then latin-1."""
    for enc in ("utf-8", "cp437"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def text_to_lines(data: bytes, width: int = 33, max_lines: int = 2000) -> list[str]:
    """Decode file bytes into display lines, wrapping long source lines."""
    import textwrap
    out: list[str] = []
    for raw in decode_text(data[:PREVIEW_BYTES]).splitlines():
        raw = raw.rstrip()
        if len(raw) <= width:
            out.append(raw)
        else:
            out += textwrap.wrap(raw, width, break_long_words=True,
                                 drop_whitespace=False)
        if len(out) >= max_lines:
            out.append("[...preview truncated...]")
            break
    return out


def image_to_ascii(data: bytes, cols: int = 33, max_lines: int = 42) -> list[str]:
    """Convert image bytes to ASCII lines that fit a phone screen."""
    img = Image.open(BytesIO(data))
    img.load()
    art = AsciiArt.from_pillow_image(img.convert("RGB"))
    lines = art.to_ascii(columns=cols, monochrome=True).splitlines()
    if len(lines) > max_lines:  # tall image: shrink until it fits
        cols = max(8, int(cols * max_lines / len(lines)))
        lines = art.to_ascii(columns=cols, monochrome=True).splitlines()
    return [l.rstrip() for l in lines]
