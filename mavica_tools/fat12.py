"""FAT12 filesystem parser for Mavica floppy disk images.

Reads the FAT12 filesystem used by Mavica cameras to recover
original filenames (e.g., MVC-001.JPG) and directory structure.

Mavica cameras use standard FAT12 on 1.44MB HD floppies:
  - 512 bytes/sector, 1 sector/cluster
  - 2 FATs, 224 root directory entries
  - Files stored as 8.3 DOS names
"""

import os
import struct
from dataclasses import dataclass

SECTOR_SIZE = 512
CLUSTER_SIZE = SECTOR_SIZE  # 1 sector per cluster on Mavica floppies

# FAT12 boot sector layout
BOOT_SECTOR_SIZE = 512
FAT_OFFSET = 1  # FAT starts at sector 1
FATS_COUNT = 2
SECTORS_PER_FAT = 9
ROOT_DIR_ENTRIES = 224
ROOT_DIR_SECTORS = (ROOT_DIR_ENTRIES * 32) // SECTOR_SIZE  # 14 sectors
DATA_START_SECTOR = 1 + (FATS_COUNT * SECTORS_PER_FAT) + ROOT_DIR_SECTORS  # sector 33


@dataclass
class FileEntry:
    """A file found in the FAT12 directory."""

    name: str  # Full 8.3 name (e.g., "MVC-001.JPG")
    short_name: str  # Raw 8.3 (space-padded)
    size: int  # File size in bytes
    start_cluster: int  # First cluster number
    is_deleted: bool  # True if the file was deleted (first byte 0xE5)
    is_directory: bool
    raw_date: int  # DOS date field
    raw_time: int  # DOS time field
    date_str: str  # "YYYY-MM-DD" or "" if invalid
    time_str: str  # "HH:MM:SS" or "" if invalid

    @property
    def start_sector(self) -> int:
        """Disk sector where this file's data begins."""
        return DATA_START_SECTOR + (self.start_cluster - 2)

    @property
    def byte_offset(self) -> int:
        """Byte offset from start of disk image."""
        return self.start_sector * SECTOR_SIZE


def _decode_dos_name(raw_name: bytes, raw_ext: bytes) -> str:
    """Decode an 8.3 DOS filename."""
    name = raw_name.rstrip(b" ").decode("ascii", errors="replace")
    ext = raw_ext.rstrip(b" ").decode("ascii", errors="replace")
    if ext:
        return f"{name}.{ext}"
    return name


def _decode_dos_date(raw: int) -> str:
    """Decode a 16-bit DOS date to YYYY-MM-DD."""
    if raw == 0:
        return ""
    day = raw & 0x1F
    month = (raw >> 5) & 0x0F
    year = ((raw >> 9) & 0x7F) + 1980
    if 1 <= month <= 12 and 1 <= day <= 31:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def _decode_dos_time(raw: int) -> str:
    """Decode a 16-bit DOS time to HH:MM:SS."""
    if raw == 0:
        return ""
    second = (raw & 0x1F) * 2
    minute = (raw >> 5) & 0x3F
    hour = (raw >> 11) & 0x1F
    if hour < 24 and minute < 60 and second < 60:
        return f"{hour:02d}:{minute:02d}:{second:02d}"
    return ""


def read_fat12(data: bytes) -> list[int]:
    """Read the FAT12 table and return a list of cluster entries.

    FAT12 packs two 12-bit entries into 3 bytes:
      - Entry N at bytes [N*3/2 .. N*3/2+1]
      - Even entries: low 12 bits of the 16-bit word
      - Odd entries: high 12 bits of the 16-bit word
    """
    fat_start = FAT_OFFSET * SECTOR_SIZE
    fat_data = data[fat_start : fat_start + SECTORS_PER_FAT * SECTOR_SIZE]

    entries = []
    total_entries = (SECTORS_PER_FAT * SECTOR_SIZE * 2) // 3  # 12-bit entries

    for i in range(total_entries):
        byte_offset = (i * 3) // 2
        if byte_offset + 1 >= len(fat_data):
            break

        word = fat_data[byte_offset] | (fat_data[byte_offset + 1] << 8)

        if i % 2 == 0:
            entry = word & 0x0FFF
        else:
            entry = (word >> 4) & 0x0FFF

        entries.append(entry)

    return entries


def bad_sectors_from_fat(data: bytes) -> set[int]:
    """Return set of absolute sector indices marked as bad (0xFF7) in the FAT.

    Works on raw disk data — only needs the first 10 sectors (boot + FAT1).
    """
    fat = read_fat12(data)
    bad = set()
    for cluster_idx, entry in enumerate(fat):
        if cluster_idx < 2:
            continue  # reserved entries
        if entry == 0xFF7:
            sector = DATA_START_SECTOR + (cluster_idx - 2)
            bad.add(sector)
    return bad


