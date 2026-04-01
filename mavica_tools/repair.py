"""Partial JPEG repair tool for Mavica images.

Attempts to salvage readable pixels from truncated or partially corrupt JPEGs.
Outputs repaired images as PNG to avoid re-encoding artifacts.
"""

import argparse
import os
import sys

from mavica_tools.utils import gather_jpegs


def _find_411_file(jpeg_path: str) -> str | None:
    """Find a matching .411 thumbnail for a JPEG file.

    Mavica stores thumbnails with the same base name: MVC-001.JPG → MVC-001.411
    """
    base, _ = os.path.splitext(jpeg_path)
    for ext in (".411", ".411"):
        candidate = base + ext
        if os.path.isfile(candidate):
            return candidate
    # Also check case-insensitive
    d = os.path.dirname(jpeg_path) or "."
    base_name = os.path.splitext(os.path.basename(jpeg_path))[0].upper()
    try:
        for f in os.listdir(d):
            if f.upper() == base_name + ".411":
                return os.path.join(d, f)
    except OSError:
        pass
    return None


def _composite_with_411(repaired_img, thumb_411_path):
    """Fill missing/gray areas of a partially recovered JPEG using the .411 thumbnail.

    Upscales the 64x48 thumbnail to match the repaired image size,
    then blends it into regions that are solid gray (unrecovered).
    """
    from PIL import Image, ImageFilter
    from mavica_tools.thumb411 import decode_411_to_image

    try:
        thumb = decode_411_to_image(thumb_411_path)
    except Exception:
        return repaired_img, False

    w, h = repaired_img.size
    thumb_up = thumb.resize((w, h), resample=Image.LANCZOS)

    # Detect gray fill regions (Pillow fills truncated areas with gray #808080)
    pixels = repaired_img.load()
    thumb_pixels = thumb_up.load()
    result = repaired_img.copy()
    result_pixels = result.load()

    # Scan rows from bottom — find where the gray fill starts
    gray_start_row = h
    for y in range(h - 1, -1, -1):
        row_is_gray = True
        for x in range(0, w, 8):  # sample every 8th pixel
            r, g, b = pixels[x, y][:3]
            if not (120 <= r <= 136 and 120 <= g <= 136 and 120 <= b <= 136):
                row_is_gray = False
                break
        if not row_is_gray:
            gray_start_row = y + 1
            break

    if gray_start_row >= h:
        # No gray fill detected — nothing to composite
        return repaired_img, False

    # Blend zone: 8 rows of gradient transition
    blend_rows = min(8, gray_start_row)
    blend_start = gray_start_row - blend_rows

    for y in range(blend_start, h):
        for x in range(w):
            if y < gray_start_row:
                # Gradient blend zone
                alpha = (y - blend_start) / blend_rows
                or_, og, ob = pixels[x, y][:3]
                tr, tg, tb = thumb_pixels[x, y][:3]
                result_pixels[x, y] = (
                    int(or_ * (1 - alpha) + tr * alpha),
                    int(og * (1 - alpha) + tg * alpha),
                    int(ob * (1 - alpha) + tb * alpha),
                )
            else:
                # Fully in the gray zone — use thumbnail
                result_pixels[x, y] = thumb_pixels[x, y][:3]

    return result, True


