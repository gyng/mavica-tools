"""Generate SVG screenshots of all TUI screens for README documentation.

Usage:
    uv run python scripts/generate_screenshots.py            # all screens
    uv run python scripts/generate_screenshots.py home check  # specific screens only
"""

import asyncio
import os
import random
import sys

from textual.widgets import Button, DataTable, Input, ProgressBar, RichLog, Static

# Fixed size for consistent screenshots
SCREENSHOT_SIZE = (120, 36)
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots")
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")


# ── Per-screen setup functions ──────────────────────────────────────────────
# Each receives (app, pilot) after the screen is mounted and paused.


async def setup_home(app, pilot):
    """Home screen — just needs deterministic trivia."""
    pass  # random already seeded


async def setup_import_workflow(app, pilot):
    from mavica_tools.tui.widgets.defrag_map import DefragMap
    from mavica_tools.tui.widgets.drive_input import DriveInput
    from mavica_tools.tui.widgets.image_preview import ImagePreview

    screen = app.screen
    src = screen.query_one("#drive-input", DriveInput)
    src.value = "A:\\"
    screen.query_one("#output-dir", Input).value = "mavica_out/import_2025-03-15_143022"
    table = screen.query_one("#results-table", DataTable)
    table.add_row("OK", "MVC-001.JPG", "94.2 KB", "2001-07-04")
    table.add_row("OK", "MVC-002.JPG", "87.6 KB", "2001-07-04")
    table.add_row("OK", "MVC-003.JPG", "91.1 KB", "2001-07-04")
    table.add_row("OK", "MVC-004.JPG", "88.3 KB", "2001-07-04")
    table.add_row("OK", "MVC-005.JPG", "93.7 KB", "2001-07-04")

    # Show a real photo in the preview (set_pil_image avoids async race)
    fixture_jpg = os.path.join(FIXTURES_DIR, "MVC-004F.JPG")
    if os.path.exists(fixture_jpg):
        from PIL import Image

        img = Image.open(fixture_jpg)
        screen.query_one("#preview", ImagePreview).set_pil_image(img, "MVC-004F.JPG")

    # Populate defrag map showing completed read
    defrag = screen.query_one("#defrag-map", DefragMap)
    for i in range(2880):
        defrag.update_sector(i, "good")

    screen.query_one("#status", Static).update(
        "  [bold #33ff33]Done![/] 5 photos imported (2 JPEGs, 3 thumbnails)"
    )

    # Enable post-import buttons
    for btn_id in ("#btn-next-disk", "#btn-stamp", "#btn-gps"):
        screen.query_one(btn_id, Button).disabled = False

    await pilot.pause()


async def setup_multipass(app, pilot):
    from mavica_tools.tui.widgets.defrag_map import DefragMap

    device_input = app.screen.query_one("#device-path", Input)
    device_input.value = "/dev/fd0"
    app.screen.query_one("#output-dir", Input).value = "mavica_out/disk_images"
    # Populate the defrag map with a realistic mid-read pattern
    defrag = app.screen.query_one("#defrag-map", DefragMap)
    for i in range(0, 1800):
        defrag.update_sector(i, "good")
    for i in range(1800, 1830):
        defrag.update_sector(i, "bad")
    for i in range(1830, 2100):
        defrag.update_sector(i, "recovered")
    for i in range(2100, 2120):
        defrag.update_sector(i, "bad")
    for i in range(2120, 2400):
        defrag.update_sector(i, "good")
    defrag.update_sector(2400, "reading")

    # Add file boundaries (simulated Mavica floppy layout)
    defrag.set_file_boundaries(
        [
            ("MVC-001F.JPG", list(range(33, 115))),
            ("MVC-002F.JPG", list(range(115, 183))),
            ("MVC-004F.JPG", list(range(183, 253))),
            ("MVC-006F.JPG", list(range(253, 353))),
            ("MVC-015F.JPG", list(range(353, 433))),
        ]
    )

    log = app.screen.query_one("#log", RichLog)
    log.write("[bold]Pass 2/5[/]  2400/2880 sectors read")
    log.write("  [green]2250 good[/]  [red]50 bad[/]  [#33aaff]270 recovered[/]")

    await pilot.pause()


