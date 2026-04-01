"""Shared utilities for mavica-tools.

Common patterns extracted to reduce duplication across modules.
"""

import glob
import os
from datetime import datetime

MAVICA_EXTENSIONS = (".jpg", ".jpeg", ".411")

# Default root output directory — all tool outputs go under here
OUTPUT_DIR = "mavica_out"

# Subdirectory defaults per tool
OUTPUT_PHOTOS = os.path.join(OUTPUT_DIR, "photos")
OUTPUT_RECOVERY = os.path.join(OUTPUT_DIR, "recovery")
OUTPUT_DISK_IMAGES = os.path.join(OUTPUT_DIR, "disk_images")
OUTPUT_REPAIRED = os.path.join(OUTPUT_DIR, "repaired")
OUTPUT_EXTRACTED = os.path.join(OUTPUT_DIR, "extracted")


def gather_jpegs(path: str) -> list[str]:
    """Gather JPEG files from a path (directory, file, or glob pattern).

    Returns a sorted, deduplicated list of file paths.
    """
    files = []
    if os.path.isdir(path):
        for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
            files.extend(glob.glob(os.path.join(path, ext)))
    elif os.path.isfile(path):
        files.append(path)
    else:
        # Try as glob pattern
        files.extend(glob.glob(path))
        files = [f for f in files if f.lower().endswith((".jpg", ".jpeg"))]

    # Deduplicate (case-insensitive filesystems return the same file for *.jpg and *.JPG)
    seen: set[str] = set()
    deduped: list[str] = []
    for f in files:
        key = os.path.normcase(f)
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    deduped.sort()
    return deduped


def gather_mavica_files(path: str) -> list[str]:
    """Gather all Mavica files (JPEGs + .411 thumbnails) from a path.

    Returns a sorted, deduplicated list of file paths.
    Deduplication uses ``os.path.normcase`` so that case-insensitive
    filesystems (Windows) don't produce duplicates from mixed-case globs.
    """
    files = []
    if os.path.isdir(path):
        for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.411"):
            files.extend(glob.glob(os.path.join(path, ext)))
    elif os.path.isfile(path):
        files.append(path)
    else:
        files.extend(glob.glob(path))
        files = [f for f in files if f.lower().endswith(MAVICA_EXTENSIONS)]

    # Deduplicate (case-insensitive filesystems return the same file for *.jpg and *.JPG)
    seen: set[str] = set()
    deduped: list[str] = []
    for f in files:
        key = os.path.normcase(f)
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    deduped.sort()
    return deduped


def get_photo_timestamp(filepath: str, use_mtime: bool = False) -> datetime | None:
    """Get photo timestamp from EXIF or file mtime.

    Tries EXIF DateTimeOriginal first, then DateTime, then falls back to mtime.
    """
    if not use_mtime:
        try:
            from PIL import Image

            img = Image.open(filepath)
            exif = img.getexif()
            # DateTimeOriginal (0x9003) lives in the Exif sub-IFD (0x8769)
            exif_ifd = exif.get_ifd(0x8769)
            date_str = (
                exif_ifd.get(0x9003)  # DateTimeOriginal in Exif IFD
                or exif.get(0x9003)  # fallback: some encoders put it in IFD0
                or exif.get(0x0132)  # DateTime in IFD0
            )
            if date_str:
                return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass

    mtime = os.path.getmtime(filepath)
    return datetime.fromtimestamp(mtime)


def get_photo_date(filepath: str) -> str | None:
    """Get photo date as YYYY-MM-DD string."""
    ts = get_photo_timestamp(filepath)
    if ts:
        return ts.strftime("%Y-%m-%d")
    return None


import platform
import subprocess
import time


def open_directory(path: str) -> None:
    """Open a directory in the system file manager and bring to foreground."""
    system = platform.system()
    if system == "Windows":
        # explorer.exe always opens a new window in the foreground
        # os.startfile reuses existing windows and doesn't raise them
        subprocess.Popen(["explorer.exe", os.path.normpath(path)])
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def format_eta(start_time: float, current: int, total: int) -> str:
    """Format an ETA string like '1m 23s left' based on progress so far."""
    if current <= 0 or total <= 0:
        return ""
    elapsed = time.time() - start_time
    if elapsed <= 0:
        return ""
    rate = current / elapsed
    remaining = (total - current) / rate
    if remaining < 1:
        return "< 1s left"
    if remaining < 60:
        return f"{int(remaining)}s left"
    minutes = int(remaining // 60)
    seconds = int(remaining % 60)
    return f"{minutes}m {seconds:02d}s left"


def print_progress(current: int, total: int, start_time: float, label: str = "") -> None:
    """Print a progress line with ETA to stderr, overwriting the current line."""
    import sys

    pct = 100 * current / total if total else 0
    eta = format_eta(start_time, current, total)
    prefix = f"  {label} " if label else "  "
    print(
        f"\r{prefix}{current}/{total} ({pct:.0f}%) {eta}    ", end="", file=sys.stderr, flush=True
    )
    if current >= total:
        print(file=sys.stderr)  # newline when done


# JPEG marker constants
JPEG_SOI = b"\xff\xd8\xff"  # Start of Image (3-byte form, includes marker byte)
JPEG_SOI_SHORT = b"\xff\xd8"  # 2-byte SOI (for checking file headers)
JPEG_EOI = b"\xff\xd9"  # End of Image


def make_contact_sheet(
    image_paths: list[str],
    output_path: str,
    columns: int = 4,
    thumb_size: tuple[int, int] = (160, 120),
    show_names: bool = True,
    title: str | None = None,
) -> str:
    """Generate a contact sheet (grid of thumbnails). Returns the output path."""
    import math

    from PIL import Image, ImageDraw, ImageFont

    if not image_paths:
        return output_path

    rows = math.ceil(len(image_paths) / columns)
    name_h = 16 if show_names else 0
    cell_w = thumb_size[0]
    cell_h = thumb_size[1] + name_h
    margin = 4
    title_h = 30 if title else 0

    sheet_w = columns * (cell_w + margin) + margin
    sheet_h = rows * (cell_h + margin) + margin + title_h
    sheet = Image.new("RGB", (sheet_w, sheet_h), (10, 10, 10))
    draw = ImageDraw.Draw(sheet)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 10)
        title_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 14
        )
    except OSError:
        try:
            font = ImageFont.truetype("C:\\Windows\\Fonts\\consola.ttf", 10)
            title_font = ImageFont.truetype("C:\\Windows\\Fonts\\consolab.ttf", 14)
        except OSError:
            font = ImageFont.load_default()
            title_font = font

    if title:
        draw.text((margin, margin), title, fill=(51, 255, 51), font=title_font)

    for i, path in enumerate(image_paths):
        col = i % columns
        row = i // columns
        x = margin + col * (cell_w + margin)
        y = title_h + margin + row * (cell_h + margin)

        try:
            img = Image.open(path)
            img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
            paste_x = x + (cell_w - img.width) // 2
            paste_y = y + (thumb_size[1] - img.height) // 2
            sheet.paste(img, (paste_x, paste_y))
        except Exception:
            draw.rectangle([x, y, x + cell_w, y + thumb_size[1]], fill=(40, 0, 0))
            draw.text((x + 4, y + thumb_size[1] // 2), "ERROR", fill=(255, 0, 0), font=font)

        if show_names:
            name = os.path.basename(path)
            if len(name) > 20:
                name = name[:17] + "..."
            draw.text((x, y + thumb_size[1] + 2), name, fill=(150, 150, 150), font=font)

    sheet.save(output_path, "JPEG", quality=90)
    return output_path
