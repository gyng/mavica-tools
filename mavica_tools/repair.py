"""Partial JPEG repair tool for Mavica images.

Attempts to salvage readable pixels from truncated or partially corrupt JPEGs.
Outputs repaired images as PNG to avoid re-encoding artifacts.
"""

import argparse
import os
import sys

from mavica_tools.utils import gather_jpegs


def repair_jpeg(input_path, output_path=None):
    """Attempt to repair a corrupt/truncated JPEG.

    Strategy:
    1. Try loading with Pillow's truncated image support
    2. If that fails, try stripping trailing garbage and reloading
    3. If that fails, try finding and extracting the valid JPEG portion

    Returns (success: bool, output_path: str or None, message: str)
    """
    try:
        from PIL import Image, ImageFile
    except ImportError:
        return False, None, "Pillow is required: pip install Pillow"

    if output_path is None:
        base, _ = os.path.splitext(input_path)
        output_path = base + "_repaired.png"

    with open(input_path, "rb") as f:
        data = f.read()

    if len(data) < 3 or data[:2] != b"\xff\xd8":
        return False, None, "Not a JPEG file (missing SOI marker)"

    # Strategy 1: Pillow with truncated image support
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    try:
        from io import BytesIO
        img = Image.open(BytesIO(data))
        img.load()
        img.save(output_path, "PNG")
        return True, output_path, f"Repaired ({img.width}x{img.height}) — loaded with truncation tolerance"
    except Exception as e:
        pass  # Try next strategy

    # Strategy 2: Find valid JPEG portion by looking for last valid EOI
    # or truncate at the point where zeros start (sector failure)
    zero_run_start = None
    run_length = 0
    for i in range(len(data)):
        if data[i] == 0:
            if run_length == 0:
                zero_run_start = i
            run_length += 1
        else:
            run_length = 0
            zero_run_start = None

        # A run of 512+ zeros is almost certainly a failed sector
        if run_length >= 512 and zero_run_start is not None:
            # Truncate just before the zero run
            truncated = data[:zero_run_start]
            # Append EOI marker to make it a valid (truncated) JPEG
            if truncated[-2:] != b"\xff\xd9":
                truncated += b"\xff\xd9"

            try:
                img = Image.open(BytesIO(truncated))
                img.load()
                img.save(output_path, "PNG")
                pct = 100 * zero_run_start / len(data)
                return True, output_path, (
                    f"Repaired ({img.width}x{img.height}) — "
                    f"truncated at {pct:.0f}% (sector failure at byte {zero_run_start})"
                )
            except Exception:
                pass
            break

    # Strategy 3: Try progressively truncating from the end
    # (works when corruption is at the tail)
    for trim in range(0, min(len(data), 50 * 1024), 512):
        if trim == 0:
            continue
        candidate = data[:-trim]
        if len(candidate) < 1024:
            break
        # Ensure it ends with EOI
        if candidate[-2:] != b"\xff\xd9":
            candidate += b"\xff\xd9"
        try:
            img = Image.open(BytesIO(candidate))
            img.load()
            img.save(output_path, "PNG")
            pct = 100 * (len(data) - trim) / len(data)
            return True, output_path, (
                f"Repaired ({img.width}x{img.height}) — "
                f"trimmed {trim} bytes from end ({pct:.0f}% of original)"
            )
        except Exception:
            continue

    return False, None, "Could not repair — file may be too corrupt for pixel recovery"


def repair_files(paths, output_dir=None):
    """Repair multiple JPEG files."""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    success_count = 0
    fail_count = 0

    for path in paths:
        name = os.path.basename(path)

        if output_dir:
            base, _ = os.path.splitext(name)
            out_path = os.path.join(output_dir, base + "_repaired.png")
        else:
            out_path = None

        ok, out, msg = repair_jpeg(path, out_path)
        if ok:
            success_count += 1
            print(f"  FIXED {name} -> {os.path.basename(out)}")
            print(f"         {msg}")
        else:
            fail_count += 1
            print(f"  FAIL  {name}")
            print(f"         {msg}")

    print(f"\nRepair results: {success_count} fixed, {fail_count} failed")


def main():
    parser = argparse.ArgumentParser(
        description="Repair corrupt/truncated Mavica JPEG files"
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="JPEG files or directories to repair",
    )
    parser.add_argument(
        "-o", "--output", default=None, help="Output directory (default: alongside originals)"
    )
    args = parser.parse_args()

    files = []
    for path in args.paths:
        files.extend(gather_jpegs(path))

    if not files:
        print("No JPEG files found.")
        sys.exit(1)

    files.sort()
    print(f"Attempting to repair {len(files)} file(s)...\n")
    repair_files(files, args.output)


if __name__ == "__main__":
    main()