def repair_jpeg(input_path, output_path=None, use_411=False):
    """Attempt to repair a corrupt/truncated JPEG.

    Strategy:
    1. Try loading with Pillow's truncated image support
    2. If that fails, try stripping trailing garbage and reloading
    3. If that fails, try finding and extracting the valid JPEG portion
    4. If use_411=True, composite with .411 thumbnail to fill missing areas

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
        # Last resort: if .411 exists, use it as a fallback
        if use_411:
            thumb_path = _find_411_file(input_path)
            if thumb_path:
                try:
                    from mavica_tools.thumb411 import decode_411_to_image
                    thumb = decode_411_to_image(thumb_path)
                    # Upscale to 640x480 (common Mavica resolution)
                    result = thumb.resize((640, 480), resample=Image.LANCZOS)
                    result.save(output_path, "PNG")
                    return True, output_path, (
                        f"Recovered from .411 thumbnail only (64x48 → 640x480)"
                    )
                except Exception:
                    pass
        return False, None, "Not a JPEG file (missing SOI marker)"

    from io import BytesIO
    repaired_img = None
    repair_msg = ""

    # Strategy 1: Pillow with truncated image support
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    try:
        img = Image.open(BytesIO(data))
        img.load()
        repaired_img = img
        repair_msg = f"Repaired ({img.width}x{img.height}) — loaded with truncation tolerance"
    except Exception:
        pass

    # Strategy 2: Find zero-byte runs (sector failures)
    if repaired_img is None:
        zero_runs = []
        run_start = None
        run_length = 0
        for i in range(len(data)):
            if data[i] == 0:
                if run_length == 0:
                    run_start = i
                run_length += 1
            else:
                if run_length >= 512 and run_start is not None:
                    zero_runs.append(run_start)
                run_length = 0
                run_start = None
        if run_length >= 512 and run_start is not None:
            zero_runs.append(run_start)

        for zero_run_start in zero_runs:
            if zero_run_start < 100:
                continue
            truncated = data[:zero_run_start]
            if truncated[-2:] != b"\xff\xd9":
                truncated += b"\xff\xd9"
            try:
                img = Image.open(BytesIO(truncated))
                img.load()
                repaired_img = img
                pct = 100 * zero_run_start / len(data)
                repair_msg = (
                    f"Repaired ({img.width}x{img.height}) — "
                    f"truncated at {pct:.0f}% (sector failure at byte {zero_run_start})"
                )
                break
            except Exception:
                continue

    # Strategy 3: Progressive tail trimming
    if repaired_img is None:
        for trim in range(512, min(len(data), 50 * 1024), 512):
            candidate = data[:-trim]
            if len(candidate) < 1024:
                break
            if candidate[-2:] != b"\xff\xd9":
                candidate += b"\xff\xd9"
            try:
                img = Image.open(BytesIO(candidate))
                img.load()
                repaired_img = img
                pct = 100 * (len(data) - trim) / len(data)
                repair_msg = (
                    f"Repaired ({img.width}x{img.height}) — "
                    f"trimmed {trim} bytes from end ({pct:.0f}% of original)"
                )
                break
            except Exception:
                continue

    # No repair strategy worked
    if repaired_img is None:
        # Last resort: .411 thumbnail fallback
        if use_411:
            thumb_path = _find_411_file(input_path)
            if thumb_path:
                try:
                    from mavica_tools.thumb411 import decode_411_to_image
                    thumb = decode_411_to_image(thumb_path)
                    result = thumb.resize((640, 480), resample=Image.LANCZOS)
                    result.save(output_path, "PNG")
                    return True, output_path, (
                        "Recovered from .411 thumbnail only (64x48 \u2192 640x480)"
                    )
                except Exception:
                    pass
        return False, None, "Could not repair — file may be too corrupt for pixel recovery"

    # Strategy 4 (optional): Composite with .411 thumbnail to fill gray areas
    if use_411:
        thumb_path = _find_411_file(input_path)
        if thumb_path:
            composited, did_fill = _composite_with_411(repaired_img, thumb_path)
            if did_fill:
                composited.save(output_path, "PNG")
                return True, output_path, repair_msg + " + .411 fill"

    repaired_img.save(output_path, "PNG")
    return True, output_path, repair_msg


def repair_files(paths, output_dir=None, use_411=False):
    """Repair multiple JPEG files."""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    from mavica_tools.utils import print_progress
    import time

    success_count = 0
    fail_count = 0
    start = time.time()
    total = len(paths)

    for i, path in enumerate(paths):
        name = os.path.basename(path)

        if output_dir:
            base, _ = os.path.splitext(name)
            out_path = os.path.join(output_dir, base + "_repaired.png")
        else:
            out_path = None

        ok, out, msg = repair_jpeg(path, out_path, use_411=use_411)
        if ok:
            success_count += 1
            print(f"  FIXED {name} -> {os.path.basename(out)}")
            print(f"         {msg}")
        else:
            fail_count += 1
            print(f"  FAIL  {name}")
            print(f"         {msg}")
        if total > 3:
            print_progress(i + 1, total, start, "Repairing")

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
