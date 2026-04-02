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
    screen.query_one("#output-dir", Input).value = "mavica_out/import_2001-07-04_103000"

    # List real fixture files in the table
    table = screen.query_one("#results-table", DataTable)
    fixture_files = sorted(f for f in os.listdir(FIXTURES_DIR) if f.endswith((".JPG", ".411")))
    for name in fixture_files:
        size_kb = os.path.getsize(os.path.join(FIXTURES_DIR, name)) / 1024
        table.add_row("[green]OK[/]", name, f"{size_kb:.1f} KB", "2001-07-04")

    # Show the first JPEG (highlighted row) in preview
    first_jpg = next((f for f in fixture_files if f.endswith(".JPG")), None)
    if first_jpg:
        from PIL import Image

        img = Image.open(os.path.join(FIXTURES_DIR, first_jpg))
        screen.query_one("#preview", ImagePreview).set_pil_image(img, first_jpg)

    # Populate defrag map from the real disk image
    from mavica_tools.fat12 import file_sector_map, parse_disk_image

    disk_path = os.path.join(FIXTURES_DIR, "disk_with_photos.img")
    defrag = screen.query_one("#defrag-map", DefragMap)
    if os.path.exists(disk_path):
        files_on_disk, fat, data = parse_disk_image(disk_path)
        for i in range(2880):
            defrag.update_sector(i, "good")
        defrag.set_file_boundaries(file_sector_map(disk_path))

    jpegs = [f for f in fixture_files if f.endswith(".JPG")]
    thumbs = [f for f in fixture_files if f.endswith(".411")]
    screen.query_one("#status", Static).update(
        f"  [bold #33ff33]Done![/] {len(fixture_files)} files imported "
        f"({len(jpegs)} JPEGs, {len(thumbs)} thumbnails)"
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

    # Use real file boundaries from fixture disk image
    from mavica_tools.fat12 import file_sector_map

    disk_path = os.path.join(FIXTURES_DIR, "disk_with_photos.img")
    if os.path.exists(disk_path):
        defrag.set_file_boundaries(file_sector_map(disk_path))

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
    disk_path = os.path.join(FIXTURES_DIR, "disk_with_photos.img")
    screen.query_one("#image-path", Input).value = disk_path
    screen.query_one("#output-dir", Input).value = "mavica_out/recovered/"

    # Populate table from real disk image FAT12 data
    from mavica_tools.fat12 import parse_disk_image

    table = screen.query_one("#results-table", DataTable)
    if os.path.exists(disk_path):
        files, fat, data = parse_disk_image(disk_path)
        for f in files:
            sel = "[green]\u25cf[/]"
            status = "[green]OK[/]"
            if f.is_deleted:
                sel = "[dim]\u25cb[/]"
                status = "[red]DEL[/]"
            table.add_row(
                sel, status, f.name, f"{f.size:,}", f"0x{f.start_cluster * 512:06X}", f.date_str
            )

    # Show first JPEG in preview
    first_jpg = os.path.join(FIXTURES_DIR, "MVC-001F.JPG")
    if os.path.exists(first_jpg):
        from PIL import Image

        img = Image.open(first_jpg)
        screen.query_one("#preview", ImagePreview).set_pil_image(img, "MVC-001F.JPG")

    await pilot.pause()


async def setup_stamp(app, pilot):
    from textual.widgets import Select

    from mavica_tools.tui.widgets.image_preview import ImagePreview

    screen = app.screen
    with screen.prevent(Input.Changed):
        screen.query_one("#source-path", Input).value = FIXTURES_DIR

    # List real fixture JPEGs in the table
    table = screen.query_one("#results-table", DataTable)
    table.clear()
    fixture_jpegs = sorted(f for f in os.listdir(FIXTURES_DIR) if f.endswith(".JPG"))
    for name in fixture_jpegs:
        size_kb = os.path.getsize(os.path.join(FIXTURES_DIR, name)) / 1024
        table.add_row(
            "[green]\u25cf[/]",
            name,
            f"{size_kb:.0f}KB",
            "[dim]No EXIF[/]",
            "Sony Mavica MVC-FD7 | 2001-07-04",
        )

    # Set camera model
    try:
        screen.query_one("#camera-model-select", Select).value = "fd7"
    except Exception:
        pass

    n = len(fixture_jpegs)
    screen.query_one("#btn-stamp", Button).label = f"Tag {n} (F2)"

    # Show a different photo than import (MVC-006F for variety)
    fixture_jpg = os.path.join(FIXTURES_DIR, "MVC-006F.JPG")
    if os.path.exists(fixture_jpg):
        from PIL import Image

        img = Image.open(fixture_jpg)
        screen.query_one("#preview", ImagePreview).set_pil_image(img, "MVC-006F.JPG")

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
    from mavica_tools.gps import match_photos_to_track, parse_gpx
    from mavica_tools.tui.widgets.image_preview import ImagePreview
    from mavica_tools.tui.widgets.track_map import TrackMap

    screen = app.screen

    gpx_path = os.path.join(FIXTURES_DIR, "track_2001-07-04.gpx")
    with screen.prevent(Input.Changed):
        screen.query_one("#photos-path", Input).value = FIXTURES_DIR
        screen.query_one("#gpx-path", Input).value = gpx_path

    # Run real matching against fixture files
    fixture_jpegs = sorted(
        os.path.join(FIXTURES_DIR, f) for f in os.listdir(FIXTURES_DIR) if f.endswith(".JPG")
    )
    track = parse_gpx(gpx_path) if os.path.exists(gpx_path) else []
    matches = match_photos_to_track(fixture_jpegs, track, tolerance_seconds=300) if track else []

    # Populate table with real match results
    table = screen.query_one("#results-table", DataTable)
    table.clear()
    table.columns.clear()
    table.add_columns("", "Filename", "Size", "Date", "Location", "Offset")
    matched_count = 0
    match_coords = []
    for i, (path, match) in enumerate(zip(fixture_jpegs, matches)):
        name = os.path.basename(path)
        size_kb = os.path.getsize(path) / 1024
        from mavica_tools.utils import get_photo_timestamp

        ts = get_photo_timestamp(path)
        date_str = ts.strftime("%m-%d %H:%M") if ts else "?"
        if match:
            matched_count += 1
            loc = f"[green]{match.point.lat:.3f}, {match.point.lon:.3f}[/]"
            if i == 0:
                loc += " [dim](o)[/]"
            secs = match.offset_seconds
            offset = f"{secs / 60:.0f}min" if secs >= 60 else f"{secs:.0f}sec"
            if match.interpolated and match.nearest_distance_m > 0:
                offset += f" ~{match.nearest_distance_m:.0f}m"
            match_coords.append((match.point.lat, match.point.lon))
        else:
            loc = "[dim]-[/]"
            offset = "[dim]-[/]"
            match_coords.append(None)
        table.add_row("[green]\u25cf[/]", name, f"{size_kb:.0f}KB", date_str, loc, offset)

    # Populate track map with real data
    track_map = screen.query_one("#track-map", TrackMap)
    if track:
        track_map.set_track([(p.lat, p.lon) for p in track])
        track_map.set_matches(match_coords)
        track_map.highlight_index = 0

    # Show MVC-015F in preview (different from other screens)
    fixture_jpg = os.path.join(FIXTURES_DIR, "MVC-015F.JPG")
    if os.path.exists(fixture_jpg):
        from PIL import Image

        img = Image.open(fixture_jpg)
        screen.query_one("#preview", ImagePreview).set_pil_image(img, "MVC-015F.JPG")

    # Button labels and status
    n = len(fixture_jpegs)
    screen.query_one("#btn-preview", Button).label = f"Preview {n} (p)"
    screen.query_one("#btn-preview", Button).disabled = False
    screen.query_one("#btn-merge", Button).label = f"Merge {n} (F2)"
    screen.query_one("#btn-merge", Button).disabled = False
    screen.query_one("#btn-map", Button).disabled = False

    screen.query_one("#status", Static).update(
        f"  [bold]Preview:[/] [green]{matched_count}[/]/{n} matched, "
        f"[dim]{n - matched_count} no match[/]  [dim](dry run \u2014 no files modified)[/]"
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

    # Use real file boundaries from fixture disk image
    from mavica_tools.fat12 import file_sector_map, parse_disk_image

    disk_path = os.path.join(FIXTURES_DIR, "disk_with_photos.img")
    if os.path.exists(disk_path):
        defrag.set_file_boundaries(file_sector_map(disk_path))
        files_on_disk, _, _ = parse_disk_image(disk_path)
        file_names = " ".join(f.name for f in files_on_disk)
    else:
        file_names = ""

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
    log.write(f"  Files: {file_names}")

    await pilot.pause()


async def setup_thumb411(app, pilot):

    screen = app.screen
    with screen.prevent(Input.Changed):
        screen.query_one("#source-path", Input).value = "mavica_out/import_2001-07-04/"

    # List real fixture .411 files
    table = screen.query_one("#results-table", DataTable)
    table.clear()
    fixture_411s = sorted(f for f in os.listdir(FIXTURES_DIR) if f.endswith(".411"))
    for name in fixture_411s:
        size_kb = os.path.getsize(os.path.join(FIXTURES_DIR, name)) / 1024
        table.add_row("[green]\u25cf[/]", name, f"{size_kb:.1f}KB", "")

    screen.query_one("#btn-convert", Button).label = f"Convert {len(fixture_411s)} files"

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


# ── Screen registry ─────────────────────────────────────────────────────────
# (filename, screen_id_or_class, setup_function)


def _build_screen_list():
    """Build the list of screens to screenshot."""
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
