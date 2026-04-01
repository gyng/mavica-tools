"""Multi-pass floppy disk imager.

Reads a floppy disk multiple times and merges the best sectors.
Floppy reads are non-deterministic — a sector that fails on pass 1 may
succeed on pass 3. This tool exploits that by taking multiple passes and
picking the first good read for each sector.
"""

import argparse
import os
import subprocess
import sys
import time
import zlib

SECTOR_SIZE = 512
SECTORS_PER_TRACK = 18
HEADS = 2
TRACKS = 80
DISK_SIZE = SECTOR_SIZE * SECTORS_PER_TRACK * HEADS * TRACKS  # 1,474,560 bytes (1.44MB)
TOTAL_SECTORS = SECTORS_PER_TRACK * HEADS * TRACKS  # 2880


def read_pass(device, pass_num, output_dir):
    """Do one full read pass of the floppy, tolerating errors."""
    img_path = os.path.join(output_dir, f"pass_{pass_num:02d}.img")
    log_path = os.path.join(output_dir, f"pass_{pass_num:02d}.log")

    print(f"  Pass {pass_num}: reading {device} -> {img_path}")

    result = subprocess.run(
        [
            "dd",
            f"if={device}",
            f"of={img_path}",
            f"bs={SECTOR_SIZE}",
            "conv=noerror,sync",
            "status=progress",
        ],
        capture_output=True,
        text=True,
    )

    with open(log_path, "w") as f:
        f.write(result.stderr)

    # Count error lines in dd output
    errors = result.stderr.lower().count("error")
    return img_path, errors


def identify_bad_sectors(image_path):
    """Return set of sector indices that are blank (all zeros) in an image."""
    data = read_image_file(image_path)
    bad = set()
    for i in range(TOTAL_SECTORS):
        sector = data[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE]
        if sector_is_blank(sector):
            bad.add(i)
    return bad


