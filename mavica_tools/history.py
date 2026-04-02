"""Disk health history — save and compare sector maps across sessions.

Tracks sector health over time so you can see if a floppy is degrading.
Data is stored as JSON in a history file.
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime

HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".mavica-tools")
HISTORY_FILE = os.path.join(HISTORY_DIR, "disk_history.json")


@dataclass
class DiskSnapshot:
    """A point-in-time snapshot of disk health."""

    disk_label: str
    timestamp: str
    total_sectors: int
    good: int
    recovered: int
    blank: int
    conflict: int
    readable_pct: float
    notes: str = ""


def load_history(path: str = HISTORY_FILE) -> list[dict]:
    """Load disk health history."""
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def save_history(history: list[dict], path: str = HISTORY_FILE):
    """Save disk health history."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(history, f, indent=2)


def record_snapshot(
    disk_label: str,
    sector_status: list[str],
    notes: str = "",
    path: str = HISTORY_FILE,
) -> DiskSnapshot:
    """Record a disk health snapshot from a sector status list."""
    total = len(sector_status)
    good = sector_status.count("good")
    recovered = sector_status.count("recovered")
    blank = sector_status.count("blank")
    conflict = sector_status.count("conflict")
    readable_pct = 100 * (good + recovered) / total if total > 0 else 0

    snapshot = DiskSnapshot(
        disk_label=disk_label,
        timestamp=datetime.now().isoformat(),
        total_sectors=total,
        good=good,
        recovered=recovered,
        blank=blank,
        conflict=conflict,
        readable_pct=round(readable_pct, 2),
        notes=notes,
    )

    history = load_history(path)
    history.append(asdict(snapshot))
    save_history(history, path)

    return snapshot


def get_disk_history(disk_label: str, path: str = HISTORY_FILE) -> list[DiskSnapshot]:
    """Get all snapshots for a specific disk."""
    history = load_history(path)
    return [DiskSnapshot(**h) for h in history if h.get("disk_label") == disk_label]


def get_all_disks(path: str = HISTORY_FILE) -> list[str]:
    """Get list of all tracked disk labels."""
    history = load_history(path)
    return sorted(set(h.get("disk_label", "") for h in history))


def compare_snapshots(older: DiskSnapshot, newer: DiskSnapshot) -> dict:
    """Compare two snapshots and return a diff summary."""
    return {
        "disk_label": newer.disk_label,
        "time_span": f"{older.timestamp[:10]} -> {newer.timestamp[:10]}",
        "readable_change": round(newer.readable_pct - older.readable_pct, 2),
        "good_change": newer.good - older.good,
        "blank_change": newer.blank - older.blank,
        "degrading": newer.readable_pct < older.readable_pct,
    }


def print_disk_report(disk_label: str, path: str = HISTORY_FILE):
    """Print a health report for a disk."""
    snapshots = get_disk_history(disk_label, path)
    if not snapshots:
        print(f"No history found for '{disk_label}'")
        return

    print(f"Disk Health History: {disk_label}")
    print(f"{'=' * 60}\n")
    print(f"{'Date':<22} {'Good':>6} {'Recv':>6} {'Blank':>6} {'Readable':>10}")
    print(f"{'-' * 60}")

    for s in snapshots:
        date = s.timestamp[:19]
        print(f"{date:<22} {s.good:>6} {s.recovered:>6} {s.blank:>6} {s.readable_pct:>9.1f}%")

    if len(snapshots) >= 2:
        diff = compare_snapshots(snapshots[0], snapshots[-1])
        print(f"\n{'─' * 60}")
        print(f"Change over {diff['time_span']}:")
        sign = "+" if diff["readable_change"] >= 0 else ""
        print(f"  Readable: {sign}{diff['readable_change']:.1f}%")
        print(f"  Good sectors: {sign}{diff['good_change']}")

        if diff["degrading"]:
            print("\n  ⚠ This disk is degrading. Consider retiring it.")
        else:
            print("\n  Disk health is stable or improving.")


def main():
    parser = argparse.ArgumentParser(description="Disk health history tracker")
    subparsers = parser.add_subparsers(dest="command")

    # Record a snapshot
    rec_parser = subparsers.add_parser("record", help="Record a snapshot from a merged image")
    rec_parser.add_argument("label", help="Disk label (e.g., 'TDK-001')")
    rec_parser.add_argument("image", help="Merged disk image to analyze")
    rec_parser.add_argument("--notes", default="", help="Optional notes")

    # View history
    view_parser = subparsers.add_parser("view", help="View disk health history")
    view_parser.add_argument("label", nargs="?", help="Disk label (omit to list all)")

    # Compare
    cmp_parser = subparsers.add_parser("compare", help="Compare first and last snapshots")
    cmp_parser.add_argument("label", help="Disk label")

    args = parser.parse_args()

    if args.command == "record":
        from mavica_tools.multipass import merge_passes

        # Read and analyze the image
        print(f"Analyzing {args.image}...")
        _merged, status = merge_passes([args.image])
        snapshot = record_snapshot(args.label, status, notes=args.notes)
        print(f"Recorded: {snapshot.disk_label} — {snapshot.readable_pct:.1f}% readable")
        print(
            f"  Good: {snapshot.good}, Recovered: {snapshot.recovered}, "
            f"Blank: {snapshot.blank}, Conflict: {snapshot.conflict}"
        )

    elif args.command == "view":
        if args.label:
            print_disk_report(args.label)
        else:
            disks = get_all_disks()
            if not disks:
                print("No disk history recorded yet.")
                print("Use 'mavica history record <label> <image>' to start tracking.")
            else:
                print("Tracked disks:\n")
                for label in disks:
                    snapshots = get_disk_history(label)
                    latest = snapshots[-1]
                    print(
                        f"  {label:<20} {len(snapshots)} snapshot(s), "
                        f"latest: {latest.readable_pct:.1f}% readable"
                    )

    elif args.command == "compare":
        snapshots = get_disk_history(args.label)
        if len(snapshots) < 2:
            print(f"Need at least 2 snapshots to compare (have {len(snapshots)})")
            return
        diff = compare_snapshots(snapshots[0], snapshots[-1])
        print(f"Comparison for {args.label}: {diff['time_span']}")
        sign = "+" if diff["readable_change"] >= 0 else ""
        print(f"  Readable: {sign}{diff['readable_change']:.1f}%")
        if diff["degrading"]:
            print("  Status: DEGRADING")
        else:
            print("  Status: Stable/Improving")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
