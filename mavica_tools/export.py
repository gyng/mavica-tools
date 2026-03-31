"""Photo export tool for recovered Mavica images.

Organize, rename, resize, watermark, and create contact sheets
from recovered Mavica JPEGs.
"""

import argparse
import glob as globmod
import math
import os
import re
import sys

from mavica_tools.utils import get_photo_date


def organize_path(filepath: str, scheme: str, base_dir: str) -> str:
    """Determine output path based on organization scheme.

    Schemes:
      - "flat": all files in base_dir
      - "date": base_dir/YYYY/MM-DD/
      - "year": base_dir/YYYY/
    """
    name = os.path.basename(filepath)

    if scheme == "flat":
        return os.path.join(base_dir, name)
    elif scheme in ("date", "year"):
        date_str = get_photo_date(filepath)
        if date_str and len(date_str) >= 10:
            year = date_str[:4]
            month_day = date_str[5:10]
            if scheme == "date":
                return os.path.join(base_dir, year, month_day, name)
            else:
                return os.path.join(base_dir, year, name)

    return os.path.join(base_dir, name)


def rename_file(original_name: str, index: int, template: str) -> str:
    """Apply a rename template.

    Template variables:
      {n} or {n:03d} — sequential number
      {name} — original filename without extension
      {ext} — original extension
    """
    base, ext = os.path.splitext(original_name)
    ext = ext.lstrip(".")

    # Handle format specs like {n:03d}
    result = template
    # Replace {n:FORMAT} patterns
    result = re.sub(r'\{n:([^}]+)\}', lambda m: format(index, m.group(1)), result)
    result = result.replace("{n}", str(index))
    result = result.replace("{name}", base)
    result = result.replace("{ext}", ext)

    # Add extension if not present
    if not os.path.splitext(result)[1]:
        result += f".{ext}"

    return result