async def setup_repair(app, pilot):
    app.screen.query_one("#source-path", Input).value = "mavica_out/extracted/"
    app.screen.query_one("#output-dir", Input).value = "mavica_out/repaired/"
    table = app.screen.query_one("#results-table", DataTable)
    table.add_row("[green]REPAIRED[/]", "MVC-003.JPG", "Pillow truncation tolerance")
    table.add_row("[yellow]PARTIAL[/]", "MVC-005.JPG", "Truncated before zero-byte run")
    await pilot.pause()


async def setup_recover_image(app, pilot):
    from mavica_tools.tui.widgets.image_preview import ImagePreview

    screen = app.screen
    screen.query_one("#image-path", Input).value = "mavica_out/disk_images/merged.img"
    screen.query_one("#output-dir", Input).value = "mavica_out/recovered/"
    table = screen.query_one("#results-table", DataTable)
    table.add_row(
        "[green]\u25cf[/]", "[green]OK[/]", "MVC-001F.JPG", "41,923", "0x008400", "2001-07-04"
    )
    table.add_row(
        "[green]\u25cf[/]", "[green]OK[/]", "MVC-002F.JPG", "34,579", "0x01DA00", "2001-07-04"
    )
    table.add_row(
        "[green]\u25cf[/]", "[green]OK[/]", "MVC-004F.JPG", "35,903", "0x033200", "2001-07-04"
    )
    table.add_row(
        "[green]\u25cf[/]", "[green]OK[/]", "MVC-006F.JPG", "50,994", "0x049200", "2001-07-04"
    )
    table.add_row(
        "[green]\u25cf[/]", "[green]OK[/]", "MVC-015F.JPG", "40,547", "0x05C400", "2001-07-04"
    )

    # Show a real photo in the preview (use set_pil_image to avoid async race)
    fixture_jpg = os.path.join(FIXTURES_DIR, "MVC-006F.JPG")
    if os.path.exists(fixture_jpg):
        from PIL import Image

        img = Image.open(fixture_jpg)
        screen.query_one("#preview", ImagePreview).set_pil_image(img, "MVC-006F.JPG")

    await pilot.pause()


async def setup_stamp(app, pilot):
    from textual.widgets import Select

    screen = app.screen
    with screen.prevent(Input.Changed):
        screen.query_one("#source-path", Input).value = "mavica_out/import_2001-07-04/"

    # Simulate file list with EXIF preview
    table = screen.query_one("#results-table", DataTable)
    table.clear()
    table.add_row(
        "[green]\u25cf[/]",
        "MVC-001.JPG",
        "94KB",
        "[dim]No EXIF[/]",
        "Sony Mavica MVC-FD7 | 2001-07-04",
    )
    table.add_row(
        "[green]\u25cf[/]",
        "MVC-002.JPG",
        "88KB",
        "[dim]No EXIF[/]",
        "Sony Mavica MVC-FD7 | 2001-07-04",
    )
    table.add_row(
        "[green]\u25cf[/]",
        "MVC-003.JPG",
        "91KB",
        "[dim]No EXIF[/]",
        "Sony Mavica MVC-FD7 | 2001-07-04",
    )
    table.add_row(
        "[green]\u25cf[/]",
        "MVC-004.JPG",
        "87KB",
        "Sony | FD7 | 2001-07-04",
        "[dim]skip (has EXIF)[/]",
    )
    table.add_row(
        "[green]\u25cf[/]",
        "MVC-005.JPG",
        "93KB",
        "[dim]No EXIF[/]",
        "Sony Mavica MVC-FD7 | 2001-07-04",
    )

    # Set camera model
    try:
        screen.query_one("#camera-model-select", Select).value = "fd7"
    except Exception:
        pass

    screen.query_one("#btn-stamp", Button).label = "Tag 5 (F2)"

    # Show a real photo in the preview (set_pil_image avoids async race)
    from mavica_tools.tui.widgets.image_preview import ImagePreview

    fixture_jpg = os.path.join(FIXTURES_DIR, "MVC-002F.JPG")
    if os.path.exists(fixture_jpg):
        from PIL import Image

        img = Image.open(fixture_jpg)
        screen.query_one("#preview", ImagePreview).set_pil_image(img, "MVC-002F.JPG")

    await pilot.pause()


