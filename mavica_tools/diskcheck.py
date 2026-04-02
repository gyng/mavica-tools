"""Floppy disk checker — test if a disk is safe before use.

Single-pass read test with clear pass/fail verdict.
Optionally does a destructive write-verify test.
"""

import argparse
import random
import sys
from dataclasses import dataclass, field

from mavica_tools.multipass import (
    HEADS,
    SECTOR_SIZE,
    SECTORS_PER_TRACK,
    TOTAL_SECTORS,
    TRACKS,
    read_sectors,
)

# Track 0 holds boot sector, FAT, root directory — critical for camera use
CRITICAL_SECTORS = set(range(0, 33))


@dataclass
class DiskCheckResult:
    """Result of a disk check."""

    headline: str = ""
    safe: bool = False
    bad_sectors: set = field(default_factory=set)
    bad_tracks: set = field(default_factory=set)
    total_sectors: int = TOTAL_SECTORS
    tested_sectors: int = 0
    read_errors: int = 0
    write_errors: int = 0
    quick_mode: bool = False
    has_filesystem: bool = False
    file_list: list = field(default_factory=list)
    diagnosis: object = None
    elapsed_seconds: float = 0.0


def _sector_track(s: int) -> int:
    return s // (SECTORS_PER_TRACK * HEADS)


def verdict(result: DiskCheckResult) -> DiskCheckResult:
    """Fill in the headline and safe flag based on error counts."""
    critical_bad = result.bad_sectors & CRITICAL_SECTORS
    total_bad = len(result.bad_sectors)

    if total_bad == 0:
        if result.quick_mode:
            result.headline = "PASS (spot check) -- No errors in sampled tracks"
        else:
            result.headline = "PASS -- Safe for camera use (0 bad sectors)"
        result.safe = True
    elif critical_bad:
        result.headline = (
            f"FAIL -- Critical area damaged ({len(critical_bad)} bad sector(s) "
            f"in boot/FAT/directory). Do not use."
        )
        result.safe = False
    elif total_bad <= 5:
        result.headline = (
            f"CAUTION -- {total_bad} bad sector(s) in data area. Camera may lose some photos."
        )
        result.safe = False
    else:
        result.headline = f"FAIL -- {total_bad} bad sector(s). Do not use."
        result.safe = False

    result.bad_tracks = {_sector_track(s) for s in result.bad_sectors}
    return result


def _quick_check_sectors(seed: int = 42) -> set[int]:
    """Select sectors for quick spot check.

    Always includes track 0 (critical area). Then samples ~10 tracks
    spread across inner/middle/outer zones.
    """
    rng = random.Random(seed)
    sectors = set(range(0, 36))  # Track 0 (both heads)

    inner = list(range(1, 27))  # tracks 1-26
    middle = list(range(27, 54))  # tracks 27-53
    outer = list(range(54, 80))  # tracks 54-79

    sampled = rng.sample(inner, 3) + rng.sample(middle, 4) + rng.sample(outer, 3)
    for track in sampled:
        start = track * SECTORS_PER_TRACK * HEADS
        sectors.update(range(start, start + SECTORS_PER_TRACK * HEADS))

    return sectors


def check_read_only(device, on_sector=None, on_metadata_ready=None, quick=False) -> DiskCheckResult:
    """Read-only disk check. Returns DiskCheckResult with verdict."""
    import time

    t_start = time.monotonic()
    only_sectors = _quick_check_sectors() if quick else None

    # Track which sectors had actual read errors (not just zero content)
    read_error_sectors: set[int] = set()

    def _on_sector_wrapper(idx, state):
        if state == "bad":
            read_error_sectors.add(idx)
        if on_sector:
            on_sector(idx, state)

    data, errors = read_sectors(
        device,
        on_sector=_on_sector_wrapper,
        on_metadata_ready=on_metadata_ready,
        only_sectors=only_sectors,
    )

    # Bad sectors = actual read errors.
    # All-zero content in the data area (sectors 33+) is normal on a formatted disk.
    # All-zero in the critical area (sectors 0-32: boot/FAT/root dir) indicates damage.
    bad = set(read_error_sectors)
    tested = only_sectors if only_sectors else set(range(TOTAL_SECTORS))
    for s in tested & CRITICAL_SECTORS:
        sector_data = data[s * SECTOR_SIZE : (s + 1) * SECTOR_SIZE]
        if sector_data == b"\x00" * SECTOR_SIZE and s not in bad:
            bad.add(s)  # Critical sector should never be all-zero on a valid disk

    # Check for FAT12 filesystem
    file_list = []
    has_fs = False
    try:
        from mavica_tools.fat12 import file_sector_map_from_data

        boundaries = file_sector_map_from_data(bytes(data))
        if boundaries:
            has_fs = True
            file_list = [(name, len(sectors) * SECTOR_SIZE) for name, sectors in boundaries]
    except Exception:
        pass

    elapsed = time.monotonic() - t_start

    result = DiskCheckResult(
        bad_sectors=bad,
        total_sectors=TOTAL_SECTORS,
        tested_sectors=len(tested),
        read_errors=errors,
        quick_mode=quick,
        has_filesystem=has_fs,
        file_list=file_list,
        elapsed_seconds=elapsed,
    )

    # Run diagnostics (always — shows "all good" for clean disks too)
    try:
        from mavica_tools.diagnose import diagnose_errors

        sector_status = []
        for s in range(TOTAL_SECTORS):
            if only_sectors and s not in only_sectors:
                sector_status.append("good")  # untested, assume good
            elif s in bad:
                sector_status.append("blank")
            else:
                sector_status.append("good")
        result.diagnosis = diagnose_errors(sector_status=sector_status)
    except Exception:
        pass

    return verdict(result)


