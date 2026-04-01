"""Cross-camera swap test tracker.

Helps you systematically test multiple Mavica cameras and floppy disks
to isolate which component is causing problems.

The test matrix:
  - N cameras, M disks
  - Each camera writes to each disk, then each disk is read on PC
  - Results are logged and analyzed to identify the faulty component
"""

import argparse
import json
import os
import sys
from datetime import datetime

DEFAULT_DB = "swaptest_results.json"


def load_db(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"cameras": [], "disks": [], "tests": [], "created": datetime.now().isoformat()}


def save_db(db, path):
    with open(path, "w") as f:
        json.dump(db, f, indent=2)


def cmd_setup(db, args):
    """Set up cameras and disks for testing."""
    print("=== Swap Test Setup ===\n")

    if args.cameras:
        db["cameras"] = [c.strip() for c in args.cameras.split(",")]
    else:
        print("Enter camera names/labels (comma-separated):")
        print("  Example: FD7-A, FD7-B, FD88")
        line = input("> ").strip()
        db["cameras"] = [c.strip() for c in line.split(",")]

    if args.disks:
        db["disks"] = [d.strip() for d in args.disks.split(",")]
    else:
        print("\nEnter disk labels (comma-separated):")
        print("  Example: Disk-1, Disk-2, Disk-3")
        line = input("> ").strip()
        db["disks"] = [d.strip() for d in line.split(",")]

    print(f"\nRegistered {len(db['cameras'])} camera(s): {', '.join(db['cameras'])}")
    print(f"Registered {len(db['disks'])} disk(s): {', '.join(db['disks'])}")

    # Generate test plan
    total = len(db["cameras"]) * len(db["disks"])
    print(f"\nTest plan: {total} combinations to test")
    print("\nSteps:")
    step = 1
    for camera in db["cameras"]:
        for disk in db["disks"]:
            print(f"  {step}. Format {disk} in {camera}, take 5 photos, read on PC")
            step += 1

    print("\nRun 'mavica-swaptest log' to record results for each combination.")


def cmd_log(db, args):
    """Log a test result."""
    cameras = db.get("cameras", [])
    disks = db.get("disks", [])

    if not cameras or not disks:
        print("Run 'setup' first to register cameras and disks.")
        return

    if args.camera and args.disk and args.result:
        camera = args.camera
        disk = args.disk
        result = args.result
    else:
        print("=== Log Test Result ===\n")

        print("Cameras:", ", ".join(f"[{i + 1}] {c}" for i, c in enumerate(cameras)))
        ci = int(input("Camera #: ")) - 1
        camera = cameras[ci]

        print("Disks:", ", ".join(f"[{i + 1}] {d}" for i, d in enumerate(disks)))
        di = int(input("Disk #: ")) - 1
        disk = disks[di]

        print("Result: [ok] all images readable, [partial] some corrupt, [fail] all corrupt")
        result = input("Result (ok/partial/fail): ").strip().lower()

    notes = args.notes or ""

    entry = {
        "camera": camera,
        "disk": disk,
        "result": result,
        "notes": notes,
        "timestamp": datetime.now().isoformat(),
    }
    db["tests"].append(entry)

    symbol = {"ok": "OK", "partial": "WARN", "fail": "FAIL"}.get(result, "?")
    print(f"\n  Logged: [{symbol}] {camera} + {disk}")