async def setup_format(app, pilot):
    from mavica_tools.tui.widgets.defrag_map import DefragMap
    from mavica_tools.tui.widgets.drive_input import DriveInput

    screen = app.screen
    screen.query_one("#drive-input", DriveInput).value = "A:\\"

    # Simulate a completed quick format
    defrag = screen.query_one("#defrag-map", DefragMap)
    for i in range(33):
        defrag.update_sector(i, "good")

    screen.query_one("#progress", ProgressBar).update(total=33, progress=33)

    log = screen.query_one("#log", RichLog)
    log.write("[bold]Quick format: A:\\ \u2192 MAVICA[/]")
    log.write("  Boot sector written (sector 0)")
    log.write("  FAT1 + FAT2 written (sectors 1\u201318)")
    log.write("  Root directory cleared (sectors 19\u201332)")
    log.write("[bold #33ff33]Format complete![/] Disk ready for Mavica use.")

    await pilot.pause()


async def setup_gps(app, pilot):
    from mavica_tools.tui.widgets.track_map import TrackMap

    screen = app.screen

    # Set input values using prevent() to suppress on_input_changed auto-listing
    photos_input = screen.query_one("#photos-path", Input)
    gpx_input = screen.query_one("#gpx-path", Input)
    with screen.prevent(Input.Changed):
        photos_input.value = "mavica_out/import_2001-07-04/"
        gpx_input.value = "tracks/2001-07-04_walk.gpx"

    # Simulate a previewed state with matched photos
    table = screen.query_one("#results-table", DataTable)
    table.clear()
    table.columns.clear()
    table.add_columns("", "Filename", "Size", "Date", "Location", "Offset")
    table.add_row(
        "[green]\u25cf[/]",
        "MVC-001.JPG",
        "94KB",
        "07-04 10:30",
        "[green]35.681, 139.767[/] [dim](o)[/]",
        "12s",
    )
    table.add_row(
        "[green]\u25cf[/]", "MVC-002.JPG", "88KB", "07-04 10:35", "[green]35.682, 139.768[/]", "8s"
    )
    table.add_row(
        "[green]\u25cf[/]", "MVC-003.JPG", "91KB", "07-04 10:41", "[green]35.684, 139.770[/]", "23s"
    )
    table.add_row(
        "[green]\u25cf[/]", "MVC-004.JPG", "87KB", "07-04 10:48", "[green]35.686, 139.772[/]", "45s"
    )
    table.add_row(
        "[dim]\u25cb[/]",
        "[dim]MVC-005.JPG[/]",
        "[dim]93KB[/]",
        "[dim]07-04 10:55[/]",
        "[dim]-[/]",
        "[dim]-[/]",
    )
    table.add_row(
        "[green]\u25cf[/]", "MVC-006.JPG", "90KB", "07-04 11:02", "[green]35.689, 139.775[/]", "18s"
    )
    table.add_row(
        "[green]\u25cf[/]", "MVC-007.JPG", "86KB", "07-04 11:08", "[green]35.690, 139.776[/]", "31s"
    )
    table.add_row(
        "[green]\u25cf[/]", "MVC-008.JPG", "95KB", "07-04 11:15", "[green]35.692, 139.778[/]", "9s"
    )

    # Populate track map with a simulated walk through Tokyo
    track_map = screen.query_one("#track-map", TrackMap)
    import math

    track_pts = []
    for i in range(100):
        t = i / 99.0
        lat = 35.680 + t * 0.015 + math.sin(t * 6) * 0.001
        lon = 139.766 + t * 0.014 + math.cos(t * 4) * 0.001
        track_pts.append((lat, lon))
    track_map.set_track(track_pts)
    match_pts = [
        (35.681, 139.767),
        (35.682, 139.768),
        (35.684, 139.770),
        (35.686, 139.772),
        None,
        (35.689, 139.775),
        (35.690, 139.776),
        (35.692, 139.778),
    ]
    track_map.set_matches(match_pts)
    track_map.highlight_index = 0

    # Fix button labels and enable buttons
    screen.query_one("#btn-preview", Button).label = "Preview 7 (p)"
    screen.query_one("#btn-preview", Button).disabled = False
    screen.query_one("#btn-merge", Button).label = "Merge 7 (F2)"
    screen.query_one("#btn-merge", Button).disabled = False
    screen.query_one("#btn-map", Button).disabled = False
    screen.query_one("#btn-map", Button).label = "Open Map"

    # Status line
    screen.query_one("#status", Static).update(
        "  [bold]Preview:[/] [green]7[/]/8 matched, [dim]1 no match[/]  [dim](dry run \u2014 no files modified)[/]"
    )

    screen.query_one("#progress", ProgressBar).update(total=8, progress=8)

    await pilot.pause()