def read_directory(data: bytes, dir_offset: int, max_entries: int) -> list[FileEntry]:
    """Read directory entries from a FAT12 directory region."""
    entries = []

    for i in range(max_entries):
        entry_offset = dir_offset + (i * 32)
        if entry_offset + 32 > len(data):
            break

        raw = data[entry_offset : entry_offset + 32]

        # First byte determines entry status
        first_byte = raw[0]
        if first_byte == 0x00:
            break  # End of directory
        if first_byte == 0x2E:
            continue  # . or .. entry

        is_deleted = first_byte == 0xE5
        attrs = raw[11]

        # Skip volume labels and LFN entries
        if attrs == 0x0F:  # LFN entry
            continue
        if attrs & 0x08 and not (attrs & 0x10):  # Volume label
            continue

        is_directory = bool(attrs & 0x10)

        raw_name = raw[0:8]
        raw_ext = raw[8:11]

        # For deleted files, the first byte was overwritten with 0xE5
        # Mavica files are typically MVC-NNN.JPG or MVC-NNNN.JPG
        # so the first byte is almost always 'M'
        if is_deleted:
            remaining = raw_name[1:]
            ext = raw_ext.rstrip(b" ").decode("ascii", errors="replace").upper()
            if remaining.startswith(b"VC-") or remaining.startswith(b"VC"):
                # Almost certainly a Mavica file — reconstruct as 'M'
                raw_name = b"M" + raw_name[1:]
            elif ext in ("JPG", "JPEG"):
                # JPEG file but unknown naming — use 'M' as best guess
                raw_name = b"M" + raw_name[1:]
            else:
                raw_name = b"_" + raw_name[1:]

        name = _decode_dos_name(raw_name, raw_ext)

        # Parse timestamps
        raw_time = struct.unpack_from("<H", raw, 22)[0]
        raw_date = struct.unpack_from("<H", raw, 24)[0]
        start_cluster = struct.unpack_from("<H", raw, 26)[0]
        size = struct.unpack_from("<I", raw, 28)[0]

        entries.append(
            FileEntry(
                name=name,
                short_name=raw_name.decode("ascii", errors="replace")
                + "."
                + raw_ext.decode("ascii", errors="replace"),
                size=size,
                start_cluster=start_cluster,
                is_deleted=is_deleted,
                is_directory=is_directory,
                raw_date=raw_date,
                raw_time=raw_time,
                date_str=_decode_dos_date(raw_date),
                time_str=_decode_dos_time(raw_time),
            )
        )

    return entries


def get_cluster_chain(fat: list[int], start_cluster: int) -> list[int]:
    """Follow a FAT12 cluster chain from start to end."""
    chain = []
    cluster = start_cluster

    # Safety: limit chain length to prevent infinite loops on corrupt FATs
    max_clusters = len(fat)
    seen = set()

    while 2 <= cluster < 0xFF8 and cluster < max_clusters and cluster not in seen:
        chain.append(cluster)
        seen.add(cluster)
        cluster = fat[cluster]

    return chain


def extract_file(data: bytes, fat: list[int], entry: FileEntry) -> bytes:
    """Extract a file's contents by following its cluster chain."""
    chain = get_cluster_chain(fat, entry.start_cluster)

    file_data = bytearray()
    for cluster in chain:
        # Cluster 2 = first data cluster, maps to DATA_START_SECTOR
        sector = DATA_START_SECTOR + (cluster - 2)
        offset = sector * SECTOR_SIZE
        file_data.extend(data[offset : offset + CLUSTER_SIZE])

    # Trim to actual file size
    return bytes(file_data[: entry.size])


def parse_disk_image(image_path: str) -> tuple[list[FileEntry], list[int], bytes]:
    """Parse a FAT12 disk image and return (files, fat_table, raw_data)."""
    with open(image_path, "rb") as f:
        data = f.read()

    files, fat = parse_disk_data(data)
    return files, fat, data


def parse_disk_data(data: bytes) -> tuple[list[FileEntry], list[int]]:
    """Parse FAT12 structures from raw disk bytes. Returns (files, fat_table)."""
    fat = read_fat12(data)
    root_dir_offset = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
    files = read_directory(data, root_dir_offset, ROOT_DIR_ENTRIES)
    return files, fat


def file_sector_map(image_path: str) -> list[tuple[str, list[int]]]:
    """Return a list of (filename, [sector_numbers]) for each file on disk.

    Useful for overlaying file boundaries on a sector visualization.
    """
    files, fat, _data = parse_disk_image(image_path)
    return _build_sector_map(files, fat)


def file_sector_map_from_data(data: bytes) -> list[tuple[str, list[int]]]:
    """Like file_sector_map but works on raw bytes instead of a file path.

    Can be called mid-read as soon as the first 33 sectors (FAT12 metadata)
    are available — the data area can be incomplete/zeroed.
    """
    files, fat = parse_disk_data(data)
    return _build_sector_map(files, fat)


