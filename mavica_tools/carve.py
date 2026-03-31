"""JPEG carver for Mavica floppy disk images.

Scans a raw disk image (or any binary file) for JPEG files and extracts them.
Works even when the FAT filesystem is damaged — searches for JPEG markers directly.

Mavica cameras write standard JFIF JPEGs, so we look for:
  - SOI marker: FF D8 FF
  - EOI marker: FF D9
"""

import argparse
import os
import struct
import sys


JPEG_SOI = b"\xff\xd8\xff"
JPEG_EOI = b"\xff\xd9"

# Mavica image size bounds (sanity check)
MIN_JPEG_SIZE = 1024         # 1KB — smallest plausible Mavica JPEG
MAX_JPEG_SIZE = 300 * 1024   # 300KB — largest plausible Mavica JPEG on a 1.44MB disk


def find_jpegs(data):
    """Find all JPEG images in raw binary data.

    Returns list of (offset, length) tuples.
    """
    results = []
    search_start = 0

    while True:
        # Find next SOI marker
        soi_pos = data.find(JPEG_SOI, search_start)
        if soi_pos == -1:
            break

        # Find the matching EOI marker
        # Look for the next SOI to bound our search — if another JPEG starts
        # before we find EOI, the current JPEG's EOI must be before that SOI.
        next_soi_pos = data.find(JPEG_SOI, soi_pos + 3)

        eoi_search_start = soi_pos + 3
        eoi_pos = -1

        while True:
            next_eoi = data.find(JPEG_EOI, eoi_search_start)
            if next_eoi == -1:
                break

            # If there's another JPEG starting before this EOI, stop here —
            # use the last EOI we found before that next SOI
            if next_soi_pos != -1 and next_eoi >= next_soi_pos:
                break

            eoi_pos = next_eoi
            eoi_search_start = next_eoi + 2

            # Check if we've gone past the max size
            length = (eoi_pos + 2) - soi_pos
            if length > MAX_JPEG_SIZE:
                # Back up to the previous EOI if there was one
                prev_eoi = data.rfind(JPEG_EOI, soi_pos + 3, next_eoi)
                if prev_eoi != -1:
                    eoi_pos = prev_eoi
                break

        if eoi_pos == -1:
            # No EOI found — truncated JPEG, extract what we have
            remaining = len(data) - soi_pos
            if remaining >= MIN_JPEG_SIZE:
                results.append((soi_pos, remaining, True))  # truncated=True
            search_start = soi_pos + 3
            continue

        length = (eoi_pos + 2) - soi_pos

        if length >= MIN_JPEG_SIZE:
            results.append((soi_pos, length, False))  # truncated=False

        search_start = soi_pos + 3

    # De-duplicate overlapping results (keep the longest span from each SOI)
    if not results:
        return results

    deduped = []
    results.sort(key=lambda r: r[0])
    for r in results:
        if deduped and r[0] < deduped[-1][0] + deduped[-1][1]:
            # Overlaps with previous — keep whichever is longer
            if r[1] > deduped[-1][1]:
                deduped[-1] = r
        else:
            deduped.append(r)

    return deduped


def carve_jpegs(image_path, output_dir):
    """Extract all JPEGs from a disk image."""
    os.makedirs(output_dir, exist_ok=True)

    with open(image_path, "rb") as f:
        data = f.read()

    print(f"Scanning {image_path} ({len(data)} bytes)...")
    jpegs = find_jpegs(data)

    if not jpegs:
        print("No JPEG images found.")
        return []

    print(f"Found {len(jpegs)} JPEG image(s):\n")

    extracted = []
    for i, (offset, length, truncated) in enumerate(jpegs):
        suffix = "_TRUNCATED" if truncated else ""
        filename = f"mavica_{i + 1:03d}{suffix}.jpg"
        filepath = os.path.join(output_dir, filename)

        jpeg_data = data[offset : offset + length]
        with open(filepath, "wb") as f:
            f.write(jpeg_data)

        status = "TRUNCATED" if truncated else "ok"
        print(f"  {filename}: {length:,} bytes at offset 0x{offset:06X} [{status}]")
        extracted.append(filepath)

    print(f"\n{len(extracted)} image(s) extracted to {output_dir}/")
    return extracted


def main():
    parser = argparse.ArgumentParser(
        description="Carve JPEG images from Mavica floppy disk images"
    )
    parser.add_argument("image", help="Disk image file (raw .img)")
    parser.add_argument(
        "-o", "--output", default="carved_images", help="Output directory"
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="Show carved images after extraction (from local output dir)",
    )
    args = parser.parse_args()

    extracted = carve_jpegs(args.image, args.output)

    if args.preview and extracted:
        print()
        from mavica_tools.terminal_image import show_images
        show_images(extracted, max_images=8)


if __name__ == "__main__":
    main()
