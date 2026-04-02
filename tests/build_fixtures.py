#!/usr/bin/env python3
"""Build fixture disk images from real Mavica photos.

Generates FAT12 disk images that mirror real Mavica floppy layout:
  - JPEGs written first in the data area
  - .411 thumbnails written after, in reverse order
  - Directory entries: JPEGs first, then .411s

Run:  uv run python tests/build_fixtures.py
"""

import os
import struct
import sys

# Add parent to path so we can import mavica_tools
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mavica_tools.format import SECTOR_SIZE, SECTORS_PER_FAT, create_disk_image

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

FAT_OFFSET = 1  # sectors
FATS_COUNT = 2
ROOT_DIR_OFFSET = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
DATA_START_SECTOR = 33


def _set_fat12_entry(disk: bytearray, cluster: int, value: int) -> None:
    """Set a FAT12 entry in both FAT1 and FAT2."""
    for fat_start in [FAT_OFFSET * SECTOR_SIZE, (FAT_OFFSET + SECTORS_PER_FAT) * SECTOR_SIZE]:
        byte_offset = fat_start + (cluster * 3) // 2
        if cluster % 2 == 0:
            disk[byte_offset] = value & 0xFF
            disk[byte_offset + 1] = (disk[byte_offset + 1] & 0xF0) | ((value >> 8) & 0x0F)
        else:
            disk[byte_offset] = (disk[byte_offset] & 0x0F) | ((value & 0x0F) << 4)
            disk[byte_offset + 1] = (value >> 4) & 0xFF


def _add_file(
    disk: bytearray, dos_name: bytes, dos_ext: bytes, data: bytes, cluster: int, dir_index: int
) -> int:
    """Write a file into the disk image. Returns next free cluster.

    Args:
        disk: Mutable disk image
        dos_name: 8-byte space-padded filename (e.g. b"MVC-002F")
        dos_ext: 3-byte extension (e.g. b"JPG" or b"411")
        data: File contents
        cluster: Starting cluster number
        dir_index: Root directory entry index
    """
    clusters_needed = (len(data) + SECTOR_SIZE - 1) // SECTOR_SIZE

    # Write data to sectors
    for i in range(clusters_needed):
        offset = (DATA_START_SECTOR + (cluster + i - 2)) * SECTOR_SIZE
        chunk = data[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE]
        disk[offset : offset + len(chunk)] = chunk

    # Write FAT chain
    for i in range(clusters_needed):
        c = cluster + i
        if i < clusters_needed - 1:
            _set_fat12_entry(disk, c, c + 1)
        else:
            _set_fat12_entry(disk, c, 0xFF8)  # end of chain

    # Write directory entry (32 bytes)
    entry = bytearray(32)
    entry[0:8] = dos_name
    entry[8:11] = dos_ext
    entry[11] = 0x20  # archive attribute
    # DOS date: 2001-07-04 = ((2001-1980)<<9) | (7<<5) | 4
    dos_date = ((2001 - 1980) << 9) | (7 << 5) | 4
    struct.pack_into("<H", entry, 24, dos_date)
    struct.pack_into("<H", entry, 26, cluster)  # start cluster
    struct.pack_into("<I", entry, 28, len(data))  # file size

    dir_offset = ROOT_DIR_OFFSET + dir_index * 32
    disk[dir_offset : dir_offset + 32] = entry

    return cluster + clusters_needed


def _load_fixture(name: str) -> bytes:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, "rb") as f:
        return f.read()


def build_good_disk() -> bytearray:
    """Build disk_with_photos.img — good disk with 5 JPEGs + 5 .411s."""
    disk = bytearray(create_disk_image("MAVICA"))

    # Files to write: JPEGs first, then .411s in reverse order
    # (matches real Mavica floppy layout)
    jpegs = [
        ("MVC-001F", "JPG", _load_fixture("MVC-001F.JPG")),
        ("MVC-002F", "JPG", _load_fixture("MVC-002F.JPG")),
        ("MVC-004F", "JPG", _load_fixture("MVC-004F.JPG")),
        ("MVC-006F", "JPG", _load_fixture("MVC-006F.JPG")),
        ("MVC-015F", "JPG", _load_fixture("MVC-015F.JPG")),
    ]
    thumbnails = [
        ("MVC-016F", "411", _load_fixture("MVC-016F.411")),
        ("MVC-015F", "411", _load_fixture("MVC-015F.411")),
        ("MVC-006F", "411", _load_fixture("MVC-006F.411")),
        ("MVC-004F", "411", _load_fixture("MVC-004F.411")),
        ("MVC-002F", "411", _load_fixture("MVC-002F.411")),
        ("MVC-001F", "411", _load_fixture("MVC-001F.411")),
    ]

    cluster = 2  # first data cluster
    dir_index = 0

    # Write JPEGs first
    for name, ext, data in jpegs:
        dos_name = name.encode("ascii").ljust(8)
        dos_ext = ext.encode("ascii").ljust(3)
        cluster = _add_file(disk, dos_name, dos_ext, data, cluster, dir_index)
        dir_index += 1

    # Write .411 thumbnails in reverse order (matches real Mavica layout)
    for name, ext, data in thumbnails:
        dos_name = name.encode("ascii").ljust(8)
        dos_ext = ext.encode("ascii").ljust(3)
        cluster = _add_file(disk, dos_name, dos_ext, data, cluster, dir_index)
        dir_index += 1

    return disk


