"""Main CLI entry point for mavica-tools."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="mavica",
        description="Mavica floppy disk recovery and troubleshooting toolkit",
    )
    subparsers = parser.add_subparsers(dest="tool")

    subparsers.add_parser("multipass", help="Multi-pass floppy disk imager")
    subparsers.add_parser("carve", help="Carve JPEG images from disk images")
    subparsers.add_parser("check", help="Check JPEG files for corruption")
    subparsers.add_parser("repair", help="Repair corrupt/truncated JPEGs")
    subparsers.add_parser("swaptest", help="Cross-camera swap test tracker")

    # Parse only the first argument to determine which tool to run
    args, remaining = parser.parse_known_args()

    if args.tool == "multipass":
        from mavica_tools.multipass import main as tool_main
    elif args.tool == "carve":
        from mavica_tools.carve import main as tool_main
    elif args.tool == "check":
        from mavica_tools.check import main as tool_main
    elif args.tool == "repair":
        from mavica_tools.repair import main as tool_main
    elif args.tool == "swaptest":
        from mavica_tools.swaptest import main as tool_main
    else:
        parser.print_help()
        print("\nTools:")
        print("  mavica multipass  — Multi-pass floppy reader (merges best sectors)")
        print("  mavica carve      — Extract JPEGs from raw disk images")
        print("  mavica check      — Batch-check JPEGs for corruption")
        print("  mavica repair     — Salvage pixels from corrupt JPEGs")
        print("  mavica swaptest   — Track cross-camera swap tests")
        print("\nQuick start:")
        print("  mavica multipass read /dev/fd0 -n 5 -o my_disk")
        print("  mavica carve my_disk/merged.img -o recovered/")
        print("  mavica check recovered/")
        print("  mavica repair recovered/")
        sys.exit(0)

    # Re-run with the remaining args
    sys.argv = [f"mavica {args.tool}"] + remaining
    tool_main()


if __name__ == "__main__":
    main()
