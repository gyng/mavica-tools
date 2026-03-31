"""Shared utilities for mavica-tools.

Common patterns extracted to reduce duplication across modules.
"""

import glob
import os
from datetime import datetime


def gather_jpegs(path: str) -> list[str]:
    """Gather JPEG files from a path (directory, file, or glob pattern).

    Returns a sorted list of file paths.
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

    files.sort()
    return files


def get_photo_timestamp(filepath: str, use_mtime: bool = False) -> datetime | None:
    """Get photo timestamp from EXIF or file mtime.

    Tries EXIF DateTimeOriginal first, then DateTime, then falls back to mtime.
    """
    if not use_mtime:
        try:
            from PIL import Image

            img = Image.open(filepath)
            exif = img.getexif()
            date_str = exif.get(0x9003) or exif.get(0x0132)  # DateTimeOriginal or DateTime
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


# JPEG marker constants
JPEG_SOI = b"\xff\xd8\xff"  # Start of Image (3-byte form, includes marker byte)
JPEG_SOI_SHORT = b"\xff\xd8"  # 2-byte SOI (for checking file headers)
JPEG_EOI = b"\xff\xd9"  # End of Image
