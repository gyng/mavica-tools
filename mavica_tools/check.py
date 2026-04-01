"""JPEG health checker for Mavica images.

Batch-checks JPEG files for corruption and reports status.
Detects: truncation, marker errors, premature EOF, and partial decode failures.
"""

import argparse
import os
import sys

from mavica_tools.utils import JPEG_EOI, gather_jpegs
from mavica_tools.utils import JPEG_SOI_SHORT as JPEG_SOI


def check_jpeg_structure(filepath):
    """Check a JPEG file for structural integrity.

    Returns a dict with:
      - valid: bool
      - issues: list of strings describing problems
      - size: file size in bytes
      - has_soi: starts with SOI marker
      - has_eoi: ends with EOI marker
      - pixel_test: whether Pillow can decode it (if available)
    """
    result = {
        "path": filepath,
        "valid": True,
        "issues": [],
        "size": 0,
        "has_soi": False,
        "has_eoi": False,
        "pixel_test": None,
        "dimensions": None,
    }

    try:
        size = os.path.getsize(filepath)
        result["size"] = size

        if size == 0:
            result["valid"] = False
            result["issues"].append("File is empty (0 bytes)")
            return result

        if size < 1024:
            result["issues"].append(f"Suspiciously small ({size} bytes)")

        with open(filepath, "rb") as f:
            header = f.read(3)
            if header[:2] != JPEG_SOI:
                result["valid"] = False
                result["issues"].append("Missing SOI marker (not a JPEG)")
                return result
            result["has_soi"] = True

            # Check for JFIF/Exif header
            if header[2:3] != b"\xff":
                result["issues"].append("Unusual byte after SOI (expected FF)")

            # Check EOI at end
            f.seek(-2, 2)
            tail = f.read(2)
            if tail == JPEG_EOI:
                result["has_eoi"] = True
            else:
                result["issues"].append("Missing EOI marker (file may be truncated)")

            # Scan for suspicious runs of zeros (common corruption pattern)
            f.seek(0)
            data = f.read()
            zero_run = 0
            max_zero_run = 0
            for byte in data:
                if byte == 0:
                    zero_run += 1
                    max_zero_run = max(max_zero_run, zero_run)
                else:
                    zero_run = 0

            if max_zero_run > 512:
                result["issues"].append(
                    f"Large zero-byte run ({max_zero_run} bytes) — likely sector read failure"
                )

    except OSError as e:
        result["valid"] = False
        result["issues"].append(f"Cannot read file: {e}")
        return result

    # Try Pillow decode
    try:
        from PIL import Image, ImageFile

        ImageFile.LOAD_TRUNCATED_IMAGES = True
        with Image.open(filepath) as img:
            img.load()  # Force full decode
            result["dimensions"] = f"{img.width}x{img.height}"
            result["pixel_test"] = "pass"
    except ImportError:
        result["pixel_test"] = "skipped (Pillow not installed)"
    except Exception as e:
        result["pixel_test"] = f"FAIL: {e}"
        result["issues"].append(f"Pillow decode error: {e}")

    if result["issues"]:
        # Distinguish warnings from hard failures
        hard_issues = [
            i for i in result["issues"] if "Missing SOI" in i or "empty" in i.lower() or "FAIL" in i
        ]
        if hard_issues:
            result["valid"] = False

    return result


def check_files(paths, verbose=False):
    """Check multiple JPEG files and print a report."""
    import time

    from mavica_tools.utils import print_progress

    results = []
    start = time.time()
    total = len(paths)
    for i, path in enumerate(paths):
        result = check_jpeg_structure(path)
        results.append(result)
        if total > 3:
            print_progress(i + 1, total, start, "Checking")

    # Print results
    good = 0
    warn = 0
    bad = 0

    for r in results:
        name = os.path.basename(r["path"])
        size_kb = r["size"] / 1024

        if not r["issues"]:
            good += 1
            if verbose:
                dims = r["dimensions"] or "?"
                print(f"  OK   {name} ({size_kb:.0f}KB, {dims})")
        elif r["valid"]:
            warn += 1
            dims = r["dimensions"] or "?"
            print(f"  WARN {name} ({size_kb:.0f}KB, {dims})")
            for issue in r["issues"]:
                print(f"         -> {issue}")
        else:
            bad += 1
            print(f"  BAD  {name} ({size_kb:.0f}KB)")
            for issue in r["issues"]:
                print(f"         -> {issue}")

    total = len(results)
    print(f"\nResults: {total} files checked")
    print(f"  OK:      {good}")
    print(f"  Warning: {warn}")
    print(f"  Bad:     {bad}")

    if warn > 0:
        print("\nFiles with warnings may be partially recoverable — try mavica-repair.")
    if bad > 0:
        print(
            "\nBad files may need disk-level recovery — try mavica-multipass on the original floppy."
        )

    return results


def main():
    parser = argparse.ArgumentParser(description="Check Mavica JPEG files for corruption")
    parser.add_argument(
        "paths",
        nargs="+",
        help="JPEG files or directories to check",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Show OK files too")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show thumbnails of bad/warning files (from local disk only)",
    )
    args = parser.parse_args()

    # Expand directories to JPEG files
    files = []
    for path in args.paths:
        files.extend(gather_jpegs(path))

    if not files:
        print("No JPEG files found.")
        sys.exit(1)

    files.sort()
    print(f"Checking {len(files)} file(s)...\n")
    results = check_files(files, verbose=args.verbose)

    if args.preview:
        bad_files = [r["path"] for r in results if r["issues"]]
        if bad_files:
            print("\nPreviews of damaged files:")
            from mavica_tools.terminal_image import show_images

            show_images(bad_files, max_images=5)


if __name__ == "__main__":
    main()