async def setup_diskcheck(app, pilot):
    from mavica_tools.tui.widgets.defrag_map import DefragMap
    from mavica_tools.tui.widgets.drive_input import DriveInput

    screen = app.screen
    screen.query_one("#drive-input", DriveInput).value = "A:\\"

    # Simulate a completed check with some bad sectors
    defrag = screen.query_one("#defrag-map", DefragMap)
    for i in range(2880):
        if i in (845, 846, 847, 1203, 1204):
            defrag.update_sector(i, "bad")
        elif i in (1500, 1501, 1502, 1503):
            defrag.update_sector(i, "marked")
        else:
            defrag.update_sector(i, "good")

    # Add file boundaries
    defrag.set_file_boundaries(
        [
            ("MVC-001F.JPG", list(range(33, 115))),
            ("MVC-002F.JPG", list(range(115, 183))),
            ("MVC-004F.JPG", list(range(183, 253))),
            ("MVC-006F.JPG", list(range(253, 353))),
            ("MVC-015F.JPG", list(range(353, 433))),
        ]
    )

    screen.query_one("#progress", ProgressBar).update(total=2880, progress=2880)

    # Verdict
    verdict = screen.query_one("#verdict", Static)
    verdict.update(
        "[bold #ffaa00]\u26a0  CAUTION[/]  [bold]Disk has 5 bad sectors + 4 marked bad in FAT[/]\n"
        "  [dim]This disk is degrading. Copy photos off immediately and retire the disk.[/]"
    )

    log = screen.query_one("#log", RichLog)
    log.write("[bold]Full check complete[/]  2880 sectors tested")
    log.write("  [green]2871 good[/]  [red]5 bad[/]  [#ffaa00]4 marked[/]")
    log.write("  Speed: 14.2 KB/s  Duration: 3m 22s")
    log.write("  Files: MVC-001F.JPG MVC-002F.JPG MVC-004F.JPG MVC-006F.JPG MVC-015F.JPG")

    await pilot.pause()


async def setup_thumb411(app, pilot):

    screen = app.screen
    with screen.prevent(Input.Changed):
        screen.query_one("#source-path", Input).value = "mavica_out/import_2001-07-04/"

    # Populate file table with .411 entries
    table = screen.query_one("#results-table", DataTable)
    table.clear()
    table.add_row("[green]\u25cf[/]", "MVC-001F.411", "5.2KB", "")
    table.add_row("[green]\u25cf[/]", "MVC-002F.411", "5.1KB", "")
    table.add_row("[green]\u25cf[/]", "MVC-003F.411", "5.3KB", "")
    table.add_row("[green]\u25cf[/]", "MVC-004F.411", "5.0KB", "")
    table.add_row("[green]\u25cf[/]", "MVC-005F.411", "5.2KB", "")
    table.add_row("[green]\u25cf[/]", "MVC-006F.411", "5.1KB", "")

    screen.query_one("#btn-convert", Button).label = "Convert 6 files"

    # Show a real .411 thumbnail preview
    from mavica_tools.tui.widgets.image_preview import ImagePreview

    fixture_411 = os.path.join(FIXTURES_DIR, "MVC-004F.411")
    if os.path.exists(fixture_411):
        try:
            from mavica_tools.thumb411 import decode_411

            img = decode_411(fixture_411)
            if img:
                screen.query_one("#preview-original", ImagePreview).set_pil_image(
                    img, "MVC-004F.411"
                )
        except Exception:
            pass

    log = screen.query_one("#log", RichLog)
    log.write("[dim]6 .411 file(s) found[/]")

    await pilot.pause()


