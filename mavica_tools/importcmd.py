"""Quick import command — photographer's one-liner.

Copies photos from a mounted floppy or disk image, tags with camera info,
and optionally creates a contact sheet. Designed for daily use.

    mavica import /mnt/floppy -m fd7
    mavica import E:\\ -m fd88 --contact-sheet
    mavica import disk.img -m fd7 -o photos/ --contact-sheet
"""

import argparse
import os
import shutil
import sys

from mavica_tools.utils import gather_mavica_files


def quick_import(
    source: str,
    output_dir: str = "photos",
    model: str | None = None,
    contact_sheet: bool = False,
) -> dict:
    """Import photos from a floppy source.

    Handles: mounted drives, directories, and disk images.
    Returns summary dict.
    """
    os.makedirs(output_dir, exist_ok=True)
    imported = []

    if os.path.isdir(source):
        # Mounted floppy / directory — copy JPEGs and .411 thumbnails
        files = gather_mavica_files(source)
        failed = 0
        import time

        from mavica_tools.utils import print_progress

        total = len(files)
        start = time.time()
        for file_idx, src in enumerate(files):
            name = os.path.basename(src)
            dest = os.path.join(output_dir, name)
            # Avoid clobbering
            if os.path.exists(dest):
                base, ext = os.path.splitext(name)
                i = 1
                while os.path.exists(dest):
                    dest = os.path.join(output_dir, f"{base}_{i}{ext}")
                    i += 1
            try:
                shutil.copy2(src, dest)
            except OSError as e:
                failed += 1
                print(f"  Failed to read {name}: {e}", file=sys.stderr)
                continue
            imported.append(dest)
            if total > 3:
                print_progress(file_idx + 1, total, start, "Copying")
        if failed:
            print(f"  {failed} file(s) could not be read (damaged sectors)", file=sys.stderr)

    elif source.lower().endswith(".img"):
        # Disk image — try FAT12, fall back to carve
        try:
            from mavica_tools.fat12 import extract_with_names

            results = extract_with_names(
                source,
                output_dir,
                auto_stamp=bool(model),
                camera_model=model,
            )
            imported = [path for _, path, _, _ in results]
            if model and results:
                model = None  # Already stamped via auto_stamp
        except Exception:
            from mavica_tools.carve import carve_jpegs

            imported = carve_jpegs(source, output_dir)
    else:
        print(f"Don't know how to read: {source}", file=sys.stderr)
        return {"imported": 0, "tagged": False, "contact_sheet": None}

    # Tag
    tagged = False
    if model and imported:
        from mavica_tools.stamp import stamp_jpeg

        for path in imported:
            if path.lower().endswith((".jpg", ".jpeg")):
                stamp_jpeg(path, model=model, date="auto", overwrite=True)
        tagged = True

    # Contact sheet
    sheet_path = None
    if contact_sheet and imported:
        from mavica_tools.export import make_contact_sheet

        sheet_path = os.path.join(output_dir, "contact_sheet.jpg")
        title = f"Mavica {model.upper()}" if model else "Mavica Photos"
        make_contact_sheet(imported, sheet_path, columns=4, title=title)

    return {
        "imported": len(imported),
        "tagged": tagged,
        "contact_sheet": sheet_path,
        "files": imported,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Quick import: copy photos from floppy, tag, and go"
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Floppy path (E:\\, /mnt/floppy), folder, or disk image (.img). "
        "Omit to auto-detect a connected floppy drive.",
    )
    parser.add_argument("-o", "--output", default="mavica_out/photos", help="Output directory")
    parser.add_argument("-m", "--model", help="Camera model (e.g., fd7, fd88)")
    parser.add_argument(
        "--contact-sheet",
        action="store_true",
        help="Generate a contact sheet grid",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show imported photos in the terminal (from local disk, not floppy)",
    )

    args = parser.parse_args()

    source = args.source
    if source is None:
        from mavica_tools.detect import detect_floppy_mount_points

        mounts = detect_floppy_mount_points()
        if not mounts:
            print(
                "No mounted floppy drives detected.\n"
                "Specify a path manually:  mavica import E:\\ -m fd7",
                file=sys.stderr,
            )
            sys.exit(1)
        if len(mounts) > 1:
            print("Multiple floppy drives detected:")
            for i, m in enumerate(mounts, 1):
                print(f"  {i}. {m}")
            print("\nSpecify one explicitly:  mavica import <path>", file=sys.stderr)
            sys.exit(1)
        source = mounts[0]
        print(f"Auto-detected floppy: {source}")

    print(f"Importing from {source}...\n")

    result = quick_import(
        source,
        output_dir=args.output,
        model=args.model,
        contact_sheet=args.contact_sheet,
    )

    from mavica_tools.fun import random_trivia

    print(f"\n{result['imported']} photo(s) imported to {args.output}/")
    if result["tagged"]:
        print(f"  Tagged with camera: {args.model}")
    if result["contact_sheet"]:
        print(f"  Contact sheet: {result['contact_sheet']}")

    if result["imported"] == 0:
        print("\n  No photos found. Check the path and try again.")
    else:
        # Show fun stats
        total_bytes = sum(os.path.getsize(f) for f in result["files"] if os.path.exists(f))
        from mavica_tools.fun import disk_stats_text

        print(disk_stats_text(result["imported"], total_bytes))
        print(f"\n  \033[2m{random_trivia()}\033[0m")

        if args.preview:
            from mavica_tools.terminal_image import show_image, show_images

            if result["contact_sheet"]:
                print()
                show_image(result["contact_sheet"], label=False)
            else:
                print()
                show_images(result["files"], max_images=6)


if __name__ == "__main__":
    main()
