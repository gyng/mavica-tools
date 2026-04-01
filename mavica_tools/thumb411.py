"""Sony Mavica .411 thumbnail decoder.

.411 files are 64x48 pixel thumbnails stored on Mavica floppy disks as hidden
files alongside the full-size JPEGs. The format is a raw raster based on
CCIR 601 (YCbCr 4:1:1 subsampled), with no header or magic bytes.

Each file is exactly 4,608 bytes:
  64 * 48 * 1.5 = 4,608 bytes (12 bits per pixel from 4:1:1 subsampling)

Data layout per 4-pixel group (6 bytes):
  Y0, Y1, Y2, Y3, Cb, Cr

Reference: https://preservation.tylerthorsted.com/2023/06/16/whats-the-411/
"""

import os

THUMB_WIDTH = 64
THUMB_HEIGHT = 48
THUMB_SIZE = 4608  # 64 * 48 * 1.5


def decode_411(data: bytes) -> list[tuple[int, int, int]]:
    """Decode raw .411 YCbCr 4:1:1 data to a list of (R, G, B) tuples."""
    if len(data) != THUMB_SIZE:
        raise ValueError(f"Expected {THUMB_SIZE} bytes for a .411 thumbnail, got {len(data)}")

    pixels: list[tuple[int, int, int]] = []
    # Each 6-byte group encodes 4 pixels: Y0 Y1 Y2 Y3 Cb Cr
    for i in range(0, len(data), 6):
        y0, y1, y2, y3, cb, cr = data[i : i + 6]
        for y in (y0, y1, y2, y3):
            r = max(0, min(255, int(y + 1.402 * (cr - 128))))
            g = max(0, min(255, int(y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128))))
            b = max(0, min(255, int(y + 1.772 * (cb - 128))))
            pixels.append((r, g, b))
    return pixels


def decode_411_to_image(path: str):
    """Decode a .411 file and return a PIL Image (RGB, 64x48)."""
    from PIL import Image

    with open(path, "rb") as f:
        data = f.read()

    pixels = decode_411(data)
    img = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT))
    img.putdata(pixels)
    return img


def convert_411(
    src: str,
    dest: str | None = None,
    fmt: str = "PNG",
) -> str:
    """Convert a .411 thumbnail to a standard image format.

    Args:
        src: Path to the .411 file.
        dest: Output path. Defaults to the same name with a new extension.
        fmt: PIL image format (PNG, JPEG, BMP, etc.).

    Returns:
        The output file path.
    """
    if dest is None:
        base, _ = os.path.splitext(src)
        dest = f"{base}.{fmt.lower()}"

    img = decode_411_to_image(src)
    img.save(dest, fmt)
    return dest


def main():
    """CLI entry point: convert .411 thumbnails to PNG."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Decode Sony Mavica .411 thumbnails to standard images"
    )
    parser.add_argument(
        "files",
        nargs="+",
        help=".411 file(s) to convert",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="Output directory (default: same directory as input)",
    )
    parser.add_argument(
        "-f",
        "--format",
        default="png",
        help="Output format: png, jpg, bmp (default: png)",
    )
    args = parser.parse_args()

    converted = 0
    for src in args.files:
        if not os.path.isfile(src):
            print(f"  Skipping {src}: not found", file=sys.stderr)
            continue

        if args.output_dir:
            os.makedirs(args.output_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(src))[0]
            dest = os.path.join(args.output_dir, f"{base}.{args.format}")
        else:
            dest = None

        try:
            out = convert_411(src, dest, fmt=args.format.upper())
            print(f"  {src} → {out}")
            converted += 1
        except Exception as e:
            print(f"  {src}: {e}", file=sys.stderr)

    print(f"\n{converted} thumbnail(s) converted.")


if __name__ == "__main__":
    main()