def cmd_report(db, _args):
    """Analyze results and identify the faulty component."""
    cameras = db.get("cameras", [])
    disks = db.get("disks", [])
    tests = db.get("tests", [])

    if not tests:
        print("No test results logged yet. Run 'log' first.")
        return

    print("=== Swap Test Report ===\n")

    # Build result matrix
    matrix = {}
    for t in tests:
        key = (t["camera"], t["disk"])
        matrix[key] = t["result"]

    # Print matrix
    header = "Camera \\ Disk"
    col_width = max(len(d) for d in disks) + 2
    print(f"  {header:<20}", end="")
    for d in disks:
        print(f"{d:^{col_width}}", end="")
    print()
    print("  " + "-" * (20 + col_width * len(disks)))

    camera_fail_count = {c: 0 for c in cameras}
    disk_fail_count = {d: 0 for d in disks}

    for camera in cameras:
        print(f"  {camera:<20}", end="")
        for disk in disks:
            result = matrix.get((camera, disk), "—")
            symbol = {
                "ok": " . ",
                "partial": " ? ",
                "fail": " X ",
            }.get(result, f" {result[:1]} ")
            print(f"{symbol:^{col_width}}", end="")

            if result in ("partial", "fail"):
                camera_fail_count[camera] += 1
                disk_fail_count[disk] += 1
        print()

    # Analysis
    print("\n--- Analysis ---\n")

    total_combos = len(cameras) * len(disks)
    tested = len(matrix)
    print(f"  Tested: {tested}/{total_combos} combinations")

    if tested < total_combos:
        missing = []
        for c in cameras:
            for d in disks:
                if (c, d) not in matrix:
                    missing.append(f"{c} + {d}")
        print(f"  Missing: {', '.join(missing)}")
        print()

    # Identify patterns
    all_ok = all(r == "ok" for r in matrix.values())
    if all_ok:
        print("  All combinations passed! The issue may be with your PC floppy drive.")
        print("  Try a different USB floppy drive or an internal drive.")
        return

    # Check if failures cluster by camera
    for camera in cameras:
        cam_results = [matrix.get((camera, d)) for d in disks if (camera, d) in matrix]
        cam_fails = sum(1 for r in cam_results if r in ("partial", "fail"))
        cam_total = len(cam_results)
        if cam_total > 0 and cam_fails == cam_total and cam_total >= 2:
            print(f"  >>> ALL disks fail with {camera} — this camera likely has a bad write head.")
            print("      Clean the head with IPA, or the drive mechanism may need service.\n")
        elif cam_fails > 0:
            print(f"  {camera}: {cam_fails}/{cam_total} failures")

    # Check if failures cluster by disk
    for disk in disks:
        disk_results = [matrix.get((c, disk)) for c in cameras if (c, disk) in matrix]
        disk_fails = sum(1 for r in disk_results if r in ("partial", "fail"))
        disk_total = len(disk_results)
        if disk_total > 0 and disk_fails == disk_total and disk_total >= 2:
            print(f"  >>> ALL cameras fail with {disk} — this disk is likely bad. Replace it.\n")
        elif disk_fails > 0:
            print(f"  {disk}: {disk_fails}/{disk_total} failures")

    # Check for single-cell failures (camera+disk interaction)
    single_fails = []
    for (c, d), r in matrix.items():
        if r in ("partial", "fail"):
            c_total_fails = camera_fail_count[c]
            d_total_fails = disk_fail_count[d]
            if c_total_fails == 1 and d_total_fails == 1:
                single_fails.append((c, d))

    if single_fails:
        print("  Isolated failures (only this specific combo fails):")
        for c, d in single_fails:
            print(
                f"    {c} + {d} — may be a head alignment mismatch. Try re-formatting the disk in this camera."
            )


def cmd_status(db, _args):
    """Show what's been tested so far."""
    cameras = db.get("cameras", [])
    disks = db.get("disks", [])
    tests = db.get("tests", [])

    tested = set()
    for t in tests:
        tested.add((t["camera"], t["disk"]))

    total = len(cameras) * len(disks)
    print(f"Progress: {len(tested)}/{total} combinations tested\n")

    print("Remaining:")
    for c in cameras:
        for d in disks:
            if (c, d) not in tested:
                print(f"  - {c} + {d}")


def main():
    parser = argparse.ArgumentParser(
        description="Cross-camera swap test tracker for Mavica troubleshooting"
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="Test database file (JSON)")
    subparsers = parser.add_subparsers(dest="command")

    setup_p = subparsers.add_parser("setup", help="Set up cameras and disks")
    setup_p.add_argument("--cameras", help="Camera names, comma-separated")
    setup_p.add_argument("--disks", help="Disk labels, comma-separated")

    log_p = subparsers.add_parser("log", help="Log a test result")
    log_p.add_argument("--camera", help="Camera name")
    log_p.add_argument("--disk", help="Disk label")
    log_p.add_argument("--result", choices=["ok", "partial", "fail"], help="Test result")
    log_p.add_argument("--notes", default="", help="Optional notes")

    subparsers.add_parser("report", help="Analyze results and find the culprit")
    subparsers.add_parser("status", help="Show testing progress")

    args = parser.parse_args()
    db = load_db(args.db)

    commands = {
        "setup": cmd_setup,
        "report": cmd_report,
        "log": cmd_log,
        "status": cmd_status,
    }

    if args.command in commands:
        commands[args.command](db, args)
        save_db(db, args.db)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