def _write_verify_unix(device, on_sector=None):
    """Write-verify on Linux/macOS using standard file I/O."""
    bad = set()
    write_errors = 0
    read_errors = 0

    with open(device, "r+b") as dev:
        for track in range(TRACKS):
            for head in range(HEADS):
                track_start = track * SECTORS_PER_TRACK * HEADS + head * SECTORS_PER_TRACK
                offset = track_start * SECTOR_SIZE
                track_size = SECTORS_PER_TRACK * SECTOR_SIZE

                pattern = bytes([0xAA if (track + head) % 2 == 0 else 0x55] * track_size)

                try:
                    dev.seek(offset)
                    dev.write(pattern)
                    dev.flush()
                except OSError:
                    write_errors += SECTORS_PER_TRACK
                    for s in range(track_start, track_start + SECTORS_PER_TRACK):
                        bad.add(s)
                        if on_sector:
                            on_sector(s, "bad")
                    continue

                try:
                    dev.seek(offset)
                    readback = dev.read(track_size)
                except OSError:
                    readback = b""

                for si in range(SECTORS_PER_TRACK):
                    s = track_start + si
                    expected = pattern[si * SECTOR_SIZE : (si + 1) * SECTOR_SIZE]
                    actual = (
                        readback[si * SECTOR_SIZE : (si + 1) * SECTOR_SIZE]
                        if len(readback) >= (si + 1) * SECTOR_SIZE
                        else b""
                    )

                    if actual == expected:
                        if on_sector:
                            on_sector(s, "good")
                    else:
                        bad.add(s)
                        read_errors += 1
                        if on_sector:
                            on_sector(s, "bad")

    return bad, write_errors, read_errors


