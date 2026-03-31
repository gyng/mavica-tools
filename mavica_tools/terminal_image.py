"""Terminal image display — show images inline in supported terminals.

Detects the best available protocol and falls back gracefully:
  1. Kitty graphics protocol (kitty, WezTerm)
  2. iTerm2 inline images (iTerm2, WezTerm)
  3. Sixel graphics (xterm -ti vt340, foot, mlterm)
  4. Half-block Unicode (everything — the universal fallback)

Mavica JPEGs are 640x480, 20-50KB — tiny enough to inline anywhere.
"""

import base64
import io
import os
import sys


def detect_protocol() -> str:
    """Detect the best image protocol supported by the current terminal.

    Returns: 'kitty', 'iterm2', 'sixel', or 'halfblock'.
    """
    term = os.environ.get("TERM", "")
    term_program = os.environ.get("TERM_PROGRAM", "")
    lc_terminal = os.environ.get("LC_TERMINAL", "")

    # Kitty
    if "kitty" in term.lower() or term_program.lower() == "kitty":
        return "kitty"

    # WezTerm supports both kitty and iterm2
    if term_program.lower() == "wezterm":
        return "kitty"

    # iTerm2
    if term_program.lower() == "iterm2" or lc_terminal.lower() == "iterm2":
        return "iterm2"

    # Sixel — check TERM for known sixel-capable terminals
    sixel_terms = ("xterm", "foot", "mlterm", "contour", "ctx")
    if any(t in term.lower() for t in sixel_terms):
        return "sixel"

    # Check SIXEL env hint (some terminals set this)
    if os.environ.get("SIXEL_SUPPORT", ""):
        return "sixel"

    return "halfblock"


def _kitty_display(image_bytes: bytes, width: int | None = None) -> None:
    """Display image using Kitty graphics protocol."""
    b64 = base64.standard_b64encode(image_bytes).decode()

    # Kitty protocol: split into chunks of 4096
    chunk_size = 4096
    chunks = [b64[i:i + chunk_size] for i in range(0, len(b64), chunk_size)]

    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        m = 0 if is_last else 1
        if i == 0:
            # First chunk: include format and action
            cols = f",c={width}" if width else ""
            sys.stdout.write(f"\033_Ga=T,f=100,m={m}{cols};{chunk}\033\\")
        else:
            sys.stdout.write(f"\033_Gm={m};{chunk}\033\\")

    sys.stdout.write("\n")
    sys.stdout.flush()


def _iterm2_display(image_bytes: bytes, width: int | None = None) -> None:
    """Display image using iTerm2 inline image protocol."""
    b64 = base64.b64encode(image_bytes).decode()
    size = len(image_bytes)
    w = f"width={width};" if width else ""
    sys.stdout.write(f"\033]1337;File=inline=1;size={size};{w}:{b64}\007\n")
    sys.stdout.flush()


def _sixel_display(image_bytes: bytes, width: int | None = None) -> None:
    """Display image using Sixel graphics.

    Converts via Pillow since Sixel encoding is complex.
    Uses a simple quantized approach.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        if width:
            aspect = img.height / img.width
            img = img.resize((width, int(width * aspect)))

        # Limit size for terminal
        max_w = min(img.width, 800)
        if img.width > max_w:
            aspect = img.height / img.width
            img = img.resize((max_w, int(max_w * aspect)))

        # Convert to palette mode (Sixel is palette-based, max 256 colors)
        img = img.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
        palette = img.getpalette()
        pixels = list(img.getdata())
        w, h = img.size

        # Sixel header
        out = ["\033Pq"]

        # Define colors
        for i in range(256):
            if palette and i * 3 + 2 < len(palette):
                r = int(palette[i * 3] / 255 * 100)
                g = int(palette[i * 3 + 1] / 255 * 100)
                b = int(palette[i * 3 + 2] / 255 * 100)
                out.append(f"#{i};2;{r};{g};{b}")

        # Encode pixels in sixel bands (6 rows per band)
        for band_y in range(0, h, 6):
            used_colors = set()
            for y in range(band_y, min(band_y + 6, h)):
                for x in range(w):
                    used_colors.add(pixels[y * w + x])

            for color in sorted(used_colors):
                out.append(f"#{color}")
                for x in range(w):
                    sixel_val = 0
                    for bit in range(6):
                        y = band_y + bit
                        if y < h and pixels[y * w + x] == color:
                            sixel_val |= (1 << bit)
                    out.append(chr(63 + sixel_val))
                out.append("$")  # Carriage return
            out.append("-")  # New line

        out.append("\033\\")  # Sixel terminator

        sys.stdout.write("".join(out))
        sys.stdout.write("\n")
        sys.stdout.flush()

    except ImportError:
        _halfblock_display(image_bytes, width)


def _halfblock_display(image_bytes: bytes, width: int | None = None) -> None:
    """Display image using half-block Unicode characters.

    Works everywhere. Uses upper-half-block (U+2580) with fg/bg colors.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")

        # Target width
        target_w = width or min(60, os.get_terminal_size().columns - 4)
        aspect = img.height / img.width
        target_h = int(target_w * aspect)
        if target_h % 2 != 0:
            target_h += 1

        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        pixels = img.load()

        for y in range(0, target_h, 2):
            line = []
            for x in range(target_w):
                tr, tg, tb = pixels[x, y]
                if y + 1 < target_h:
                    br, bg, bb = pixels[x, y + 1]
                else:
                    br, bg, bb = 0, 0, 0
                line.append(
                    f"\033[38;2;{tr};{tg};{tb}m"
                    f"\033[48;2;{br};{bg};{bb}m"
                    "\u2580"
                )
            print("".join(line) + "\033[0m")

    except ImportError:
        print("[image preview requires Pillow]")


def show_image(
    path: str,
    width: int | None = None,
    protocol: str | None = None,
    label: bool = True,
) -> None:
    """Display an image file in the terminal.

    Args:
        path: Path to image file
        width: Display width in characters/pixels (protocol-dependent)
        protocol: Force a specific protocol, or None for auto-detect
        label: Show filename and dimensions above the image
    """
    if not os.path.isfile(path):
        return

    if label:
        try:
            from PIL import Image
            img = Image.open(path)
            w, h = img.size
            size_kb = os.path.getsize(path) / 1024
            print(f"  {os.path.basename(path)}  {w}x{h}  {size_kb:.0f}KB")
        except Exception:
            print(f"  {os.path.basename(path)}")

    with open(path, "rb") as f:
        image_bytes = f.read()

    proto = protocol or detect_protocol()

    if proto == "kitty":
        _kitty_display(image_bytes, width)
    elif proto == "iterm2":
        _iterm2_display(image_bytes, width)
    elif proto == "sixel":
        _sixel_display(image_bytes, width)
    else:
        _halfblock_display(image_bytes, width)


def show_images(
    paths: list[str],
    width: int | None = None,
    protocol: str | None = None,
    max_images: int = 10,
) -> None:
    """Display multiple images. Limits output to avoid flooding the terminal."""
    proto = protocol or detect_protocol()
    shown = 0

    for path in paths:
        if shown >= max_images:
            remaining = len(paths) - shown
            print(f"\n  ... and {remaining} more image(s)")
            break

        if path.lower().endswith((".jpg", ".jpeg", ".png")):
            show_image(path, width=width, protocol=proto)
            shown += 1
