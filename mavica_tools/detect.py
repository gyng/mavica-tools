"""Floppy drive auto-detection across platforms.

Scans for available floppy drives on Windows, macOS, and Linux.
"""

import os
import platform
import subprocess
from dataclasses import dataclass


@dataclass
class FloppyDrive:
    """A detected floppy drive."""
    device: str         # Device path (e.g., /dev/fd0, \\.\A:)
    label: str          # Human-readable label
    removable: bool     # Whether it's removable media
    size_bytes: int     # Size in bytes (0 if unknown)


def detect_floppy_drives() -> list[FloppyDrive]:
    """Detect available floppy drives on the current platform."""
    system = platform.system()
    if system == "Linux":
        return _detect_linux()
    elif system == "Windows":
        return _detect_windows()
    elif system == "Darwin":
        return _detect_macos()
    return []


def _detect_linux() -> list[FloppyDrive]:
    """Detect floppy drives on Linux."""
    drives = []

    # Check /dev/fd* devices
    for i in range(4):
        dev = f"/dev/fd{i}"
        if os.path.exists(dev):
            drives.append(FloppyDrive(
                device=dev,
                label=f"Floppy drive {i} ({dev})",
                removable=True,
                size_bytes=0,
            ))

    # Check /sys/block for floppy devices
    try:
        for block_dev in os.listdir("/sys/block"):
            if block_dev.startswith("fd"):
                dev = f"/dev/{block_dev}"
                if dev not in [d.device for d in drives]:
                    # Check if removable
                    removable_path = f"/sys/block/{block_dev}/removable"
                    removable = False
                    if os.path.exists(removable_path):
                        with open(removable_path) as f:
                            removable = f.read().strip() == "1"

                    size_path = f"/sys/block/{block_dev}/size"
                    size_bytes = 0
                    if os.path.exists(size_path):
                        with open(size_path) as f:
                            size_bytes = int(f.read().strip()) * 512

                    drives.append(FloppyDrive(
                        device=dev,
                        label=f"Floppy {block_dev} ({dev})",
                        removable=removable,
                        size_bytes=size_bytes,
                    ))
    except OSError:
        pass

    # Also check for USB floppy drives that show up as /dev/sd*
    # These are harder to detect — check for 1.44MB removable devices
    try:
        for block_dev in os.listdir("/sys/block"):
            if not block_dev.startswith("sd"):
                continue
            removable_path = f"/sys/block/{block_dev}/removable"
            if not os.path.exists(removable_path):
                continue
            with open(removable_path) as f:
                if f.read().strip() != "1":
                    continue

            size_path = f"/sys/block/{block_dev}/size"
            if os.path.exists(size_path):
                with open(size_path) as f:
                    sectors = int(f.read().strip())
                    # 1.44MB floppy = 2880 sectors
                    if sectors == 2880:
                        dev = f"/dev/{block_dev}"
                        drives.append(FloppyDrive(
                            device=dev,
                            label=f"USB floppy ({dev})",
                            removable=True,
                            size_bytes=sectors * 512,
                        ))
    except OSError:
        pass

    return drives


def _detect_windows() -> list[FloppyDrive]:
    """Detect floppy drives on Windows."""
    drives = []

    try:
        # Use WMI via PowerShell to find floppy drives
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-WmiObject Win32_LogicalDisk | "
                "Where-Object { $_.DriveType -eq 2 } | "
                "Select-Object DeviceID, VolumeName, Size | "
                "ConvertTo-Json"
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            import json
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                data = [data]
            for disk in data:
                drive_letter = disk.get("DeviceID", "")
                volume = disk.get("VolumeName", "") or "Removable"
                size = int(disk.get("Size") or 0)
                if drive_letter:
                    drives.append(FloppyDrive(
                        device=f"\\\\.\\{drive_letter}",
                        label=f"{drive_letter} {volume}",
                        removable=True,
                        size_bytes=size,
                    ))
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass

    # Fallback: always suggest A: and B:
    if not drives:
        for letter in ("A", "B"):
            device = f"\\\\.\\{letter}:"
            drives.append(FloppyDrive(
                device=device,
                label=f"{letter}: (standard floppy)",
                removable=True,
                size_bytes=0,
            ))

    return drives


def _detect_macos() -> list[FloppyDrive]:
    """Detect floppy drives on macOS."""
    drives = []

    try:
        # Use diskutil to find external/removable disks
        result = subprocess.run(
            ["diskutil", "list", "-plist", "external"],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            import plistlib
            plist = plistlib.loads(result.stdout)
            for disk_name in plist.get("AllDisks", []):
                dev = f"/dev/{disk_name}"
                # Check size — floppy is ~1.44MB
                info_result = subprocess.run(
                    ["diskutil", "info", "-plist", dev],
                    capture_output=True, timeout=5,
                )
                if info_result.returncode == 0:
                    info = plistlib.loads(info_result.stdout)
                    size = info.get("TotalSize", 0)
                    removable = info.get("Removable", False)
                    name = info.get("MediaName", "")

                    # Floppy drives are ~1.44MB
                    if 1400000 <= size <= 1500000 or "floppy" in name.lower():
                        drives.append(FloppyDrive(
                            device=dev,
                            label=f"{name or 'Floppy'} ({dev})",
                            removable=removable,
                            size_bytes=size,
                        ))
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass

    # Fallback
    if not drives:
        for i in range(1, 5):
            dev = f"/dev/disk{i}"
            if os.path.exists(dev):
                drives.append(FloppyDrive(
                    device=dev,
                    label=f"External disk ({dev}) — verify before use",
                    removable=True,
                    size_bytes=0,
                ))

    return drives


def main():
    """CLI entry point for drive detection."""
    drives = detect_floppy_drives()
    system = platform.system()

    print(f"Floppy drive detection ({system})\n")

    if not drives:
        print("  No floppy drives detected.")
        print("\n  Tips:")
        if system == "Linux":
            print("  - Check that the floppy module is loaded: modprobe floppy")
            print("  - USB floppy drives should appear as /dev/sdX")
        elif system == "Windows":
            print("  - Check Device Manager for floppy drives")
            print(r"  - Try \\.\A: manually")
        elif system == "Darwin":
            print("  - USB floppy drives should appear in diskutil list")
        return

    print(f"  Found {len(drives)} drive(s):\n")
    for d in drives:
        size = f"{d.size_bytes:,} bytes" if d.size_bytes else "unknown size"
        print(f"  {d.device}")
        print(f"    {d.label} ({size})")
    print()


if __name__ == "__main__":
    main()