def build_bad_sectors_disk(good_disk: bytearray) -> bytearray:
    """Build disk_bad_sectors.img — simulate a damaged floppy.

    Damage:
      - MVC-006F.JPG: 8 consecutive sectors zeroed mid-file + marked bad in FAT
      - MVC-002F.JPG: 4 consecutive sectors zeroed near the end
    This produces visible corruption that check_jpeg_structure detects
    (zero runs > 512 bytes) and bad sectors visible on the defrag map.
    """
    disk = bytearray(good_disk)

    jpeg_004_clusters = (len(_load_fixture("MVC-004F.JPG")) + SECTOR_SIZE - 1) // SECTOR_SIZE
    jpeg_002_clusters = (len(_load_fixture("MVC-002F.JPG")) + SECTOR_SIZE - 1) // SECTOR_SIZE
    jpeg_006_clusters = (len(_load_fixture("MVC-006F.JPG")) + SECTOR_SIZE - 1) // SECTOR_SIZE

    start_cluster_002 = 2 + jpeg_004_clusters
    start_cluster_006 = start_cluster_002 + jpeg_002_clusters

    # MVC-006F.JPG: zero out 8 sectors in the middle.
    # FAT chain stays intact (file is extractable but has a hole).
    # Also mark a few unallocated sectors as bad in FAT to test
    # the 0xFF7 detection path separately.
    mid_006 = start_cluster_006 + jpeg_006_clusters // 2
    for c in range(mid_006, mid_006 + 8):
        offset = (DATA_START_SECTOR + (c - 2)) * SECTOR_SIZE
        disk[offset : offset + SECTOR_SIZE] = b"\x00" * SECTOR_SIZE

    # Mark a few free clusters as bad in FAT (0xFF7) — simulates
    # a disk that was scanned and had bad sectors recorded
    next_free = 2 + jpeg_004_clusters + jpeg_002_clusters + jpeg_006_clusters
    # Skip past .411 thumbnails
    for _, _, thumb_data in [
        ("MVC-006F", "411", _load_fixture("MVC-006F.411")),
        ("MVC-004F", "411", _load_fixture("MVC-004F.411")),
        ("MVC-002F", "411", _load_fixture("MVC-002F.411")),
    ]:
        next_free += (len(thumb_data) + SECTOR_SIZE - 1) // SECTOR_SIZE
    # Mark 4 free clusters as bad in FAT
    for c in range(next_free, next_free + 4):
        _set_fat12_entry(disk, c, 0xFF7)

    # MVC-002F.JPG: zero out 4 sectors near the end (no FAT marking —
    # simulates undetected read failure from multipass merge)
    near_end_002 = start_cluster_002 + int(jpeg_002_clusters * 0.8)
    for c in range(near_end_002, near_end_002 + 4):
        offset = (DATA_START_SECTOR + (c - 2)) * SECTOR_SIZE
        disk[offset : offset + SECTOR_SIZE] = b"\x00" * SECTOR_SIZE

    return disk


def build_truncated_disk(good_disk: bytearray) -> bytearray:
    """Build disk_truncated.img — MVC-002F.JPG data cut to 70%."""
    disk = bytearray(good_disk)

    jpeg_004_clusters = (len(_load_fixture("MVC-004F.JPG")) + SECTOR_SIZE - 1) // SECTOR_SIZE
    jpeg_002_size = len(_load_fixture("MVC-002F.JPG"))
    jpeg_002_clusters = (jpeg_002_size + SECTOR_SIZE - 1) // SECTOR_SIZE

    start_cluster_002 = 2 + jpeg_004_clusters
    # Zero out the last 30% of MVC-002F.JPG's sectors
    cutoff_cluster = start_cluster_002 + int(jpeg_002_clusters * 0.7)
    for c in range(cutoff_cluster, start_cluster_002 + jpeg_002_clusters):
        offset = (DATA_START_SECTOR + (c - 2)) * SECTOR_SIZE
        disk[offset : offset + SECTOR_SIZE] = b"\x00" * SECTOR_SIZE

    return disk


