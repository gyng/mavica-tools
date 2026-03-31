"""Metadata stamper for recovered Mavica JPEGs.

Mavica cameras write bare JFIF JPEGs with no EXIF metadata.
This tool adds EXIF tags to recovered images:
  - Camera model (e.g., "Sony Mavica FD7")
  - Date/time (from file timestamp, FAT12 date, or manual entry)
  - Custom notes

Uses Pillow's EXIF support — no extra dependencies needed.
"""

import argparse
import glob
import os
import struct
import sys
from datetime import datetime
from io import BytesIO


# EXIF tag IDs
TAG_MAKE = 0x010F
TAG_MODEL = 0x0110
TAG_DATETIME = 0x0132
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME_DIGITIZED = 0x9004
TAG_IMAGE_DESCRIPTION = 0x010E
TAG_SOFTWARE = 0x0131
TAG_USER_COMMENT = 0x9286

# Common Mavica models
MAVICA_MODELS = {
    "fd5": "Sony Mavica MVC-FD5",
    "fd7": "Sony Mavica MVC-FD7",
    "fd51": "Sony Mavica MVC-FD51",
    "fd71": "Sony Mavica MVC-FD71",
    "fd73": "Sony Mavica MVC-FD73",
    "fd75": "Sony Mavica MVC-FD75",
    "fd83": "Sony Mavica MVC-FD83",
    "fd85": "Sony Mavica MVC-FD85",
    "fd87": "Sony Mavica MVC-FD87",
    "fd88": "Sony Mavica MVC-FD88",
    "fd90": "Sony Mavica MVC-FD90",
    "fd91": "Sony Mavica MVC-FD91",
    "fd92": "Sony Mavica MVC-FD92",
    "fd95": "Sony Mavica MVC-FD95",
    "fd97": "Sony Mavica MVC-FD97",
    "fd100": "Sony Mavica MVC-FD100",
    "fd200": "Sony Mavica MVC-FD200",
}


def stamp_jpeg(
    input_path: str,
    output_path: str = None,
    model: str = None,
    date: str = None,
    description: str = None,
    overwrite: bool = False,
) -> tuple[bool, str, str]:
    """Add EXIF metadata to a JPEG file.

    Args:
        input_path: Source JPEG file
        output_path: Output file (default: overwrite input or save alongside)
        model: Camera model string or shorthand (e.g., "fd7")
        date: Date string "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD" or "auto" (use file mtime)
        description: Image description / notes
        overwrite: If True, overwrite input file

    Returns:
        (success, output_path, message)
    """
    try:
        from PIL import Image
        from PIL.ExifTags import Base as ExifBase
    except ImportError:
        return False, None, "Pillow is required: pip install Pillow"

    if output_path is None:
        if overwrite:
            output_path = input_path
        else:
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_stamped{ext}"

    try:
        img = Image.open(input_path)
    except Exception as e:
        return False, None, f"Cannot open: {e}"

    # Get or create EXIF data
    try:
        exif = img.getexif()
    except Exception:
        exif = Image.Exif()

    # Resolve model shorthand
    if model:
        model_lower = model.lower().replace("mvc-", "").replace("mavica", "").strip()
        if model_lower in MAVICA_MODELS:
            full_model = MAVICA_MODELS[model_lower]
        else:
            full_model = model
        exif[TAG_MAKE] = "Sony"
        exif[TAG_MODEL] = full_model

    # Resolve date
    if date:
        if date.lower() == "auto":
            mtime = os.path.getmtime(input_path)
            dt = datetime.fromtimestamp(mtime)
            exif_date = dt.strftime("%Y:%m:%d %H:%M:%S")
        elif len(date) == 10:  # YYYY-MM-DD
            exif_date = date.replace("-", ":") + " 00:00:00"
        else:
            exif_date = date.replace("-", ":")

        exif[TAG_DATETIME] = exif_date
        exif[TAG_DATETIME_ORIGINAL] = exif_date
        exif[TAG_DATETIME_DIGITIZED] = exif_date

    if description:
        exif[TAG_IMAGE_DESCRIPTION] = description

    # Always stamp with our software tag
    exif[TAG_SOFTWARE] = "mavica-tools"

    try:
        img.save(output_path, "JPEG", exif=exif.tobytes())
        tags_added = []
        if model:
            tags_added.append(f"model={exif.get(TAG_MODEL, model)}")
        if date:
            tags_added.append(f"date={exif.get(TAG_DATETIME, date)}")
        if description:
            tags_added.append(f"desc={description[:30]}")

        return True, output_path, f"Stamped: {', '.join(tags_added)}"
    except Exception as e:
        return False, None, f"Save failed: {e}"


def stamp_files(
    paths: list[str],
    output_dir: str = None,
    model: str = None,
    date: str = None,
    description: str = None,
    overwrite: bool = False,
):
    """Stamp multiple JPEG files with metadata."""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    success = 0
    fail = 0

    for path in paths:
        name = os.path.basename(path)

        if output_dir:
            out_path = os.path.join(output_dir, name)
        else:
            out_path = None

        ok, result_path, msg = stamp_jpeg(
            path, out_path,
            model=model, date=date, description=description,
            overwrite=overwrite,
        )

        if ok:
            success += 1
            print(f"  OK   {name}: {msg}")
        else:
            fail += 1
            print(f"  FAIL {name}: {msg}")

    print(f"\nResults: {success} stamped, {fail} failed")


def main():
    parser = argparse.ArgumentParser(
        description="Add EXIF metadata to recovered Mavica JPEGs"
    )
    parser.add_argument("paths", nargs="+", help="JPEG files or directories")
    parser.add_argument("-o", "--output", help="Output directory (default: save alongside)")
    parser.add_argument(
        "-m", "--model",
        help="Camera model (e.g., 'fd7', 'fd88', or full name)",
    )
    parser.add_argument(
        "-d", "--date",
        help="Date: 'auto' (from file mtime), 'YYYY-MM-DD', or 'YYYY-MM-DD HH:MM:SS'",
    )
    parser.add_argument(
        "--description",
        help="Image description / notes",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite input files instead of creating new ones",
    )
    args = parser.parse_args()

    # Expand directories
    files = []
    for path in args.paths:
        if os.path.isdir(path):
            for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
                files.extend(glob.glob(os.path.join(path, ext)))
        else:
            files.append(path)

    if not files:
        print("No JPEG files found.")
        sys.exit(1)

    files.sort()
    print(f"Stamping {len(files)} file(s)...\n")

    stamp_files(
        files,
        output_dir=args.output,
        model=args.model,
        date=args.date,
        description=args.description,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