def _build_sector_map(files: list[FileEntry], fat: list[int]) -> list[tuple[str, list[int]]]:
    """Build (filename, [sector_numbers]) list from parsed FAT12 data."""
    result = []
    for entry in files:
        if entry.is_directory or entry.size == 0:
            continue
        chain = get_cluster_chain(fat, entry.start_cluster)
        sectors = [DATA_START_SECTOR + (c - 2) for c in chain]
        result.append((entry.name, sectors))
    return result


def extract_with_names(
    image_path: str,
    output_dir: str,
    include_deleted: bool = False,
    auto_stamp: bool = False,
    camera_model: str = None,
):
    """Extract files from a Mavica disk image preserving original names.

    If auto_stamp=True, writes FAT12 timestamps into EXIF metadata for JPEGs.

    Returns list of (original_name, output_path, size, is_deleted).
    """
    files, fat, data = parse_disk_image(image_path)
    os.makedirs(output_dir, exist_ok=True)

    results = []
    for entry in files:
        if entry.is_directory:
            continue
        if entry.is_deleted and not include_deleted:
            continue
        if entry.size == 0:
            continue

        file_data = extract_file(data, fat, entry)

        # Use original name, prefix deleted files
        name = entry.name
        if entry.is_deleted:
            name = f"DELETED_{name}"

        out_path = os.path.join(output_dir, name)

        # Handle duplicates
        base, ext = os.path.splitext(out_path)
        counter = 1
        while os.path.exists(out_path):
            out_path = f"{base}_{counter}{ext}"
            counter += 1

        with open(out_path, "wb") as f:
            f.write(file_data)

        # Preserve FAT12 timestamp as file mtime
        if entry.date_str:
            try:
                from datetime import datetime as _dt

                ts_str = entry.date_str
                if entry.time_str:
                    ts_str += f" {entry.time_str}"
                else:
                    ts_str += " 00:00:00"
                ts = _dt.strptime(ts_str, "%Y-%m-%d %H:%M:%S").timestamp()
                os.utime(out_path, (ts, ts))
            except (ValueError, OSError):
                pass

        # Auto-stamp EXIF from FAT12 timestamps
        if auto_stamp and name.upper().endswith((".JPG", ".JPEG")):
            _auto_stamp_exif(out_path, entry, camera_model)

        results.append((entry.name, out_path, entry.size, entry.is_deleted))

    return results


def _auto_stamp_exif(filepath: str, entry: FileEntry, camera_model: str = None):
    """Stamp EXIF metadata from FAT12 directory entry timestamps."""
    try:
        from mavica_tools.stamp import stamp_jpeg

        date_str = None
        if entry.date_str:
            if entry.time_str:
                date_str = f"{entry.date_str} {entry.time_str}"
            else:
                date_str = entry.date_str

        if date_str or camera_model:
            stamp_jpeg(
                filepath,
                output_path=filepath,
                model=camera_model,
                date=date_str,
                overwrite=True,
            )
    except Exception:
        pass  # Best-effort — don't fail extraction on stamp errors


def list_files(image_path: str, include_deleted: bool = False) -> list[FileEntry]:
    """List files in a Mavica disk image."""
    files, _, _ = parse_disk_image(image_path)
    if not include_deleted:
        files = [f for f in files if not f.is_deleted]
    return files


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="FAT12 parser for Mavica floppy disk images")
    subparsers = parser.add_subparsers(dest="command")

    ls_parser = subparsers.add_parser("ls", help="List files on disk image")
    ls_parser.add_argument("image", help="Disk image file")
    ls_parser.add_argument("--deleted", action="store_true", help="Show deleted files too")

    extract_parser = subparsers.add_parser("extract", help="Extract files with original names")
    extract_parser.add_argument("image", help="Disk image file")
    extract_parser.add_argument(
        "-o", "--output", default="mavica_out/extracted", help="Output directory"
    )
    extract_parser.add_argument("--deleted", action="store_true", help="Include deleted files")

    args = parser.parse_args()

    if args.command == "ls":
        files = list_files(args.image, include_deleted=args.deleted)
        if not files:
            print("No files found.")
            sys.exit(0)

        print(f"{'Status':<8} {'Name':<16} {'Size':>10} {'Date':<12} {'Time':<10}")
        print("-" * 60)
        for f in files:
            status = "DEL" if f.is_deleted else "OK"
            print(f"{status:<8} {f.name:<16} {f.size:>10,} {f.date_str:<12} {f.time_str:<10}")

        total = sum(f.size for f in files if not f.is_deleted)
        print(f"\n{len(files)} file(s), {total:,} bytes")

    elif args.command == "extract":
        results = extract_with_names(args.image, args.output, include_deleted=args.deleted)
        for name, path, size, deleted in results:
            prefix = "[DELETED] " if deleted else ""
            print(f"  {prefix}{name} -> {path} ({size:,} bytes)")
        print(f"\n{len(results)} file(s) extracted to {args.output}/")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
