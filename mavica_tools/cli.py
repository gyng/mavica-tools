"""Main CLI entry point for mavica-tools."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="mavica",
        description="Mavica floppy disk recovery and troubleshooting toolkit",
    )
    subparsers = parser.add_subparsers(dest="tool")

    subparsers.add_parser("import", help="Quick import: copy, tag, and go")
    subparsers.add_parser("multipass", help="Multi-pass floppy disk imager")
    subparsers.add_parser("carve", help="Carve JPEG images from disk images")
    subparsers.add_parser("check", help="Check JPEG files for corruption")
    subparsers.add_parser("repair", help="Repair corrupt/truncated JPEGs")
    subparsers.add_parser("swaptest", help="Cross-camera swap test tracker")
    subparsers.add_parser("fat12", help="FAT12 filesystem tools (ls, extract)")
    subparsers.add_parser("recover", help="Full recovery pipeline")
    subparsers.add_parser("format", help="Create Mavica-compatible FAT12 format")
    subparsers.add_parser("stamp", help="Add EXIF metadata to recovered JPEGs")
    subparsers.add_parser("detect", help="Auto-detect floppy drives")
    subparsers.add_parser("gps", help="Merge GPS track data into photos")
    subparsers.add_parser("thumb411", help="Decode .411 Mavica thumbnails")
    subparsers.add_parser("diskcheck", help="Check if a floppy disk is safe for camera use")
    subparsers.add_parser("tui", help="Launch interactive terminal UI")

    # Parse only the first argument to determine which tool to run
    args, remaining = parser.parse_known_args()

    if args.tool is None and not remaining:
        # No subcommand — launch TUI if interactive, otherwise show help
        if sys.stdin.isatty() and sys.stdout.isatty():
            from mavica_tools.tui.app import run

            run()
            return
        # Non-interactive: fall through to help text below

    if args.tool == "tui":
        from mavica_tools.tui.app import run

        run()
        return
    elif args.tool == "import":
        from mavica_tools.importcmd import main as tool_main
    elif args.tool == "multipass":
        from mavica_tools.multipass import main as tool_main
    elif args.tool == "carve":
        from mavica_tools.carve import main as tool_main
    elif args.tool == "check":
        from mavica_tools.check import main as tool_main
    elif args.tool == "repair":
        from mavica_tools.repair import main as tool_main
    elif args.tool == "swaptest":
        from mavica_tools.swaptest import main as tool_main
    elif args.tool == "fat12":
        from mavica_tools.fat12 import main as tool_main
    elif args.tool == "recover":
        from mavica_tools.recover import main as tool_main
    elif args.tool == "format":
        from mavica_tools.format import main as tool_main
    elif args.tool == "stamp":
        from mavica_tools.stamp import main as tool_main
    elif args.tool == "detect":
        from mavica_tools.detect import main as tool_main
    elif args.tool == "gps":
        from mavica_tools.gps import main as tool_main
    elif args.tool == "thumb411":
        from mavica_tools.thumb411 import main as tool_main
    elif args.tool == "diskcheck":
        from mavica_tools.diskcheck import main as tool_main
    else:
        parser.print_help()
        print("\nTools:")
        print("  mavica import     — Quick import: copy photos from floppy, tag")
        print("  mavica multipass  — Multi-pass floppy reader (merges best sectors)")
        print("  mavica carve      — Extract JPEGs from raw disk images")
        print("  mavica check      — Batch-check JPEGs for corruption")
        print("  mavica repair     — Salvage pixels from corrupt JPEGs")
        print("  mavica swaptest   — Track cross-camera swap tests")
        print("  mavica fat12      — FAT12 filesystem tools (list/extract files)")
        print("  mavica recover    — Full recovery pipeline (read+extract+check+repair)")
        print("  mavica format     — Create Mavica-compatible FAT12 floppy format")
        print("  mavica stamp      — Add EXIF metadata to recovered JPEGs")
        print("  mavica detect     — Auto-detect floppy drives")
        print("  mavica gps        — Merge GPS track data into photos (requires piexif)")
        print("  mavica thumb411   — Decode .411 Mavica thumbnails to PNG/JPG")
        print("  mavica diskcheck  — Check if a floppy disk is safe for camera use")
        print("  mavica tui        — Launch interactive terminal UI")
        print("\nQuick start:")
        print("  mavica multipass read /dev/fd0 -n 5 -o my_disk")
        print("  mavica carve my_disk/merged.img -o recovered/")
        print("  mavica check recovered/")
        print("  mavica repair recovered/")
        sys.exit(0)

    # Re-run with the remaining args
    sys.argv = [f"mavica {args.tool}", *remaining]
    tool_main()


if __name__ == "__main__":
    main()
