"""Batch recovery command — runs the full workflow unattended.

Pipeline: multipass read -> FAT12 extract (or carve) -> check -> repair

This is the "just do everything" command for when you want to
recover a floppy with minimal interaction.
"""

import argparse
import os
import platform
import sys

from mavica_tools.multipass import merge_passes, SECTOR_SIZE, DISK_SIZE
from mavica_tools.fat12 import parse_disk_image, extract_with_names, list_files
from mavica_tools.carve import carve_jpegs
from mavica_tools.check import check_jpeg_structure
from mavica_tools.repair import repair_jpeg


def recover_from_images(image_paths: list[str], output_dir: str, use_fat: bool = True):
    """Run the full recovery pipeline from existing disk image(s).

    Steps:
    1. Merge images (if multiple)
    2. Try FAT12 extraction first (preserves filenames)
    3. Fall back to JPEG carving if FAT12 fails
    4. Check all extracted files
    5. Repair any corrupt ones

    Returns a summary dict.
    """
    os.makedirs(output_dir, exist_ok=True)

    summary = {
        "merged_path": None,
        "extraction_method": None,
        "total_files": 0,
        "good": 0,
        "repaired": 0,
        "failed": 0,
        "files": [],
    }

    # Step 1: Merge
    print(f"[1/4] Merging {len(image_paths)} image(s)...")
    merged, sector_status = merge_passes(image_paths)

    merged_path = os.path.join(output_dir, "merged.img")
    with open(merged_path, "wb") as f:
        f.write(merged)
    summary["merged_path"] = merged_path

    good_sectors = sector_status.count("good") + sector_status.count("recovered")
    total_sectors = len(sector_status)
    print(f"  Sectors: {good_sectors}/{total_sectors} readable "
          f"({100 * good_sectors / total_sectors:.1f}%)")

    # Step 2: Extract files
    extracted_dir = os.path.join(output_dir, "extracted")
    os.makedirs(extracted_dir, exist_ok=True)

    extracted_files = []

    if use_fat:
        print("\n[2/4] Trying FAT12 filesystem extraction...")
        try:
            files = list_files(merged_path, include_deleted=True)
            jpeg_files = [f for f in files if f.name.upper().endswith((".JPG", ".JPEG"))]

            if jpeg_files:
                results = extract_with_names(merged_path, extracted_dir, include_deleted=True)
                extracted_files = [path for _, path, _, _ in results]
                summary["extraction_method"] = "fat12"
                print(f"  Extracted {len(extracted_files)} file(s) with original names")
            else:
                print("  No JPEG files found in FAT12 directory")
                raise ValueError("No files in FAT12")
        except Exception as e:
            print(f"  FAT12 extraction failed: {e}")
            print("  Falling back to JPEG carving...")
            use_fat = False

    if not use_fat or not extracted_files:
        print("\n[2/4] Carving JPEGs from raw image...")
        extracted_files = carve_jpegs(merged_path, extracted_dir)
        summary["extraction_method"] = "carve"

    if not extracted_files:
        print("\nNo images recovered.")
        return summary

    summary["total_files"] = len(extracted_files)

    # Step 3: Check
    print(f"\n[3/4] Checking {len(extracted_files)} file(s)...")
    needs_repair = []

    for filepath in extracted_files:
        result = check_jpeg_structure(filepath)
        name = os.path.basename(filepath)

        if not result["issues"]:
            summary["good"] += 1
            print(f"  OK   {name}")
            summary["files"].append((name, filepath, "ok"))
        else:
            issues = "; ".join(result["issues"])
            print(f"  WARN {name}: {issues}")
            needs_repair.append(filepath)

    # Step 4: Repair
    if needs_repair:
        repaired_dir = os.path.join(output_dir, "repaired")
        os.makedirs(repaired_dir, exist_ok=True)

        print(f"\n[4/4] Repairing {len(needs_repair)} file(s)...")
        for filepath in needs_repair:
            name = os.path.basename(filepath)
            base, _ = os.path.splitext(name)
            out_path = os.path.join(repaired_dir, base + "_repaired.png")

            ok, result_path, msg = repair_jpeg(filepath, out_path)
            if ok:
                summary["repaired"] += 1
                print(f"  FIXED {name}: {msg}")
                summary["files"].append((name, result_path, "repaired"))
            else:
                summary["failed"] += 1
                print(f"  FAIL  {name}: {msg}")
                summary["files"].append((name, filepath, "failed"))
    else:
        print("\n[4/4] No repairs needed — all files are OK!")

    # Summary
    print(f"\n{'='*50}")
    print(f"Recovery complete: {output_dir}/")
    print(f"  Total:    {summary['total_files']}")
    print(f"  Good:     {summary['good']}")
    print(f"  Repaired: {summary['repaired']}")
    print(f"  Failed:   {summary['failed']}")
    print(f"  Method:   {summary['extraction_method']}")

    return summary


def recover_from_device(device: str, output_dir: str, passes: int = 5):
    """Full recovery from a floppy device: read + extract + check + repair."""
    import subprocess
    import time

    os.makedirs(output_dir, exist_ok=True)
    system = platform.system()

    print(f"Reading floppy from {device} ({passes} passes)...\n")

    image_paths = []
    for p in range(1, passes + 1):
        img_path = os.path.join(output_dir, f"pass_{p:02d}.img")
        print(f"  Pass {p}/{passes}...", end=" ", flush=True)

        try:
            if system == "Windows":
                with open(device, "rb") as dev:
                    data = dev.read(DISK_SIZE)
                with open(img_path, "wb") as f:
                    f.write(data)
                print(f"read {len(data):,} bytes")
            else:
                result = subprocess.run(
                    ["dd", f"if={device}", f"of={img_path}",
                     f"bs={SECTOR_SIZE}", "conv=noerror,sync"],
                    capture_output=True, text=True,
                )
                errors = result.stderr.lower().count("error")
                print(f"{'clean' if not errors else f'{errors} error(s)'}")

            image_paths.append(img_path)

        except (OSError, FileNotFoundError) as e:
            print(f"error: {e}")
            if not image_paths:
                print("\nCannot read device. Check that:")
                if system == "Windows":
                    print("  - You're running as Administrator")
                    print(r"  - The device path is correct (e.g., \\.\A:)")
                else:
                    print(f"  - {device} exists and you have read permission")
                    print("  - The floppy disk is inserted")
                return None

    if not image_paths:
        print("No successful reads.")
        return None

    print()
    return recover_from_images(image_paths, output_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Full recovery pipeline: read -> extract -> check -> repair"
    )
    subparsers = parser.add_subparsers(dest="command")

    # From device
    dev_parser = subparsers.add_parser("device", help="Recover from floppy device")
    dev_parser.add_argument("device", help="Floppy device path")
    dev_parser.add_argument("-o", "--output", default="mavica_out/recovery", help="Output directory")
    dev_parser.add_argument("-n", "--passes", type=int, default=5, help="Number of read passes")

    # From existing images
    img_parser = subparsers.add_parser("images", help="Recover from existing disk images")
    img_parser.add_argument("images", nargs="+", help="Disk image files")
    img_parser.add_argument("-o", "--output", default="mavica_out/recovery", help="Output directory")
    img_parser.add_argument("--no-fat", action="store_true", help="Skip FAT12, carve directly")

    args = parser.parse_args()

    if args.command == "device":
        recover_from_device(args.device, args.output, passes=args.passes)
    elif args.command == "images":
        recover_from_images(args.images, args.output, use_fat=not args.no_fat)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
