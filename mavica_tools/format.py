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
    boot[0:3] = b"\xeb\x3c\x90"

    # OEM name (8 bytes)
    boot[3:11] = b"MAVICA  "

    # BIOS Parameter Block
    struct.pack_into("<H", boot, 11, BYTES_PER_SECTOR)  # bytes per sector
    boot[13] = SECTORS_PER_CLUSTER  # sectors per cluster
    struct.pack_into("<H", boot, 14, RESERVED_SECTORS)  # reserved sectors
    boot[16] = NUM_FATS  # number of FATs
    struct.pack_into("<H", boot, 17, ROOT_ENTRIES)  # root dir entries
    struct.pack_into("<H", boot, 19, TOTAL_SECTORS)  # total sectors
    boot[21] = MEDIA_DESCRIPTOR  # media descriptor
    struct.pack_into("<H", boot, 22, SECTORS_PER_FAT)  # sectors per FAT
    struct.pack_into("<H", boot, 24, SECTORS_PER_TRACK)  # sectors per track
    struct.pack_into("<H", boot, 26, NUM_HEADS)  # number of heads
    struct.pack_into("<I", boot, 28, 0)  # hidden sectors
    struct.pack_into("<I", boot, 32, 0)  # total sectors (32-bit, 0 = use 16-bit)

    # Extended boot record
    boot[36] = 0x00  # drive number (floppy)
    boot[37] = 0x00  # reserved
    boot[38] = 0x29  # extended boot signature
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


def _set_fat12_entry(fat: bytearray, index: int, value: int) -> None:
    """Set a FAT12 entry. FAT12 packs two 12-bit entries into 3 bytes."""
    byte_offset = (index * 3) // 2
    if index % 2 == 0:
        # Even entry: low 8 bits in byte[n], low 4 bits of byte[n+1]
        fat[byte_offset] = value & 0xFF
        fat[byte_offset + 1] = (fat[byte_offset + 1] & 0xF0) | ((value >> 8) & 0x0F)
    else:
        # Odd entry: high 4 bits of byte[n], all 8 bits of byte[n+1]
        fat[byte_offset] = (fat[byte_offset] & 0x0F) | ((value & 0x0F) << 4)
        fat[byte_offset + 1] = (value >> 4) & 0xFF


# Data area starts at sector 33 (boot=1 + FAT1=9 + FAT2=9 + rootdir=14)
DATA_START_SECTOR = 33

# FAT12 bad cluster marker
BAD_CLUSTER = 0xFF7


def create_fat(bad_sectors: list[int] | None = None) -> bytes:
    """Create a FAT12 table (9 sectors), marking bad sectors if provided.

    bad_sectors is a list of absolute sector indices (0-2879).
    Only sectors in the data area (>=33) can be marked bad.
    """
    fat = bytearray(SECTORS_PER_FAT * SECTOR_SIZE)

    # First two entries are reserved
    # Entry 0: media descriptor
    # Entry 1: end-of-chain marker
    fat[0] = MEDIA_DESCRIPTOR
    fat[1] = 0xFF
    fat[2] = 0xFF

    # Mark bad sectors in the FAT
    if bad_sectors:
        for sector in bad_sectors:
            if sector >= DATA_START_SECTOR:
                # Cluster number = sector - DATA_START_SECTOR + 2
                # (clusters 0 and 1 are reserved in FAT12)
                cluster = sector - DATA_START_SECTOR + 2
                _set_fat12_entry(fat, cluster, BAD_CLUSTER)

    return bytes(fat)


def create_root_directory() -> bytes:
    """Create an empty root directory (14 sectors)."""
    root_dir_size = ROOT_ENTRIES * 32
    return b"\x00" * root_dir_size


def create_disk_image(volume_label: str = "MAVICA", bad_sectors: list[int] | None = None) -> bytes:
    """Create a complete 1.44MB FAT12 disk image.

    If bad_sectors is provided, those clusters are marked 0xFF7 in both FATs
    so the camera will skip them.
    """
    image = bytearray(DISK_SIZE)

    offset = 0

    # Boot sector
    boot = create_boot_sector(volume_label)
    image[offset : offset + SECTOR_SIZE] = boot
    offset += SECTOR_SIZE

    # FAT 1 (with bad sector mapping)
    fat = create_fat(bad_sectors)
    image[offset : offset + len(fat)] = fat
    offset += len(fat)

    # FAT 2 (identical copy)
    image[offset : offset + len(fat)] = fat
    offset += len(fat)

    # Root directory (already zeroed)
    root_dir = create_root_directory()
    image[offset : offset + len(root_dir)] = root_dir

    # Data area is already zeroed

    return bytes(image)