def read_sectors(
    device, on_sector=None, on_metadata_ready=None, skip_sectors=None, only_sectors=None
):
    """Core sector-reading loop with track-level bulk reads.

    Returns (data_bytearray, error_count).

    on_sector(sector_index, state): called after each sector.
    on_metadata_ready(data_bytes): called once after sector 32 is read.
    skip_sectors: set of sectors to skip (already good).
    only_sectors: if set, only read these sectors (for quick/spot checks).
    """
    if skip_sectors is None:
        skip_sectors = set()

    data = bytearray(DISK_SIZE)
    errors = 0
    metadata_fired = False

    with open(device, "rb") as dev:
        sector_idx = 0
        while sector_idx < TOTAL_SECTORS:
            track_start = (sector_idx // SECTORS_PER_TRACK) * SECTORS_PER_TRACK
            track_end = track_start + SECTORS_PER_TRACK

            # Check if entire track can be skipped
            track_sectors = set(range(track_start, min(track_end, TOTAL_SECTORS)))
            if track_sectors.issubset(skip_sectors):
                for s in range(track_start, min(track_end, TOTAL_SECTORS)):
                    if on_sector:
                        on_sector(s, "good")
                try:
                    dev.seek(min(track_end, TOTAL_SECTORS) * SECTOR_SIZE)
                except OSError:
                    dev.read((min(track_end, TOTAL_SECTORS) - sector_idx) * SECTOR_SIZE)
                sector_idx = min(track_end, TOTAL_SECTORS)
                continue

            # If only_sectors is set, skip tracks with no target sectors
            if only_sectors is not None and not (track_sectors & only_sectors):
                for s in track_sectors:
                    if on_sector:
                        on_sector(s, "waiting")
                try:
                    dev.seek(min(track_end, TOTAL_SECTORS) * SECTOR_SIZE)
                except OSError:
                    pass
                sector_idx = min(track_end, TOTAL_SECTORS)
                continue

            # Try bulk track read if no sectors to skip in this track
            track_has_skips = bool(track_sectors & skip_sectors)
            if not track_has_skips and sector_idx == track_start:
                remaining = min(SECTORS_PER_TRACK, TOTAL_SECTORS - track_start)
                try:
                    dev.seek(track_start * SECTOR_SIZE)
                    chunk = dev.read(remaining * SECTOR_SIZE)
                    if len(chunk) == remaining * SECTOR_SIZE:
                        data[track_start * SECTOR_SIZE : track_start * SECTOR_SIZE + len(chunk)] = (
                            chunk
                        )
                        for s in range(track_start, track_start + remaining):
                            if on_sector:
                                on_sector(s, "good")
                        if (
                            not metadata_fired
                            and track_start + remaining > 32
                            and on_metadata_ready
                        ):
                            metadata_fired = True
                            on_metadata_ready(bytes(data))
                        sector_idx = track_start + remaining
                        continue
                except OSError:
                    pass
                try:
                    dev.seek(track_start * SECTOR_SIZE)
                except OSError:
                    pass

            # Sector-by-sector for this track
            if sector_idx < track_start:
                sector_idx = track_start
            for s in range(sector_idx, min(track_end, TOTAL_SECTORS)):
                if s in skip_sectors:
                    if on_sector:
                        on_sector(s, "good")
                    try:
                        dev.seek((s + 1) * SECTOR_SIZE)
                    except OSError:
                        try:
                            dev.read(SECTOR_SIZE)
                        except OSError:
                            pass
                    continue

                if only_sectors is not None and s not in only_sectors:
                    if on_sector:
                        on_sector(s, "waiting")
                    try:
                        dev.seek((s + 1) * SECTOR_SIZE)
                    except OSError:
                        pass
                    continue

                if on_sector:
                    on_sector(s, "reading")

                try:
                    dev.seek(s * SECTOR_SIZE)
                except OSError:
                    pass

                try:
                    chunk = dev.read(SECTOR_SIZE)
                    if len(chunk) == SECTOR_SIZE:
                        data[s * SECTOR_SIZE : (s + 1) * SECTOR_SIZE] = chunk
                        if on_sector:
                            on_sector(s, "good")
                    else:
                        data[s * SECTOR_SIZE : s * SECTOR_SIZE + len(chunk)] = chunk
                        errors += 1
                        if on_sector:
                            on_sector(s, "bad")
                except OSError:
                    errors += 1
                    if on_sector:
                        on_sector(s, "bad")

                if not metadata_fired and s >= 32 and on_metadata_ready:
                    metadata_fired = True
                    on_metadata_ready(bytes(data))

            sector_idx = min(track_end, TOTAL_SECTORS)

    return data, errors


def read_pass_sectored(
    device, pass_num, output_dir, on_sector=None, on_metadata_ready=None, skip_sectors=None
):
    """Read a floppy pass and write the result to a .img file.

    Thin wrapper around read_sectors() that persists the data.
    Falls back to bulk dd if the device can't be opened directly.
    """
    img_path = os.path.join(output_dir, f"pass_{pass_num:02d}.img")

    try:
        try:
            data, errors = read_sectors(
                device,
                on_sector=on_sector,
                on_metadata_ready=on_metadata_ready,
                skip_sectors=skip_sectors,
            )
        finally:
            # Always write whatever was read — even if interrupted mid-read
            try:
                with open(img_path, "wb") as f:
                    f.write(data)
            except UnboundLocalError:
                pass  # read_sectors raised before data was assigned

        return img_path, errors

    except (OSError, PermissionError):
        # Can't open device directly — fall back to dd
        return read_pass(device, pass_num, output_dir)


def read_image_file(path):
    """Read a disk image file, padding to full disk size if needed."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < DISK_SIZE:
        data += b"\x00" * (DISK_SIZE - len(data))
    return data


def sector_is_blank(sector_data):
    """Check if a sector is all zeros (likely a read failure filled by conv=sync)."""
    return sector_data == b"\x00" * SECTOR_SIZE


def merge_passes(image_paths):
    """Merge multiple pass images, picking the best sector from each.

    Strategy:
    - For each sector, use the first non-blank read
    - If all reads are non-blank, use majority vote (most common content)
    - Track which sectors had disagreements (potential trouble spots)
    """
    images = [read_image_file(p) for p in image_paths]
    merged = bytearray(DISK_SIZE)
    sector_status = []  # 'good', 'recovered', 'blank', 'conflict'

    for sector_idx in range(TOTAL_SECTORS):
        offset = sector_idx * SECTOR_SIZE
        reads = [img[offset : offset + SECTOR_SIZE] for img in images]

        non_blank = [r for r in reads if not sector_is_blank(r)]

        if not non_blank:
            # All passes returned blank — sector is unreadable
            merged[offset : offset + SECTOR_SIZE] = b"\x00" * SECTOR_SIZE
            sector_status.append("blank")
        elif len(non_blank) == 1:
            # Only one pass got data — use it
            merged[offset : offset + SECTOR_SIZE] = non_blank[0]
            sector_status.append("recovered")
        else:
            # Multiple non-blank reads — use majority vote
            counts = {}
            for r in non_blank:
                h = zlib.crc32(r)
                counts[h] = counts.get(h, 0) + 1

            if len(counts) == 1:
                # All non-blank reads agree
                merged[offset : offset + SECTOR_SIZE] = non_blank[0]
                sector_status.append("good")
            else:
                # Conflict — pick the most common read
                best_hash = max(counts, key=counts.get)
                for r in non_blank:
                    if zlib.crc32(r) == best_hash:
                        merged[offset : offset + SECTOR_SIZE] = r
                        break
                sector_status.append("conflict")

    return bytes(merged), sector_status


def print_sector_map(sector_status):
    """Print a visual map of sector health."""
    symbols = {"good": ".", "recovered": "r", "blank": "X", "conflict": "!"}

    print("\nSector map (each char = 1 sector, 18 sectors/line = 1 track side):")
    print("  . = good  r = recovered from one pass  X = unreadable  ! = conflict\n")

    for i in range(0, len(sector_status), SECTORS_PER_TRACK):
        track = i // (SECTORS_PER_TRACK * HEADS)
        head = (i // SECTORS_PER_TRACK) % HEADS
        chunk = sector_status[i : i + SECTORS_PER_TRACK]
        line = "".join(symbols.get(s, "?") for s in chunk)
        print(f"  T{track:02d}H{head} [{line}]")


def print_summary(sector_status, pass_image_paths=None):
    """Print a summary of disk health."""
    total = len(sector_status)
    good = sector_status.count("good")
    recovered = sector_status.count("recovered")
    blank = sector_status.count("blank")
    conflict = sector_status.count("conflict")

    readable_pct = 100 * (good + recovered) / total if total else 0

    from mavica_tools.fun import health_bar, recovery_suggestions, sector_sparkline

    print("\nDisk health:")
    print(health_bar(readable_pct))
    print(sector_sparkline(sector_status))
    print()
    print(f"  Total:     {total}")
    print(f"  Good:      {good} ({100 * good / total:.1f}%)")
    print(f"  Recovered: {recovered} ({100 * recovered / total:.1f}%)")
    print(f"  Conflict:  {conflict} ({100 * conflict / total:.1f}%)")
    print(f"  Blank:     {blank} ({100 * blank / total:.1f}%)")

    suggestions = recovery_suggestions(sector_status)
    if suggestions:
        print()
        for s in suggestions:
            print(f"  {s}")

    # Drive vs disk diagnostics
    if blank > 0:
        try:
            from mavica_tools.diagnose import diagnose_errors, format_diagnosis

            diag = diagnose_errors(
                pass_image_paths=pass_image_paths,
                sector_status=sector_status,
            )
            if diag.evidence:
                print("\nDiagnosis:")
                print(format_diagnosis(diag, rich=False))
        except Exception:
            pass  # Diagnostics are best-effort


def multipass_image(device, output_dir, passes=5, eject_between=True, adaptive_stop=True):
    """Run the full multi-pass imaging workflow.

    With adaptive_stop=True, stops early if 2 consecutive passes
    recover zero new sectors (diminishing returns).
    """
    os.makedirs(output_dir, exist_ok=True)

    print("Multi-pass floppy imager")
    print(f"  Device: {device}")
    print(f"  Passes: {passes}")
    print(f"  Output: {output_dir}")
    if adaptive_stop:
        print("  Adaptive stop: enabled (stops if no improvement)")
    print()

    image_paths = []
    good_sectors = set()  # Sectors known to be good from prior passes
    stale_count = 0  # Consecutive passes with no new recovery

    for i in range(1, passes + 1):
        skip = good_sectors if i > 1 else None
        if skip:
            print(
                f"  Pass {i}: reading {len(good_sectors)} good, {TOTAL_SECTORS - len(good_sectors)} to retry"
            )

        path, errors = read_pass_sectored(device, i, output_dir, skip_sectors=skip)
        image_paths.append(path)
        if errors:
            print(f"    ({errors} error(s))")
        else:
            print("    clean read")

        # Update good sectors set
        bad = identify_bad_sectors(path)
        new_good = (set(range(TOTAL_SECTORS)) - bad) - good_sectors
        good_sectors |= set(range(TOTAL_SECTORS)) - bad

        if i > 1:
            if new_good:
                print(f"    +{len(new_good)} new sector(s) recovered")
                stale_count = 0
            else:
                stale_count += 1
                print("    no new sectors recovered")

        # Adaptive stop
        if adaptive_stop and stale_count >= 2 and i < passes:
            print("\n  Stopping early: no improvement in last 2 passes.")
            break

        if eject_between and i < passes:
            print("  Ejecting disk (re-insert when ready)...")
            subprocess.run(["eject", device], capture_output=True)
            time.sleep(1)
            for _ in range(30):
                if os.path.exists(device):
                    break
                time.sleep(1)

    print(f"\nMerging {len(image_paths)} passes...")
    merged, sector_status = merge_passes(image_paths)

    merged_path = os.path.join(output_dir, "merged.img")
    with open(merged_path, "wb") as f:
        f.write(merged)

    print(f"Merged image written to: {merged_path}")
    print_sector_map(sector_status)
    print_summary(sector_status, pass_image_paths=image_paths)

    return merged_path, sector_status


def merge_existing_images(image_paths, output_path):
    """Merge already-captured disk images (no hardware needed)."""
    print(f"Merging {len(image_paths)} existing images...")
    merged, sector_status = merge_passes(image_paths)

    with open(output_path, "wb") as f:
        f.write(merged)

    print(f"Merged image written to: {output_path}")
    print_sector_map(sector_status)
    print_summary(sector_status, pass_image_paths=image_paths)

    return output_path, sector_status


def main():
    parser = argparse.ArgumentParser(
        description="Multi-pass floppy disk imager for Mavica recovery"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Live read from device
    read_parser = subparsers.add_parser("read", help="Read from a floppy device")
    read_parser.add_argument("device", help="Floppy device (e.g. /dev/fd0)")
    read_parser.add_argument(
        "-o", "--output", default="mavica_out/disk_images", help="Output directory"
    )
    read_parser.add_argument(
        "-n", "--passes", type=int, default=5, help="Number of read passes (default: 5)"
    )
    read_parser.add_argument(
        "--no-eject",
        action="store_true",
        help="Don't eject between passes",
    )

    # Merge existing images
    merge_parser = subparsers.add_parser("merge", help="Merge existing disk images")
    merge_parser.add_argument("images", nargs="+", help="Disk image files to merge")
    merge_parser.add_argument(
        "-o", "--output", default="merged.img", help="Output merged image path"
    )

    args = parser.parse_args()

    if args.command == "read":
        multipass_image(
            args.device,
            args.output,
            passes=args.passes,
            eject_between=not args.no_eject,
        )
    elif args.command == "merge":
        merge_existing_images(args.images, args.output)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