def _write_verify_win32(device, on_sector=None):
    """Write-verify on Windows using Win32 API (same as format)."""
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
            raise PermissionError("Permission denied. Run as Administrator.")
        elif err == 21:
            raise OSError("Drive not ready. Is a disk inserted?")
        raise OSError(f"Cannot open device (Win32 error {err})")

    bad = set()
    write_errors = 0
    read_errors = 0

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
                raise OSError(
                    "Cannot lock volume. Close Explorer and any programs using the disk, then retry."
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

        for track in range(TRACKS):
            for head in range(HEADS):
                track_start = track * SECTORS_PER_TRACK * HEADS + head * SECTORS_PER_TRACK
                offset = track_start * SECTOR_SIZE
                track_size = SECTORS_PER_TRACK * SECTOR_SIZE

                pattern = bytes([0xAA if (track + head) % 2 == 0 else 0x55] * track_size)
                write_buf = ctypes.create_string_buffer(pattern)
                read_buf = ctypes.create_string_buffer(track_size)

                # Write
                kernel32.SetFilePointer(handle, offset, None, 0)
                written = wt.DWORD(0)
                ok = kernel32.WriteFile(handle, write_buf, track_size, ctypes.byref(written), None)
                if not ok or written.value != track_size:
                    write_errors += SECTORS_PER_TRACK
                    for s in range(track_start, track_start + SECTORS_PER_TRACK):
                        bad.add(s)
                        if on_sector:
                            on_sector(s, "bad")
                    continue

                kernel32.FlushFileBuffers(handle)

                # Read back
                kernel32.SetFilePointer(handle, offset, None, 0)
                read_bytes = wt.DWORD(0)
                ok = kernel32.ReadFile(handle, read_buf, track_size, ctypes.byref(read_bytes), None)
                readback = read_buf.raw if ok else b""

                for si in range(SECTORS_PER_TRACK):
                    s = track_start + si
                    expected = pattern[si * SECTOR_SIZE : (si + 1) * SECTOR_SIZE]
                    actual = (
                        readback[si * SECTOR_SIZE : (si + 1) * SECTOR_SIZE]
                        if len(readback) >= (si + 1) * SECTOR_SIZE
                        else b""
                    )

                    if actual == expected:
                        if on_sector:
                            on_sector(s, "good")
                    else:
                        bad.add(s)
                        read_errors += 1
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

    return bad, write_errors, read_errors


def check_write_verify(device, on_sector=None) -> DiskCheckResult:
    """Destructive write-verify test. Writes patterns and reads them back.

    WARNING: Destroys all data on the disk.
    """
    import time

    t_start = time.monotonic()
    from mavica_tools.format import _validate_device_path

    error = _validate_device_path(device)
    if error:
        return verdict(
            DiskCheckResult(
                headline=f"FAIL -- {error}",
                bad_sectors=set(range(TOTAL_SECTORS)),
                tested_sectors=0,
            )
        )

    import platform

    system = platform.system()
    bad = set()
    write_errors = 0
    read_errors = 0

    try:
        if system == "Windows":
            bad, write_errors, read_errors = _write_verify_win32(device, on_sector)
        else:
            bad, write_errors, read_errors = _write_verify_unix(device, on_sector)
    except PermissionError:
        return verdict(
            DiskCheckResult(
                headline="FAIL -- Cannot write to device (write-protected or no permission)",
                bad_sectors=set(range(TOTAL_SECTORS)),
                tested_sectors=0,
            )
        )
    except OSError as e:
        msg = str(e)
        if "write-protect" in msg.lower() or "read-only" in msg.lower():
            return verdict(
                DiskCheckResult(
                    headline="FAIL -- Disk is write-protected",
                    bad_sectors=set(range(TOTAL_SECTORS)),
                    tested_sectors=0,
                )
            )
        return verdict(
            DiskCheckResult(
                headline=f"FAIL -- {e}",
                bad_sectors=set(range(TOTAL_SECTORS)),
                tested_sectors=0,
            )
        )

    elapsed = time.monotonic() - t_start

    result = DiskCheckResult(
        bad_sectors=bad,
        total_sectors=TOTAL_SECTORS,
        tested_sectors=TOTAL_SECTORS,
        read_errors=read_errors,
        write_errors=write_errors,
        elapsed_seconds=elapsed,
    )

    # Run diagnostics (always — shows "all good" for clean disks too)
    try:
        from mavica_tools.diagnose import diagnose_errors

        sector_status = ["blank" if s in bad else "good" for s in range(TOTAL_SECTORS)]
        result.diagnosis = diagnose_errors(sector_status=sector_status)
    except Exception:
        pass

    return verdict(result)


def print_result(result: DiskCheckResult) -> None:
    """Print disk check results to stdout."""
    from mavica_tools.fun import health_bar

    good_pct = (
        100 * (result.tested_sectors - len(result.bad_sectors)) / result.tested_sectors
        if result.tested_sectors
        else 0
    )

    print(f"\n  {result.headline}\n")
    print(health_bar(good_pct))
    print(f"\n  Tested:  {result.tested_sectors}/{result.total_sectors} sectors")
    print(f"  Good:    {result.tested_sectors - len(result.bad_sectors)}")
    print(f"  Bad:     {len(result.bad_sectors)}")
    if result.elapsed_seconds > 0:
        elapsed = result.elapsed_seconds
        bytes_read = result.tested_sectors * SECTOR_SIZE
        speed_kbs = bytes_read / 1024 / elapsed if elapsed > 0 else 0
        if elapsed >= 60:
            time_str = f"{int(elapsed // 60)}m {elapsed % 60:.1f}s"
        else:
            time_str = f"{elapsed:.1f}s"
        print(f"  Time:    {time_str}  ({speed_kbs:.1f} KB/s)")
    if result.write_errors:
        print(f"  Write errors: {result.write_errors}")
    if result.bad_tracks:
        print(f"  Bad tracks: {sorted(result.bad_tracks)}")

    if result.file_list:
        print(f"\n  Files on disk ({len(result.file_list)}):")
        for name, size in result.file_list:
            print(f"    {name:<15s}  {size:>6,} bytes")

    if result.diagnosis:
        from mavica_tools.diagnose import format_diagnosis

        print("\n  Diagnosis:")
        print(format_diagnosis(result.diagnosis, rich=False))

    print()


def main():
    parser = argparse.ArgumentParser(description="Check if a floppy disk is safe for camera use")
    parser.add_argument("device", help="Floppy device (e.g. /dev/fd0, \\\\.\\A:)")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick spot check (track 0 + sampled tracks)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Destructive write-verify test (DESTROYS ALL DATA)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation for destructive tests",
    )
    args = parser.parse_args()

    if args.write:
        if not args.yes:
            print("WARNING: Write test will DESTROY ALL DATA on the disk.")
            try:
                confirm = input("Type 'yes' to continue: ")
            except EOFError, KeyboardInterrupt:
                print("\nCancelled.")
                sys.exit(1)
            if confirm.strip().lower() != "yes":
                print("Cancelled.")
                sys.exit(1)

        print(f"Write-verify test: {args.device}")
        result = check_write_verify(args.device)
    else:
        mode = "Quick check" if args.quick else "Full read check"
        print(f"{mode}: {args.device}")
        result = check_read_only(args.device, quick=args.quick)

    print_result(result)
    sys.exit(0 if result.safe else 1)


if __name__ == "__main__":
    main()
