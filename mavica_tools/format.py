"""Mavica-compatible FAT12 floppy formatter.

Creates a FAT12 filesystem image compatible with Mavica cameras.
Can write directly to a floppy device or output an image file.

Mavica cameras expect:
  - 1.44MB HD (2880 sectors, 512 bytes/sector)
  - FAT12 filesystem
  - 1 sector per cluster
  - 2 FATs, 9 sectors per FAT
  - 224 root directory entries
  - Volume label (optional, Mavica uses "MAVICA" or similar)
"""

import argparse
import os
import platform
import struct
import sys


SECTOR_SIZE = 512
TOTAL_SECTORS = 2880
DISK_SIZE = SECTOR_SIZE * TOTAL_SECTORS  # 1,474,560 bytes

# FAT12 BPB (BIOS Parameter Block) values for 1.44MB floppy
BYTES_PER_SECTOR = 512
SECTORS_PER_CLUSTER = 1
RESERVED_SECTORS = 1
NUM_FATS = 2
ROOT_ENTRIES = 224
SECTORS_PER_FAT = 9
SECTORS_PER_TRACK = 18
NUM_HEADS = 2
MEDIA_DESCRIPTOR = 0xF0  # 1.44MB floppy


def create_boot_sector(volume_label: str = "MAVICA") -> bytes:
    """Create a FAT12 boot sector for a 1.44MB floppy."""
    boot = bytearray(SECTOR_SIZE)

    # Jump instruction + NOP
    boot[0:3] = b"\xEB\x3C\x90"

    # OEM name (8 bytes)
    boot[3:11] = b"MAVICA  "

    # BIOS Parameter Block
    struct.pack_into("<H", boot, 11, BYTES_PER_SECTOR)       # bytes per sector
    boot[13] = SECTORS_PER_CLUSTER                             # sectors per cluster
    struct.pack_into("<H", boot, 14, RESERVED_SECTORS)        # reserved sectors
    boot[16] = NUM_FATS                                        # number of FATs
    struct.pack_into("<H", boot, 17, ROOT_ENTRIES)            # root dir entries
    struct.pack_into("<H", boot, 19, TOTAL_SECTORS)           # total sectors
    boot[21] = MEDIA_DESCRIPTOR                                # media descriptor
    struct.pack_into("<H", boot, 22, SECTORS_PER_FAT)         # sectors per FAT
    struct.pack_into("<H", boot, 24, SECTORS_PER_TRACK)       # sectors per track
    struct.pack_into("<H", boot, 26, NUM_HEADS)               # number of heads
    struct.pack_into("<I", boot, 28, 0)                        # hidden sectors
    struct.pack_into("<I", boot, 32, 0)                        # total sectors (32-bit, 0 = use 16-bit)

    # Extended boot record
    boot[36] = 0x00             # drive number (floppy)
    boot[37] = 0x00             # reserved
    boot[38] = 0x29             # extended boot signature
    struct.pack_into("<I", boot, 39, 0x12345678)  # volume serial number

    # Volume label (11 bytes, space-padded)
    label = volume_label.upper()[:11].ljust(11).encode("ascii")
    boot[43:54] = label

    # File system type
    boot[54:62] = b"FAT12   "

    # Boot signature
    boot[510] = 0x55
    boot[511] = 0xAA

    return bytes(boot)


def create_fat() -> bytes:
    """Create an empty FAT12 table (9 sectors)."""
    fat = bytearray(SECTORS_PER_FAT * SECTOR_SIZE)

    # First two entries are reserved
    # Entry 0: media descriptor
    # Entry 1: end-of-chain marker
    # FAT12: entries 0 and 1 packed into first 3 bytes
    fat[0] = MEDIA_DESCRIPTOR
    fat[1] = 0xFF
    fat[2] = 0xFF

    return bytes(fat)


def create_root_directory() -> bytes:
    """Create an empty root directory (14 sectors)."""
    root_dir_size = (ROOT_ENTRIES * 32)
    return b"\x00" * root_dir_size


def create_disk_image(volume_label: str = "MAVICA") -> bytes:
    """Create a complete 1.44MB FAT12 disk image."""
    image = bytearray(DISK_SIZE)

    offset = 0

    # Boot sector
    boot = create_boot_sector(volume_label)
    image[offset : offset + SECTOR_SIZE] = boot
    offset += SECTOR_SIZE

    # FAT 1
    fat = create_fat()
    image[offset : offset + len(fat)] = fat
    offset += len(fat)

    # FAT 2 (copy)
    image[offset : offset + len(fat)] = fat
    offset += len(fat)

    # Root directory (already zeroed)
    root_dir = create_root_directory()
    image[offset : offset + len(root_dir)] = root_dir

    # Data area is already zeroed

    return bytes(image)


def format_floppy(device: str, volume_label: str = "MAVICA") -> bool:
    """Write a Mavica-compatible FAT12 filesystem to a floppy device.

    Returns True on success.
    """
    image = create_disk_image(volume_label)
    system = platform.system()

    try:
        if system == "Windows":
            with open(device, "wb") as f:
                f.write(image)
        else:
            # Linux/macOS: use dd for safety
            import subprocess
            result = subprocess.run(
                ["dd", f"of={device}", f"bs={SECTOR_SIZE}",
                 f"count={TOTAL_SECTORS}", "conv=notrunc"],
                input=image,
                capture_output=True,
            )
            if result.returncode != 0:
                print(f"dd error: {result.stderr.decode()}", file=sys.stderr)
                return False

        return True

    except PermissionError:
        if system == "Windows":
            print("Permission denied. Run as Administrator.", file=sys.stderr)
        else:
            print(f"Permission denied. Try: sudo mavica format {device}", file=sys.stderr)
        return False
    except OSError as e:
        print(f"Error writing to {device}: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Create Mavica-compatible FAT12 floppy format"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Create image file
    img_parser = subparsers.add_parser("image", help="Create a disk image file")
    img_parser.add_argument("-o", "--output", default="mavica_blank.img", help="Output file")
    img_parser.add_argument("-l", "--label", default="MAVICA", help="Volume label")

    # Format device
    dev_parser = subparsers.add_parser("device", help="Format a floppy device")
    dev_parser.add_argument("device", help="Floppy device path")
    dev_parser.add_argument("-l", "--label", default="MAVICA", help="Volume label")
    dev_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    args = parser.parse_args()

    if args.command == "image":
        image = create_disk_image(args.label)
        with open(args.output, "wb") as f:
            f.write(image)
        print(f"Created {args.output} ({len(image):,} bytes)")
        print(f"  Volume label: {args.label}")
        print(f"  Format: FAT12, 1.44MB, Mavica-compatible")

    elif args.command == "device":
        if not args.yes:
            print(f"WARNING: This will erase ALL data on {args.device}!")
            confirm = input("Type YES to continue: ")
            if confirm != "YES":
                print("Aborted.")
                sys.exit(1)

        print(f"Formatting {args.device}...")
        if format_floppy(args.device, args.label):
            print("Done. Disk is ready for Mavica use.")
        else:
            print("Format failed.", file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
