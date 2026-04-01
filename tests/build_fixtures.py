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
    """Build disk_with_photos.img — good disk with 3 JPEGs + 3 .411s."""
    disk = bytearray(create_disk_image("MAVICA"))

    # Files to write: JPEGs first, then .411s in reverse order
    jpegs = [
        ("MVC-004F", "JPG", _load_fixture("MVC-004F.JPG")),
        ("MVC-002F", "JPG", _load_fixture("MVC-002F.JPG")),
        ("MVC-006F", "JPG", _load_fixture("MVC-006F.JPG")),
    ]
    thumbnails = [
        ("MVC-006F", "411", _load_fixture("MVC-006F.411")),
        ("MVC-004F", "411", _load_fixture("MVC-004F.411")),
        ("MVC-002F", "411", _load_fixture("MVC-002F.411")),
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
    """Build disk_bad_sectors.img — zero out 2 consecutive sectors mid-JPEG.

    check_jpeg_structure flags zero runs > 512 bytes, so we need at least
    2 sectors (1024 bytes) of zeros to trigger detection.
    """
    disk = bytearray(good_disk)

    # MVC-006F.JPG is the 3rd JPEG written. Find its start by calculating:
    # cluster after MVC-004F (11 sectors) + MVC-002F (68 sectors)
    jpeg_004_clusters = (len(_load_fixture("MVC-004F.JPG")) + SECTOR_SIZE - 1) // SECTOR_SIZE
    jpeg_002_clusters = (len(_load_fixture("MVC-002F.JPG")) + SECTOR_SIZE - 1) // SECTOR_SIZE
    jpeg_006_clusters = (len(_load_fixture("MVC-006F.JPG")) + SECTOR_SIZE - 1) // SECTOR_SIZE

    start_cluster_006 = 2 + jpeg_004_clusters + jpeg_002_clusters
    # Zero out 2 consecutive sectors in the middle of MVC-006F.JPG
    mid_cluster = start_cluster_006 + jpeg_006_clusters // 2
    mid_offset = (DATA_START_SECTOR + (mid_cluster - 2)) * SECTOR_SIZE
    disk[mid_offset : mid_offset + SECTOR_SIZE * 2] = b"\x00" * (SECTOR_SIZE * 2)

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

    print(f"\nDone. {len(images)} disk images in {FIXTURES_DIR}/")


if __name__ == "__main__":
    main()
