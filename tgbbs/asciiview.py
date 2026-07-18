"""ASCII image viewer -- images become terminal art, like nature intended.

Uses ascii-magic (which rides on Pillow) for the actual conversion.
"""

from io import BytesIO

from ascii_magic import AsciiArt
from PIL import Image

IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
MAX_BYTES = 20 * 1024 * 1024  # Bot API getFile limit


def is_image_name(name: str) -> bool:
    return name.lower().endswith(IMG_EXTS)


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
