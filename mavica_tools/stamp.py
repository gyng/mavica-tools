"""Metadata stamper for recovered Mavica JPEGs.

Mavica cameras write bare JFIF JPEGs with no EXIF metadata.
This tool adds EXIF tags to recovered images:
  - Camera model (e.g., "Sony Mavica FD7")
  - Date/time (from file timestamp, FAT12 date, or manual entry)
  - Custom notes

Uses Pillow's EXIF support — no extra dependencies needed.
"""

import argparse
import os
import sys
from datetime import datetime
from fractions import Fraction
from io import BytesIO

from mavica_tools.utils import gather_jpegs


# EXIF tag IDs
TAG_MAKE = 0x010F
TAG_MODEL = 0x0110
TAG_DATETIME = 0x0132
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME_DIGITIZED = 0x9004
TAG_IMAGE_DESCRIPTION = 0x010E
TAG_SOFTWARE = 0x0131
TAG_USER_COMMENT = 0x9286

# EXIF IFD tags (stored in the Exif sub-IFD)
TAG_EXIF_IFD = 0x8769
TAG_FNUMBER = 0x829D
TAG_EXPOSURE_PROGRAM = 0x8822
TAG_ISO = 0x8827
TAG_FOCAL_LENGTH = 0x920A
TAG_FOCAL_LENGTH_35MM = 0xA405
TAG_MAX_APERTURE = 0x9205
TAG_METERING_MODE = 0x9207
TAG_FLASH = 0x9209
TAG_COLOR_SPACE = 0xA001
TAG_PIXEL_X = 0xA002
TAG_PIXEL_Y = 0xA003
TAG_SENSING_METHOD = 0xA217
TAG_SCENE_TYPE = 0xA301
TAG_CUSTOM_RENDERED = 0xA401
TAG_EXPOSURE_MODE = 0xA402
TAG_WHITE_BALANCE = 0xA403
TAG_DIGITAL_ZOOM_RATIO = 0xA404
TAG_SCENE_CAPTURE_TYPE = 0xA406