async def setup_swaptest(app, pilot):
    screen = app.screen

    with screen.prevent(Input.Changed):
        screen.query_one("#cameras-input", Input).value = "FD7, FD73, FD88"
        screen.query_one("#disks-input", Input).value = "Maxell MF2HD, Sony 2HD, TDK MF2HD"

    # Populate matrix table
    table = screen.query_one("#matrix-table", DataTable)
    table.clear()
    table.columns.clear()
    table.add_columns("", "Maxell MF2HD", "Sony 2HD", "TDK MF2HD")
    table.add_row("[bold]FD7[/]", "[green]OK[/]", "[green]OK[/]", "[yellow]PARTIAL[/]")
    table.add_row("[bold]FD73[/]", "[green]OK[/]", "[red]FAIL[/]", "[green]OK[/]")
    table.add_row("[bold]FD88[/]", "[yellow]PARTIAL[/]", "[green]OK[/]", "")

    analysis = screen.query_one("#analysis", Static)
    analysis.update(
        "[bold]Analysis:[/] 8/9 tested (89%)\n"
        "  [red]Sony 2HD + FD73[/]: fails consistently \u2192 likely disk/camera incompatibility\n"
        "  [yellow]TDK MF2HD + FD7[/]: partial reads \u2192 try cleaning heads"
    )

    log = screen.query_one("#log", RichLog)
    log.write("Matrix loaded: 3 cameras \u00d7 3 disks")

    await pilot.pause()


# ── Screen registry ─────────────────────────────────────────────────────────
# (filename, screen_id_or_class, setup_function)


def _build_screen_list():
    """Build the list of screens to screenshot."""
    from mavica_tools.tui.screens.swaptest import SwapTestScreen

    return [
        # (filename, screen_id or class instance, setup_fn)
        ("home.svg", "home", setup_home),
        ("import_workflow.svg", "import_workflow", setup_import_workflow),
        ("multipass.svg", "multipass", setup_multipass),
        ("recover_image.svg", "recover_image", setup_recover_image),
        ("repair.svg", "repair", setup_repair),
        ("stamp.svg", "stamp", setup_stamp),
        ("format.svg", "format", setup_format),
        ("gps.svg", "gps", setup_gps),
        ("diskcheck.svg", "diskcheck", setup_diskcheck),
        ("thumb411.svg", "thumb411", setup_thumb411),
        ("swaptest.svg", SwapTestScreen, setup_swaptest),
    ]


async def capture_screen(filename, screen_id_or_class, setup_fn, output_dir):
    """Capture a single screen screenshot."""
    from mavica_tools.tui.app import MavicaApp

    random.seed(42)

    app = MavicaApp()
    async with app.run_test(size=SCREENSHOT_SIZE) as pilot:
        await pilot.pause()

        # Navigate to target screen
        if isinstance(screen_id_or_class, str):
            await app.push_screen(screen_id_or_class)
        else:
            await app.push_screen(screen_id_or_class())
        await pilot.pause()

        # Run screen-specific setup
        try:
            await setup_fn(app, pilot)
        except Exception as e:
            print(f"  Warning: setup for {filename} raised {e}")

        await pilot.pause()

        # Save screenshot
        path = app.save_screenshot(filename, path=output_dir)
        return path


async def main():
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    screens = _build_screen_list()

    # Filter to requested screens if args provided
    if len(sys.argv) > 1:
        requested = set(sys.argv[1:])
        screens = [
            (f, s, fn)
            for f, s, fn in screens
            if f.replace(".svg", "") in requested or (isinstance(s, str) and s in requested)
        ]

    print(f"Generating {len(screens)} screenshots to {SCREENSHOTS_DIR}/")

    for filename, screen_id, setup_fn in screens:
        try:
            await capture_screen(filename, screen_id, setup_fn, SCREENSHOTS_DIR)
            print(f"  {filename}")
        except Exception as e:
            print(f"  {filename} FAILED: {e}")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