def build_deleted_files_disk(good_disk: bytearray) -> bytearray:
    """Build disk_deleted_files.img — MVC-004F.JPG dir entry marked as deleted (0xE5)."""
    disk = bytearray(good_disk)

    # MVC-004F.JPG is the first directory entry (dir_index=0)
    dir_offset = ROOT_DIR_OFFSET
    disk[dir_offset] = 0xE5  # mark as deleted

    return disk


def build_gpx_track() -> str:
    """Build track_2001-07-04.gpx — a GPX track matching the photo timestamps.

    Simulates a walk through Tokyo on 2001-07-04 with trackpoints every
    minute from 10:00 to 11:00 UTC. The fixture JPEGs (MVC-002F, MVC-004F,
    MVC-006F) have DOS date 2001-07-04, so they'll match within tolerance.
    """
    import math

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">',
        "<trk><name>Tokyo Walk 2001-07-04</name><trkseg>",
    ]

    # 61 trackpoints, one per minute from 10:00 to 11:00
    for i in range(61):
        t = i / 60.0
        lat = 35.6800 + t * 0.015 + math.sin(t * 6) * 0.001
        lon = 139.7660 + t * 0.014 + math.cos(t * 4) * 0.001
        alt = 30.0 + math.sin(t * 3) * 5
        minute = i
        hour = 10 + minute // 60
        minute = minute % 60
        time_str = f"2001-07-04T{hour:02d}:{minute:02d}:00Z"
        lines.append(
            f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}">'
            f"<ele>{alt:.1f}</ele><time>{time_str}</time></trkpt>"
        )

    lines.append("</trkseg></trk></gpx>")
    return "\n".join(lines)


def main():
    os.makedirs(FIXTURES_DIR, exist_ok=True)

    print("Building fixture disk images...")

    good_disk = build_good_disk()
    images = {
        "disk_with_photos.img": good_disk,
        "disk_bad_sectors.img": build_bad_sectors_disk(good_disk),
        "disk_truncated.img": build_truncated_disk(good_disk),
        "disk_deleted_files.img": build_deleted_files_disk(good_disk),
    }

    for name, data in images.items():
        path = os.path.join(FIXTURES_DIR, name)
        with open(path, "wb") as f:
            f.write(data)
        print(f"  {name} ({len(data):,} bytes)")

    # Build GPX fixture
    gpx_content = build_gpx_track()
    gpx_path = os.path.join(FIXTURES_DIR, "track_2001-07-04.gpx")
    with open(gpx_path, "w", encoding="utf-8") as f:
        f.write(gpx_content)
    print(f"  track_2001-07-04.gpx ({len(gpx_content):,} bytes)")

    # Stamp fixture JPEGs with EXIF dates that fall within the GPX track window.
    # The track runs 10:00-11:00 UTC on 2001-07-04, so space the photos across it.
    stamp_fixture_jpeg_dates()

    print(f"\nDone. {len(images)} disk images + 1 GPX track in {FIXTURES_DIR}/")


def stamp_fixture_jpeg_dates():
    """Add EXIF DateTimeOriginal to fixture JPEGs so they match the GPX track."""
    try:
        import piexif
    except ImportError:
        print("  (skipping EXIF stamp — piexif not installed)")
        return

    # Timestamps offset from trackpoints to test tolerance matching:
    #   MVC-002F: 42s after 10:10 trackpoint — easy match within default 5m tolerance
    #   MVC-004F: 3m18s after 10:33 trackpoint — within 5m but tests interpolation
    #   MVC-006F: 6m15s after track ends at 11:00 — outside 5m tolerance, needs 7m+
    #   MVC-014F: exact match at 10:20 trackpoint
    #   MVC-015F: 1m45s after 10:45 trackpoint
    jpeg_times = {
        "MVC-002F.JPG": "2001:07:04 10:10:42",
        "MVC-004F.JPG": "2001:07:04 10:33:18",
        "MVC-006F.JPG": "2001:07:04 11:06:15",
        "MVC-001F.JPG": "2001:07:04 10:20:00",
        "MVC-015F.JPG": "2001:07:04 10:46:45",
    }

    for name, date_str in jpeg_times.items():
        path = os.path.join(FIXTURES_DIR, name)
        if not os.path.exists(path):
            continue
        try:
            exif_dict = piexif.load(path)
            exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = date_str.encode()
            exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = date_str.encode()
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, path)
            print(f"  {name} stamped with {date_str}")
        except Exception as e:
            print(f"  {name} stamp failed: {e}")


if __name__ == "__main__":
    main()