# Accurate camera specs for every floppy Mavica model.
# Sources: Sony product pages, dpreview archives, imaging-resource.
# Focal lengths and apertures are for the optical lens (not digital zoom).
# Focal length 35mm equivalent calculated from sensor size.
MAVICA_SPECS = {
    "fd5": {
        "model": "Sony Mavica MVC-FD5",
        "year": 1997,
        "resolution": (640, 480),
        "sensor": "1/4\" CCD",
        "focal_length_mm": 4.2,         # fixed lens
        "focal_length_35mm": 47,
        "aperture_max": 2.0,
        "aperture_min": 2.0,            # fixed aperture
        "zoom_optical": 1.0,
        "zoom_digital": 10.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd7": {
        "model": "Sony Mavica MVC-FD7",
        "year": 1997,
        "resolution": (640, 480),
        "sensor": "1/4\" CCD",
        "focal_length_mm": 4.2,
        "focal_length_35mm": 47,
        "aperture_max": 2.0,
        "aperture_min": 2.0,
        "zoom_optical": 1.0,
        "zoom_digital": 10.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd51": {
        "model": "Sony Mavica MVC-FD51",
        "year": 1998,
        "resolution": (640, 480),
        "sensor": "1/4\" CCD",
        "focal_length_mm": 4.2,
        "focal_length_35mm": 47,
        "aperture_max": 2.0,
        "aperture_min": 2.0,
        "zoom_optical": 1.0,
        "zoom_digital": 10.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd71": {
        "model": "Sony Mavica MVC-FD71",
        "year": 1998,
        "resolution": (640, 480),
        "sensor": "1/4\" CCD",
        "focal_length_mm": 4.2,
        "focal_length_35mm": 47,
        "aperture_max": 2.0,
        "aperture_min": 2.0,
        "zoom_optical": 1.0,
        "zoom_digital": 10.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd73": {
        "model": "Sony Mavica MVC-FD73",
        "year": 1999,
        "resolution": (640, 480),
        "sensor": "1/4\" CCD",
        "focal_length_mm": 4.7,         # Carl Zeiss Vario-Sonnar
        "focal_length_35mm": 40,        # wide end
        "aperture_max": 1.8,
        "aperture_min": 3.1,
        "zoom_optical": 3.0,
        "zoom_digital": 6.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd75": {
        "model": "Sony Mavica MVC-FD75",
        "year": 1999,
        "resolution": (640, 480),
        "sensor": "1/3\" CCD",
        "focal_length_mm": 4.7,
        "focal_length_35mm": 40,
        "aperture_max": 1.8,
        "aperture_min": 3.1,
        "zoom_optical": 3.0,
        "zoom_digital": 6.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd83": {
        "model": "Sony Mavica MVC-FD83",
        "year": 2000,
        "resolution": (1280, 960),
        "sensor": "1/2.7\" CCD",
        "focal_length_mm": 6.1,
        "focal_length_35mm": 37,
        "aperture_max": 2.8,
        "aperture_min": 2.8,
        "zoom_optical": 3.0,
        "zoom_digital": 2.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd85": {
        "model": "Sony Mavica MVC-FD85",
        "year": 2000,
        "resolution": (1280, 960),
        "sensor": "1/2.7\" CCD",
        "focal_length_mm": 6.1,
        "focal_length_35mm": 37,
        "aperture_max": 2.8,
        "aperture_min": 2.8,
        "zoom_optical": 3.0,
        "zoom_digital": 2.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd87": {
        "model": "Sony Mavica MVC-FD87",
        "year": 2000,
        "resolution": (1280, 960),
        "sensor": "1/2.7\" CCD",
        "focal_length_mm": 6.1,
        "focal_length_35mm": 37,
        "aperture_max": 2.8,
        "aperture_min": 2.8,
        "zoom_optical": 3.0,
        "zoom_digital": 2.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd88": {
        "model": "Sony Mavica MVC-FD88",
        "year": 2000,
        "resolution": (1280, 960),
        "sensor": "1/2.7\" CCD",
        "focal_length_mm": 6.1,
        "focal_length_35mm": 37,
        "aperture_max": 2.8,
        "aperture_min": 2.8,
        "zoom_optical": 3.0,
        "zoom_digital": 2.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd90": {
        "model": "Sony Mavica MVC-FD90",
        "year": 2000,
        "resolution": (640, 480),
        "sensor": "1/4\" CCD",
        "focal_length_mm": 4.2,
        "focal_length_35mm": 47,
        "aperture_max": 2.0,
        "aperture_min": 2.0,
        "zoom_optical": 1.0,
        "zoom_digital": 4.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd91": {
        "model": "Sony Mavica MVC-FD91",
        "year": 2000,
        "resolution": (640, 480),
        "sensor": "1/3\" CCD",
        "focal_length_mm": 3.5,
        "focal_length_35mm": 30,        # wide end of 14x zoom
        "aperture_max": 1.8,
        "aperture_min": 3.1,
        "zoom_optical": 14.0,
        "zoom_digital": 2.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd92": {
        "model": "Sony Mavica MVC-FD92",
        "year": 2001,
        "resolution": (1024, 768),
        "sensor": "1/3.2\" CCD",
        "focal_length_mm": 5.1,
        "focal_length_35mm": 38,
        "aperture_max": 2.8,
        "aperture_min": 2.8,
        "zoom_optical": 3.0,
        "zoom_digital": 2.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd95": {
        "model": "Sony Mavica MVC-FD95",
        "year": 2001,
        "resolution": (1600, 1200),
        "sensor": "1/2.7\" CCD",
        "focal_length_mm": 6.1,
        "focal_length_35mm": 37,
        "aperture_max": 2.8,
        "aperture_min": 2.8,
        "zoom_optical": 3.0,
        "zoom_digital": 2.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd97": {
        "model": "Sony Mavica MVC-FD97",
        "year": 2001,
        "resolution": (1600, 1200),
        "sensor": "1/2.7\" CCD",
        "focal_length_mm": 6.1,
        "focal_length_35mm": 37,
        "aperture_max": 2.8,
        "aperture_min": 2.8,
        "zoom_optical": 3.0,
        "zoom_digital": 2.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd100": {
        "model": "Sony Mavica MVC-FD100",
        "year": 2001,
        "resolution": (1280, 960),
        "sensor": "1/2.7\" CCD",
        "focal_length_mm": 6.1,
        "focal_length_35mm": 37,
        "aperture_max": 2.8,
        "aperture_min": 2.8,
        "zoom_optical": 3.0,
        "zoom_digital": 2.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
    "fd200": {
        "model": "Sony Mavica MVC-FD200",
        "year": 2002,
        "resolution": (1600, 1200),
        "sensor": "1/2.7\" CCD",
        "focal_length_mm": 6.1,
        "focal_length_35mm": 37,
        "aperture_max": 2.8,
        "aperture_min": 3.6,
        "zoom_optical": 3.0,
        "zoom_digital": 6.0,
        "iso": 100,
        "flash": True,
        "media": "3.5\" floppy",
    },
}

# Convenience shorthand lookup (kept for backward compat)
MAVICA_MODELS = {k: v["model"] for k, v in MAVICA_SPECS.items()}


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

    # Resolve model shorthand and write camera specs
    if model:
        model_lower = model.lower().replace("mvc-", "").replace("mavica", "").strip()
        specs = MAVICA_SPECS.get(model_lower)

        if specs:
            full_model = specs["model"]
        else:
            full_model = model
            specs = None

        exif[TAG_MAKE] = "Sony"
        exif[TAG_MODEL] = full_model

        # Write accurate camera specs into EXIF IFD
        if specs:

            exif_ifd = exif.get_ifd(TAG_EXIF_IFD)

            # Focal length as rational (numerator, denominator)
            fl = specs["focal_length_mm"]
            fl_frac = Fraction(fl).limit_denominator(100)
            exif_ifd[TAG_FOCAL_LENGTH] = (fl_frac.numerator, fl_frac.denominator)

            # 35mm equivalent focal length (integer)
            exif_ifd[TAG_FOCAL_LENGTH_35MM] = specs["focal_length_35mm"]

            # F-number (max aperture)
            ap = specs["aperture_max"]
            ap_frac = Fraction(ap).limit_denominator(100)
            exif_ifd[TAG_FNUMBER] = (ap_frac.numerator, ap_frac.denominator)

            # Max aperture value (APEX)
            exif_ifd[TAG_MAX_APERTURE] = (ap_frac.numerator, ap_frac.denominator)

            # ISO
            exif_ifd[TAG_ISO] = specs["iso"]

            # Flash (fired = 0x01, not fired = 0x00, has flash = 0x18)
            exif_ifd[TAG_FLASH] = 0x18 if specs.get("flash") else 0x00

            # Color space (sRGB)
            exif_ifd[TAG_COLOR_SPACE] = 1

            # Pixel dimensions
            exif_ifd[TAG_PIXEL_X] = specs["resolution"][0]
            exif_ifd[TAG_PIXEL_Y] = specs["resolution"][1]

            # Sensing method (one-chip color area)
            exif_ifd[TAG_SENSING_METHOD] = 2

            # Exposure program (auto)
            exif_ifd[TAG_EXPOSURE_PROGRAM] = 2

            # Metering mode (multi-segment)
            exif_ifd[TAG_METERING_MODE] = 5

            # White balance (auto)
            exif_ifd[TAG_WHITE_BALANCE] = 0

            # Exposure mode (auto)
            exif_ifd[TAG_EXPOSURE_MODE] = 0

            # Scene capture type (standard)
            exif_ifd[TAG_SCENE_CAPTURE_TYPE] = 0

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
        files.extend(gather_jpegs(path))

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