def get_blocking_processes(device: str) -> list[str]:
    """Find processes that may be blocking access to a drive.

    Returns a list of process names/descriptions. Best-effort — may return
    empty list if detection fails.
    """
    if platform.system() != "Windows":
        return []

    # Extract drive letter from device path like \\.\A:
    drive_letter = ""
    for ch in device.upper():
        if ch.isalpha():
            drive_letter = ch
    if not drive_letter:
        return []

    try:
        import subprocess

        # Check for processes with open files on the drive
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-Process | Where-Object {{ $_.Path -and "
                f"(Get-Process -Id $_.Id -FileVersionInfo -ErrorAction SilentlyContinue).FileName -like '{drive_letter}:\\\\*' }} | "
                f"Select-Object -ExpandProperty Name -Unique",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [name.strip() for name in result.stdout.strip().split("\n") if name.strip()]
    except Exception:
        pass

    # Fallback: check common culprits
    blockers = []
    try:
        import subprocess

        # Check if Explorer has the drive open
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process explorer -ErrorAction SilentlyContinue | "
                "Select-Object -ExpandProperty Name",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and "explorer" in result.stdout.lower():
            blockers.append("Windows Explorer (may have drive window open)")
    except Exception:
        pass

    # Check for common antivirus
    try:
        import subprocess

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process | Where-Object { "
                "$_.Name -match 'antivirus|defender|malware|avast|avg|norton|mcafee|kaspersky|bitdefender'"
                " } | Select-Object -ExpandProperty Name -Unique",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            for name in result.stdout.strip().split("\n"):
                if name.strip():
                    blockers.append(f"{name.strip()} (antivirus may be scanning removable drives)")
    except Exception:
        pass

    return blockers


def force_dismount_volume(device: str) -> tuple[bool, str]:
    """Force-dismount a Windows volume, breaking any open handles.

    Returns (success, message).
    """
    if platform.system() != "Windows":
        return False, "Force dismount is only supported on Windows"

    import ctypes
    import ctypes.wintypes as wt

    kernel32 = ctypes.windll.kernel32

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    OPEN_EXISTING = 3
    FSCTL_DISMOUNT_VOLUME = 0x00090020
    FSCTL_LOCK_VOLUME = 0x00090018
    FSCTL_UNLOCK_VOLUME = 0x0009001C

    handle = kernel32.CreateFileW(
        device,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        return False, "Cannot open device"

    try:
        dummy = wt.DWORD(0)
        # Force dismount — invalidates all open handles to this volume
        ok = kernel32.DeviceIoControl(
            handle,
            FSCTL_DISMOUNT_VOLUME,
            None,
            0,
            None,
            0,
            ctypes.byref(dummy),
            None,
        )
        if not ok:
            return False, "Dismount failed"

        # Try to lock after dismount
        locked = kernel32.DeviceIoControl(
            handle,
            FSCTL_LOCK_VOLUME,
            None,
            0,
            None,
            0,
            ctypes.byref(dummy),
            None,
        )

        # Unlock — we just wanted to verify it's free now
        if locked:
            kernel32.DeviceIoControl(
                handle,
                FSCTL_UNLOCK_VOLUME,
                None,
                0,
                None,
                0,
                ctypes.byref(dummy),
                None,
            )

        return True, "Volume dismounted successfully"
    finally:
        kernel32.CloseHandle(handle)


def _write_windows_device(device: str, image: bytes) -> tuple[bool, str]:
    """Write to a raw Windows device using Win32 API.

    Python's open() can't write to \\\\.\\A: directly — it needs
    CreateFile with GENERIC_WRITE and the volume must be locked.
    """
    import ctypes
    import ctypes.wintypes as wt

    kernel32 = ctypes.windll.kernel32

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    FSCTL_LOCK_VOLUME = 0x00090018
    FSCTL_UNLOCK_VOLUME = 0x0009001C
    FSCTL_DISMOUNT_VOLUME = 0x00090020

    # Open the device
    handle = kernel32.CreateFileW(
        device,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error() or kernel32.GetLastError()
        if err == 5:
            return False, "Permission denied. Run as Administrator."
        elif err == 2 or err == 3:
            return False, f"Device not found: {device}"
        elif err == 21:
            return False, "Drive not ready. Is a disk inserted?"
        return False, f"Cannot open {device} (Win32 error {err})"

    try:
        import time as _time

        dummy = wt.DWORD(0)

        # Lock the volume — retry a few times as a previous operation
        # (e.g. disk checker) may still be releasing its handle
        locked = False
        for attempt in range(5):
            locked = kernel32.DeviceIoControl(
                handle,
                FSCTL_LOCK_VOLUME,
                None,
                0,
                None,
                0,
                ctypes.byref(dummy),
                None,
            )
            if locked:
                break
            _time.sleep(0.5)

        if not locked:
            # Force dismount without lock — last resort
            kernel32.DeviceIoControl(
                handle,
                FSCTL_DISMOUNT_VOLUME,
                None,
                0,
                None,
                0,
                ctypes.byref(dummy),
                None,
            )
            # Try lock one more time after dismount
            locked = kernel32.DeviceIoControl(
                handle,
                FSCTL_LOCK_VOLUME,
                None,
                0,
                None,
                0,
                ctypes.byref(dummy),
                None,
            )
            if not locked:
                return (
                    False,
                    "Cannot lock volume. Close Explorer and any programs using the disk, then retry.",
                )

        # Dismount so Windows doesn't cache stale data
        kernel32.DeviceIoControl(
            handle,
            FSCTL_DISMOUNT_VOLUME,
            None,
            0,
            None,
            0,
            ctypes.byref(dummy),
            None,
        )

        # Write the image
        written = wt.DWORD(0)
        buf = ctypes.create_string_buffer(image)
        ok = kernel32.WriteFile(
            handle,
            buf,
            len(image),
            ctypes.byref(written),
            None,
        )
        if not ok or written.value != len(image):
            err = ctypes.get_last_error() or kernel32.GetLastError()
            if err == 19:
                return False, "Disk is write-protected. Slide the write-protect tab on the floppy."
            return (
                False,
                f"Write failed (wrote {written.value}/{len(image)} bytes, Win32 error {err})",
            )

        # Flush
        kernel32.FlushFileBuffers(handle)

        # Unlock
        kernel32.DeviceIoControl(
            handle,
            FSCTL_UNLOCK_VOLUME,
            None,
            0,
            None,
            0,
            ctypes.byref(dummy),
            None,
        )

        return True, "Formatted successfully"

    finally:
        kernel32.CloseHandle(handle)


MAX_FLOPPY_SIZE = 2 * 1024 * 1024  # 2MB — generous limit for any floppy variant


def _get_device_size(device: str) -> int | None:
    """Get the size of a block device in bytes. Returns None if unknown."""
    system = platform.system()

    if system == "Windows":
        try:
            import ctypes
            import ctypes.wintypes as wt

            kernel32 = ctypes.windll.kernel32
            GENERIC_READ = 0x80000000
            FILE_SHARE_READ = 0x1
            FILE_SHARE_WRITE = 0x2
            OPEN_EXISTING = 3
            IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C

            handle = kernel32.CreateFileW(
                device,
                GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                0,
                None,
            )
            if handle == ctypes.c_void_p(-1).value:
                return None

            try:
                size = ctypes.c_longlong(0)
                returned = wt.DWORD(0)
                ok = kernel32.DeviceIoControl(
                    handle,
                    IOCTL_DISK_GET_LENGTH_INFO,
                    None,
                    0,
                    ctypes.byref(size),
                    ctypes.sizeof(size),
                    ctypes.byref(returned),
                    None,
                )
                if ok:
                    return size.value
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            pass
        return None

    elif system == "Linux":
        try:
            import fcntl
            import struct as _struct

            BLKGETSIZE64 = 0x80081272
            with open(device, "rb") as f:
                buf = b"\x00" * 8
                buf = fcntl.ioctl(f.fileno(), BLKGETSIZE64, buf)
                return _struct.unpack("Q", buf)[0]
        except Exception:
            pass
        return None

    elif system == "Darwin":
        try:
            import subprocess as _sp

            result = _sp.run(
                ["diskutil", "info", "-plist", device],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                import plistlib

                info = plistlib.loads(result.stdout)
                return info.get("TotalSize", None)
        except Exception:
            pass
        return None

    return None


def _validate_device_path(device: str) -> str | None:
    """Refuse to format anything that doesn't look like a floppy device.

    Checks device path against known-safe patterns and verifies
    disk size is floppy-sized (<=2MB). Returns an error message
    if the device is rejected, None if OK.
    """
    system = platform.system()
    d = device.strip()

    if system == "Windows":
        # Only allow \\.\A: and \\.\B: (standard floppy drive letters)
        normalized = d.upper().replace("/", "\\")
        allowed = {r"\\.\A:", r"\\.\B:"}
        if normalized not in allowed:
            if len(d) >= 2 and d[1] == ":" and d[0].upper() not in ("A", "B"):
                return (
                    f"Refusing to format {device} -- that is not a floppy drive. "
                    f"Only A: and B: are allowed. "
                    f"Use \\\\.\\A: for the floppy drive."
                )
            return (
                f"Refusing to format {device} -- does not look like a floppy device. "
                f"Expected \\\\.\\A: or \\\\.\\B:"
            )
    elif system == "Linux":
        safe_prefixes = ("/dev/fd",)
        if not any(d.startswith(p) for p in safe_prefixes):
            if d.startswith("/dev/sd"):
                pass  # USB floppy shows as /dev/sdX — size check below will catch hard drives
            else:
                return (
                    f"Refusing to format {device} -- does not look like a floppy device. "
                    f"Expected /dev/fd0 or similar."
                )
        # Block obvious system devices
        if d in (
            "/dev/sda",
            "/dev/sda1",
            "/dev/nvme0n1",
            "/dev/nvme0n1p1",
            "/dev/vda",
            "/dev/vda1",
            "/dev/xvda",
            "/dev/xvda1",
            "/dev/mmcblk0",
            "/dev/mmcblk0p1",
        ):
            return f"Refusing to format {device} -- that looks like a system disk."
    elif system == "Darwin":
        if d == "/dev/disk0" or d.startswith("/dev/disk0s"):
            return f"Refusing to format {device} -- that is the boot disk."
        if not d.startswith("/dev/disk"):
            return f"Refusing to format {device} -- expected /dev/diskN."

    # Block paths that are clearly files/directories, not devices
    if os.path.isdir(d):
        return f"Refusing to format {device} -- that is a directory, not a device."

    # Size check — reject anything larger than 2MB (no floppy is bigger)
    size = _get_device_size(d)
    if size is not None and size > MAX_FLOPPY_SIZE:
        size_mb = size / (1024 * 1024)
        return (
            f"Refusing to format {device} -- disk is {size_mb:.0f}MB, "
            f"too large to be a floppy (max {MAX_FLOPPY_SIZE // (1024 * 1024)}MB). "
            f"This looks like a hard drive or USB stick."
        )

    return None


def format_floppy_full(
    device: str, volume_label: str = "MAVICA", on_sector=None
) -> tuple[bool, str, int]:
    """Full format: zero every sector, verify, then write FAT12.

    Bad sectors found during verification are marked as 0xFF7 in the FAT
    so the camera will skip them.

    Returns (success, message, bad_sector_count).
    on_sector(sector_index, state) callback for live progress.
    """
    error = _validate_device_path(device)
    if error:
        return False, error, 0

    system = platform.system()
    bad_list: list[int] = []

    # Phase 1: Write zeros to every sector and verify
    try:
        if system == "Windows":
            ok, msg, bad_list = _full_format_win32(device, on_sector)
            if not ok:
                return False, msg, len(bad_list)
        else:
            ok, msg, bad_list = _full_format_unix(device, on_sector)
            if not ok:
                return False, msg, len(bad_list)
    except PermissionError:
        if system == "Windows":
            return False, "Permission denied. Run as Administrator.", 0
        return False, f"Permission denied. Try: sudo mavica format {device}", 0
    except FileNotFoundError:
        return False, f"Device not found: {device}", 0
    except OSError as e:
        msg = str(e)
        if "write-protect" in msg.lower() or "read-only" in msg.lower():
            return False, "Disk is write-protected. Slide the write-protect tab on the floppy.", 0
        return False, f"Error: {e}", 0

    # Phase 2: Write FAT12 filesystem with bad sectors marked in FAT
    ok, msg = format_floppy(device, volume_label, bad_sectors=bad_list or None)
    if not ok:
        return False, msg, len(bad_list)

    if bad_list:
        # Count how many bad sectors are in the data area (mappable)
        data_bad = [s for s in bad_list if s >= DATA_START_SECTOR]
        meta_bad = [s for s in bad_list if s < DATA_START_SECTOR]
        return (
            True,
            (
                f"Formatted with {len(bad_list)} bad sector(s) "
                f"({len(data_bad)} marked in FAT"
                f"{f', {len(meta_bad)} in metadata area' if meta_bad else ''})"
            ),
            len(bad_list),
        )
    return True, "Formatted successfully (all sectors verified)", 0


def _full_format_unix(device, on_sector=None):
    """Full format on Linux/macOS — write zeros, read back, verify.

    Returns (success, message, list_of_bad_sector_indices).
    """
    bad_list: list[int] = []
    zero_sector = b"\x00" * SECTOR_SIZE

    with open(device, "r+b") as dev:
        for s in range(TOTAL_SECTORS):
            if on_sector:
                on_sector(s, "reading")
            offset = s * SECTOR_SIZE

            # Write zeros
            try:
                dev.seek(offset)
                dev.write(zero_sector)
            except OSError:
                bad_list.append(s)
                if on_sector:
                    on_sector(s, "bad")
                continue

            # Read back and verify
            try:
                dev.seek(offset)
                readback = dev.read(SECTOR_SIZE)
                if readback == zero_sector:
                    if on_sector:
                        on_sector(s, "good")
                else:
                    bad_list.append(s)
                    if on_sector:
                        on_sector(s, "bad")
            except OSError:
                bad_list.append(s)
                if on_sector:
                    on_sector(s, "bad")

    return True, "", bad_list


def _full_format_win32(device, on_sector=None):
    """Full format on Windows — write zeros via Win32 API, read back, verify."""
    import ctypes
    import ctypes.wintypes as wt

    kernel32 = ctypes.windll.kernel32

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    OPEN_EXISTING = 3
    FSCTL_LOCK_VOLUME = 0x00090018
    FSCTL_UNLOCK_VOLUME = 0x0009001C
    FSCTL_DISMOUNT_VOLUME = 0x00090020

    handle = kernel32.CreateFileW(
        device,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        err = ctypes.get_last_error() or kernel32.GetLastError()
        if err == 5:
            return False, "Permission denied. Run as Administrator.", 0
        elif err == 21:
            return False, "Drive not ready. Is a disk inserted?", 0
        return False, f"Cannot open device (Win32 error {err})", 0

    bad_list: list[int] = []
    try:
        import time as _time

        dummy = wt.DWORD(0)

        locked = False
        for attempt in range(5):
            locked = kernel32.DeviceIoControl(
                handle,
                FSCTL_LOCK_VOLUME,
                None,
                0,
                None,
                0,
                ctypes.byref(dummy),
                None,
            )
            if locked:
                break
            _time.sleep(0.5)

        if not locked:
            kernel32.DeviceIoControl(
                handle,
                FSCTL_DISMOUNT_VOLUME,
                None,
                0,
                None,
                0,
                ctypes.byref(dummy),
                None,
            )
            locked = kernel32.DeviceIoControl(
                handle,
                FSCTL_LOCK_VOLUME,
                None,
                0,
                None,
                0,
                ctypes.byref(dummy),
                None,
            )
            if not locked:
                return (
                    False,
                    "Cannot lock volume. Close Explorer and any programs using the disk, then retry.",
                    [],
                )

        kernel32.DeviceIoControl(
            handle,
            FSCTL_DISMOUNT_VOLUME,
            None,
            0,
            None,
            0,
            ctypes.byref(dummy),
            None,
        )

        zero_sector = b"\x00" * SECTOR_SIZE
        zero_buf = ctypes.create_string_buffer(zero_sector)
        read_buf = ctypes.create_string_buffer(SECTOR_SIZE)

        for s in range(TOTAL_SECTORS):
            if on_sector:
                on_sector(s, "reading")

            offset = s * SECTOR_SIZE

            # Seek
            kernel32.SetFilePointer(handle, offset, None, 0)

            # Write zeros
            written = wt.DWORD(0)
            ok = kernel32.WriteFile(handle, zero_buf, SECTOR_SIZE, ctypes.byref(written), None)
            if not ok or written.value != SECTOR_SIZE:
                bad_list.append(s)
                if on_sector:
                    on_sector(s, "bad")
                continue

            kernel32.FlushFileBuffers(handle)

            # Read back
            kernel32.SetFilePointer(handle, offset, None, 0)
            read_bytes = wt.DWORD(0)
            ok = kernel32.ReadFile(handle, read_buf, SECTOR_SIZE, ctypes.byref(read_bytes), None)

            if ok and read_bytes.value == SECTOR_SIZE and read_buf.raw == zero_sector:
                if on_sector:
                    on_sector(s, "good")
            else:
                bad_list.append(s)
                if on_sector:
                    on_sector(s, "bad")

        kernel32.DeviceIoControl(
            handle,
            FSCTL_UNLOCK_VOLUME,
            None,
            0,
            None,
            0,
            ctypes.byref(dummy),
            None,
        )
    finally:
        kernel32.CloseHandle(handle)

    return True, "", bad_list


def format_floppy(
    device: str, volume_label: str = "MAVICA", bad_sectors: list[int] | None = None
) -> tuple[bool, str]:
    """Write a Mavica-compatible FAT12 filesystem to a floppy device.

    If bad_sectors is provided, those clusters are marked 0xFF7 in the FAT.

    Returns (success, message).
    """
    # Safety check — refuse to format non-floppy devices
    error = _validate_device_path(device)
    if error:
        return False, error

    image = create_disk_image(volume_label, bad_sectors=bad_sectors)
    system = platform.system()

    try:
        if system == "Windows":
            return _write_windows_device(device, image)
        else:
            # Linux/macOS: use dd for safety
            import subprocess

            result = subprocess.run(
                [
                    "dd",
                    f"of={device}",
                    f"bs={SECTOR_SIZE}",
                    f"count={TOTAL_SECTORS}",
                    "conv=notrunc",
                ],
                input=image,
                capture_output=True,
            )
            if result.returncode != 0:
                return False, f"dd error: {result.stderr.decode().strip()}"

        return True, "Formatted successfully"

    except PermissionError:
        if system == "Windows":
            return False, "Permission denied. Run as Administrator."
        else:
            return False, f"Permission denied. Try: sudo mavica format {device}"
    except FileNotFoundError:
        return False, f"Device not found: {device}"
    except OSError as e:
        msg = str(e)
        if "write-protect" in msg.lower() or "read-only" in msg.lower():
            return False, "Disk is write-protected. Slide the write-protect tab on the floppy."
        return False, f"Error writing to {device}: {e}"


def main():
    parser = argparse.ArgumentParser(description="Create Mavica-compatible FAT12 floppy format")
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
    dev_parser.add_argument(
        "--full",
        action="store_true",
        help="Full format: zero + verify every sector, then write FAT12 (slow but thorough)",
    )

    args = parser.parse_args()

    if args.command == "image":
        image = create_disk_image(args.label)
        with open(args.output, "wb") as f:
            f.write(image)
        print(f"Created {args.output} ({len(image):,} bytes)")
        print(f"  Volume label: {args.label}")
        print("  Format: FAT12, 1.44MB, Mavica-compatible")

    elif args.command == "device":
        if not args.yes:
            mode = "FULL format (zero + verify every sector)" if args.full else "Quick format"
            print(f"WARNING: {mode} will erase ALL data on {args.device}!")
            confirm = input("Type YES to continue: ")
            if confirm != "YES":
                print("Aborted.")
                sys.exit(1)

        if args.full:
            print(f"Full format: {args.device} (this takes ~2 minutes)...")
            ok, msg, bad = format_floppy_full(args.device, args.label)
            if ok:
                if bad:
                    print(f"Done with {bad} bad sector(s). Disk has defects but is formatted.")
                else:
                    print("Done. All sectors verified. Disk is ready for Mavica use.")
            else:
                print(f"Format failed: {msg}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Quick format: {args.device}...")
            ok, msg = format_floppy(args.device, args.label)
            if ok:
                print("Done. Disk is ready for Mavica use.")
            else:
                print(f"Format failed: {msg}", file=sys.stderr)
                sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