def apply_watermark(img, text: str, position: str = "bottom-right"):
    """Apply a retro date-stamp watermark to an image.

    Mimics the amber-on-black date imprint from 90s cameras.
    Returns a modified copy.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = img.copy()
    draw = ImageDraw.Draw(img)

    # Use a small built-in font
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 14)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("C:\\Windows\\Fonts\\consola.ttf", 14)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Measure text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    padding = 4
    bar_w = text_w + padding * 2
    bar_h = text_h + padding * 2

    # Position
    if position == "bottom-right":
        x = img.width - bar_w - 8
        y = img.height - bar_h - 8
    elif position == "bottom-left":
        x = 8
        y = img.height - bar_h - 8
    elif position == "top-right":
        x = img.width - bar_w - 8
        y = 8
    else:  # top-left
        x = 8
        y = 8

    # Draw black bar with amber text
    draw.rectangle([x, y, x + bar_w, y + bar_h], fill=(0, 0, 0))
    draw.text((x + padding, y + padding), text, fill=(255, 170, 0), font=font)

    return img


def add_border(img, caption: str = "", border_size: int = 20):
    """Add a retro black border with optional caption underneath."""
    from PIL import Image, ImageDraw, ImageFont

    caption_h = 24 if caption else 0
    new_w = img.width + border_size * 2
    new_h = img.height + border_size * 2 + caption_h

    bordered = Image.new("RGB", (new_w, new_h), (0, 0, 0))
    bordered.paste(img, (border_size, border_size))

    if caption:
        draw = ImageDraw.Draw(bordered)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 12)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("C:\\Windows\\Fonts\\consola.ttf", 12)
            except (OSError, IOError):
                font = ImageFont.load_default()

        draw.text(
            (border_size, img.height + border_size + 4),
            caption,
            fill=(180, 180, 180),
            font=font,
        )

    return bordered


def make_contact_sheet(
    image_paths: list[str],
    output_path: str,
    columns: int = 4,
    thumb_size: tuple[int, int] = (160, 120),
    show_names: bool = True,
    title: str = None,
) -> str:
    """Generate a contact sheet (grid of thumbnails).

    Returns the output path.
    """
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
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 14)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("C:\\Windows\\Fonts\\consola.ttf", 10)
            title_font = ImageFont.truetype("C:\\Windows\\Fonts\\consolab.ttf", 14)
        except (OSError, IOError):
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

            # Center the thumbnail in the cell
            paste_x = x + (cell_w - img.width) // 2
            paste_y = y + (thumb_size[1] - img.height) // 2
            sheet.paste(img, (paste_x, paste_y))
        except Exception:
            # Draw a placeholder for unreadable images
            draw.rectangle([x, y, x + cell_w, y + thumb_size[1]], fill=(40, 0, 0))
            draw.text((x + 4, y + thumb_size[1] // 2), "ERROR", fill=(255, 0, 0), font=font)

        if show_names:
            name = os.path.basename(path)
            if len(name) > 20:
                name = name[:17] + "..."
            draw.text((x, y + thumb_size[1] + 2), name, fill=(150, 150, 150), font=font)

    sheet.save(output_path, "JPEG", quality=90)
    return output_path


def export_images(
    input_dir: str,
    output_dir: str,
    organize: str = "flat",
    rename: str = "original",
    template: str = "mavica-{n:03d}",
    resize: tuple[int, int] | None = None,
    upscale: str = "nearest",
    watermark: str | None = None,
    border: bool = False,
    contact_sheet: bool = False,
    contact_columns: int = 4,
    title: str | None = None,
) -> dict:
    """Export recovered images with organization, renaming, and processing.

    Returns a summary dict.
    """
    from PIL import Image

    os.makedirs(output_dir, exist_ok=True)

    # Gather JPEG files
    files = []
    for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
        files.extend(globmod.glob(os.path.join(input_dir, ext)))
    # Also check for repaired PNGs
    for ext in ("*.png", "*.PNG"):
        files.extend(globmod.glob(os.path.join(input_dir, ext)))
    # Deduplicate (Windows is case-insensitive, so *.jpg and *.JPG match the same files)
    seen: set[str] = set()
    deduped: list[str] = []
    for f in files:
        key = os.path.normcase(f)
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    files = sorted(deduped)

    summary = {
        "total": len(files),
        "exported": 0,
        "errors": 0,
        "contact_sheet_path": None,
        "output_paths": [],
    }

    if not files:
        return summary

    resample = Image.Resampling.NEAREST if upscale == "nearest" else Image.Resampling.LANCZOS

    for i, filepath in enumerate(files):
        try:
            # Determine output name
            original_name = os.path.basename(filepath)
            if rename == "template":
                out_name = rename_file(original_name, i + 1, template)
            else:
                out_name = original_name

            # Determine output path
            out_path = organize_path(
                os.path.join(input_dir, out_name), organize, output_dir
            )
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            img = Image.open(filepath)

            # Resize
            if resize:
                img = img.resize(resize, resample)

            # Watermark
            if watermark:
                img = apply_watermark(img, watermark)

            # Border
            if border:
                img = add_border(img, caption=original_name)

            # Save
            if out_path.lower().endswith(".png"):
                img.save(out_path, "PNG")
            else:
                img.save(out_path, "JPEG", quality=92)

            summary["exported"] += 1
            summary["output_paths"].append(out_path)

        except Exception as e:
            summary["errors"] += 1
            print(f"  Error exporting {filepath}: {e}", file=sys.stderr)

    # Contact sheet
    if contact_sheet and summary["output_paths"]:
        sheet_path = os.path.join(output_dir, "contact_sheet.jpg")
        make_contact_sheet(
            summary["output_paths"],
            sheet_path,
            columns=contact_columns,
            title=title,
        )
        summary["contact_sheet_path"] = sheet_path

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Export recovered Mavica images with organization, renaming, and effects"
    )
    parser.add_argument("input_dir", help="Directory containing recovered images")
    parser.add_argument("-o", "--output", default="mavica_out/exported", help="Output directory")
    parser.add_argument(
        "--organize", choices=["flat", "date", "year"], default="flat",
        help="Folder structure (default: flat)",
    )
    parser.add_argument(
        "--rename", choices=["original", "template"], default="original",
        help="Naming scheme",
    )
    parser.add_argument("--template", default="mavica-{n:03d}", help="Rename template")
    parser.add_argument("--resize", help="Resize output (e.g., 1280x960)")
    parser.add_argument(
        "--upscale", choices=["nearest", "lanczos"], default="nearest",
        help="Upscale method (default: nearest — preserves pixel aesthetic)",
    )
    parser.add_argument("--watermark", help="Watermark text (e.g., 'Shot on Mavica FD7')")
    parser.add_argument("--border", action="store_true", help="Add retro black border")
    parser.add_argument("--contact-sheet", action="store_true", help="Generate contact sheet")
    parser.add_argument("--columns", type=int, default=4, help="Contact sheet columns")
    parser.add_argument("--title", help="Contact sheet title")

    args = parser.parse_args()

    resize = None
    if args.resize:
        parts = args.resize.lower().split("x")
        resize = (int(parts[0]), int(parts[1]))

    print(f"Exporting from {args.input_dir}...\n")

    summary = export_images(
        args.input_dir,
        args.output,
        organize=args.organize,
        rename=args.rename,
        template=args.template,
        resize=resize,
        upscale=args.upscale,
        watermark=args.watermark,
        border=args.border,
        contact_sheet=args.contact_sheet,
        contact_columns=args.columns,
        title=args.title,
    )

    print(f"Exported: {summary['exported']}/{summary['total']}")
    if summary["errors"]:
        print(f"Errors: {summary['errors']}")
    if summary["contact_sheet_path"]:
        print(f"Contact sheet: {summary['contact_sheet_path']}")


if __name__ == "__main__":
    main()
