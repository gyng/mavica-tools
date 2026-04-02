"""Import workflow — photographer's daily driver.

Insert floppy → see photos → preview → copy to disk.
Also supports "next disk" flow for batch importing a stack of floppies.
Stamping/tagging is handled by the separate Stamp screen.
"""

import glob as globmod
import os
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    ProgressBar,
    RichLog,
    Static,
)
from textual.worker import get_current_worker

from mavica_tools.tui.widgets.defrag_map import DefragMap
from mavica_tools.tui.widgets.drive_input import DriveInput
from mavica_tools.tui.widgets.file_picker import FilePicker
from mavica_tools.tui.widgets.image_preview import ImagePreview


class ImportWorkflowScreen(Screen):
    """One-screen photographer workflow: read floppy → preview → copy."""

    DEFAULT_CSS = """
    ImportWorkflowScreen VerticalScroll {
        height: 1fr;
    }
    #import-main {
        height: auto;
        min-height: 10;
    }
    #import-left {
        width: 1fr;
        min-width: 30;
    }
    #import-right {
        width: 40;
        min-width: 30;
        align: center top;
    }
    #import-right ImagePreview {
        height: auto;
        min-height: 5;
        content-align: center top;
        margin-bottom: 1;
    }
    ImportWorkflowScreen #results-table {
        height: auto;
        margin: 0;
    }
    ImportWorkflowScreen #defrag-map {
        width: 100%;
    }
    ImportWorkflowScreen #log {
        height: 2;
        max-height: 2;
        margin: 0;
        border: none;
    }
    """

    BINDINGS: ClassVar[list] = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("f2", "start_import", "Import", show=True),
        Binding("o", "open_output", "Open Out", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static(
                "[bold #ffaa00]Import from Floppy[/]\n",
                id="title-bar",
            )

            # Source row — shared drive input with autodetect + browse
            yield DriveInput(
                label="Source",
                default="auto",
                show_mounts=True,
                autodetect_on_mount=True,
                id="drive-input",
            )

            # Output row
            with Horizontal(classes="input-row"):
                yield Static("     [bold]Out[/] ", classes="row-label")
                yield Input(placeholder="Save photos to...", id="output-dir")
                yield Button("Browse", id="btn-browse-out")
                yield Button("Open", id="btn-open-folder")

            # Main action
            with Horizontal(classes="button-row"):
                yield Button("Preview Disk", variant="warning", id="btn-preview")
                yield Button("Import Photos (F2)", variant="success", id="btn-import")
                yield Button("Stop", variant="error", id="btn-stop", disabled=True)
                yield Button("Next Disk", variant="warning", id="btn-next-disk", disabled=True)

            yield ProgressBar(total=100, show_percentage=True, show_eta=True, id="progress")
            yield Static("", id="status")

            # Two-pane: file list on left, preview on right
            with Horizontal(id="import-main"):
                with Vertical(id="import-left"):
                    yield DataTable(id="results-table")
                with Vertical(id="import-right"):
                    yield ImagePreview(id="preview")

            # Defrag map — full width below the two-pane area
            yield DefragMap(id="defrag-map")

            # Post-import actions
            with Horizontal(classes="button-row"):
                yield Button("Stamp Photos", variant="warning", id="btn-stamp", disabled=True)
                yield Button("Add GPS Track", variant="default", id="btn-gps", disabled=True)

            yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Status", "Filename", "Size", "Date")
        table.cursor_type = "row"
        self._imported_files: list[str] = []
        self._source_files: list[str] = []
        self._disk_count = 0

        self._regenerate_output_dir()

    def _regenerate_output_dir(self) -> None:
        """Set output dir to a fresh timestamped path."""
        from datetime import datetime as _dt

        ts = _dt.now().strftime("%Y-%m-%d_%H%M%S")
        self.query_one("#output-dir", Input).value = f"mavica_out/import_{ts}"

    @property
    def _source_path(self) -> str:
        return self.query_one("#drive-input", DriveInput).value

    # ── Defrag map helpers ──────────────────────────────────────

    def _try_populate_defrag(self, source: str) -> None:
        """Populate defrag map from a mounted floppy device or disk image."""
        defrag = self.query_one("#defrag-map", DefragMap)

        if source.lower().endswith(".img") and os.path.isfile(source):
            try:
                from mavica_tools.fat12 import file_sector_map

                boundaries = file_sector_map(source)
                defrag.set_file_boundaries(boundaries)
            except Exception:
                pass
            return

        if not os.path.isdir(source):
            return

        # Mounted directory — try to find the raw device behind it
        import platform

        device = None
        system = platform.system()
        if system == "Windows":
            # mount_path like "A:\" -> device "\\.\A:"
            if len(source) >= 2 and source[1] == ":":
                device = f"\\\\.\\{source[0]}:"
        elif system == "Linux":
            try:
                with open("/proc/mounts") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == source.rstrip("/"):
                            device = parts[0]
                            break
            except OSError:
                pass

        if not device:
            return

        try:
            with open(device, "rb") as fh:
                data = fh.read(33 * 512)  # FAT12 metadata area
            from mavica_tools.fat12 import file_sector_map_from_data

            boundaries = file_sector_map_from_data(data)
            if boundaries:
                defrag.set_file_boundaries(boundaries)
        except OSError:
            pass

    # ── Button handlers ───────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse-out":
            self._browse_output()
        elif event.button.id == "btn-open-folder":
            self.action_open_output()
        elif event.button.id == "btn-preview":
            self._preview_disk()
        elif event.button.id == "btn-import":
            self._start_import()
        elif event.button.id == "btn-stop":
            self._stop_import()
        elif event.button.id == "btn-next-disk":
            self._next_disk()
        elif event.button.id == "btn-stamp":
            self._open_stamp()
        elif event.button.id == "btn-gps":
            screen = self.app.SCREENS["gps"]()
            screen._prefill_photos = self.query_one("#output-dir", Input).value.strip()
            self.app.push_screen(screen)

    # ── Actions / keybindings ─────────────────────────────────────

    def action_start_import(self) -> None:
        """F2 -- start import."""
        self._start_import()

    def action_open_output(self) -> None:
        from mavica_tools.utils import open_directory

        output_dir = os.path.abspath(self.query_one("#output-dir", Input).value.strip())
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            open_directory(output_dir)

    def _browse_output(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#output-dir", Input).value = path

        self.app.push_screen(
            FilePicker(
                title="Select output directory",
                select_directory=True,
                allow_new_folder=True,
            ),
            on_selected,
        )

    # ── Preview ───────────────────────────────────────────────────

    def _show_preview(self, path: str) -> None:
        """Show a preview for a file — handles both JPEG and .411 thumbnails."""
        preview = self.query_one("#preview", ImagePreview)
        if path.lower().endswith(".411"):
            try:
                from mavica_tools.thumb411 import decode_411_to_image

                img = decode_411_to_image(path)
                # Nearest neighbor for upscaling — preserves the blocky pixel art look of 64x48 thumbnails
                upscaled = img.resize((256, 192), resample=0)
                preview.set_pil_image(upscaled, os.path.basename(path))
            except Exception:
                preview.image_path = ""
        else:
            preview.image_path = path

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None:
            return
        if self._imported_files and event.cursor_row < len(self._imported_files):
            self._show_preview(self._imported_files[event.cursor_row])
        elif self._source_files and event.cursor_row < len(self._source_files):
            path = self._source_files[event.cursor_row]
            if os.path.isfile(path):
                self._show_preview(path)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._imported_files and event.cursor_row < len(self._imported_files):
            self._show_preview(self._imported_files[event.cursor_row])

    # ── Preview disk ──────────────────────────────────────────────

    def _preview_disk(self) -> None:
        """List files on the source disk/directory without importing."""
        source = self._source_path
        if not source:
            self.notify("Enter a floppy path, mounted drive, or disk image", severity="warning")
            return
        self.run_worker(self._do_preview(source), exclusive=True)

    async def _do_preview(self, source: str) -> None:
        """Read file listing from source and populate the table + defrag map."""
        table = self.query_one("#results-table", DataTable)
        table.clear()
        log = self.query_one("#log", RichLog)
        self._source_files = []

        if source.lower().endswith(".img") and os.path.isfile(source):
            # Disk image — parse FAT12
            try:
                from mavica_tools.fat12 import parse_disk_image

                files, _fat, _data = parse_disk_image(source)
                for f in files:
                    table.add_row("", f.name, f"{f.size / 1024:.1f} KB", f.date_str)
                    # Construct a fake path for preview ordering
                    self._source_files.append(source)
                log.write(f"[dim]Disk image: {len(files)} files found[/]")
            except Exception as e:
                log.write(f"[red]Failed to read disk image: {e}[/]")
        elif os.path.isdir(source):
            # Mounted directory — list Mavica files
            from mavica_tools.utils import gather_mavica_files

            files = gather_mavica_files(source)
            self._source_files = files
            for path in files:
                name = os.path.basename(path)
                try:
                    size_kb = os.path.getsize(path) / 1024
                    size_str = f"{size_kb:.1f} KB"
                except OSError:
                    size_str = "?"
                table.add_row("", name, size_str, "")
            log.write(f"[dim]{len(files)} file(s) on disk[/]")

            # Preview first file
            if files:
                self._show_preview(files[0])
                table.focus()
        else:
            log.write(f"[red]Cannot read: {source}[/]")
            return

        # Populate defrag map
        self._try_populate_defrag(source)

    # ── Import ────────────────────────────────────────────────────

    _stop_requested: bool = False

    def _start_import(self) -> None:
        source = self._source_path
        if not source:
            self.notify("Enter a floppy path, mounted drive, or disk image", severity="warning")
            return

        self._stop_requested = False
        self.query_one("#btn-import", Button).disabled = True
        self.query_one("#btn-stop", Button).disabled = False
        self.run_worker(self._do_import(source), exclusive=True)

    def _stop_import(self) -> None:
        self._stop_requested = True
        self.query_one("#btn-stop", Button).disabled = True
        for worker in self.workers:
            worker.cancel()

    async def _do_import(self, source: str) -> None:
        import asyncio
        import shutil
        import time

        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        table = self.query_one("#results-table", DataTable)
        progress = self.query_one("#progress", ProgressBar)
        status = self.query_one("#status", Static)
        self.query_one("#defrag-map", DefragMap)  # ensure widget exists
        output_dir = self.query_one("#output-dir", Input).value.strip() or "photos"

        table.clear()
        self._imported_files = []
        self._disk_count += 1

        status.update("  [bold]Reading floppy...[/]")
        log.write(f"[bold]Disk {self._disk_count}:[/] Reading from {source}...")

        # Try to populate defrag map from device/image
        self._try_populate_defrag(source)

        os.makedirs(output_dir, exist_ok=True)

        t_start = time.monotonic()
        total_bytes = 0

        files = []
        if os.path.isdir(source):
            # Mounted floppy or directory — copy JPEGs and .411 thumbnails
            for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.411"):
                files.extend(globmod.glob(os.path.join(source, ext)))
            # Deduplicate (Windows is case-insensitive)
            seen: set[str] = set()
            deduped: list[str] = []
            for f in files:
                key = os.path.normcase(f)
                if key not in seen:
                    seen.add(key)
                    deduped.append(f)
            files = sorted(deduped)

            if files:
                log.write(f"  Found {len(files)} file(s) on mounted disk")
                progress.update(total=len(files), progress=0)
                failed = 0

                for i, src_file in enumerate(files):
                    if self._stop_requested or worker.is_cancelled:
                        log.write("[yellow]Stopped.[/]")
                        self._finish_import(output_dir, t_start, total_bytes, stopped=True)
                        return

                    name = os.path.basename(src_file)
                    dest = os.path.join(output_dir, name)

                    try:
                        await asyncio.to_thread(shutil.copy2, src_file, dest)
                    except OSError as e:
                        failed += 1
                        log.write(f"  [red]Failed to read {name}: {e}[/]")
                        table.add_row("[red]ERR[/]", name, "\u2014", "")
                        progress.update(progress=i + 1)
                        continue
                    self._imported_files.append(dest)

                    fsize = os.path.getsize(dest)
                    total_bytes += fsize
                    size_kb = fsize / 1024
                    from mavica_tools.utils import get_photo_date

                    date = get_photo_date(dest) or ""

                    table.add_row(
                        str(i + 1 - failed), os.path.basename(dest), f"{size_kb:.0f}KB", date
                    )
                    progress.update(progress=i + 1)

                    # Live speed in status bar
                    elapsed = time.monotonic() - t_start
                    if elapsed > 0:
                        speed = total_bytes / 1024 / elapsed
                        status.update(
                            f"  [bold]Copying...[/] {i + 1}/{len(files)}  [dim]{speed:.1f} KB/s[/]"
                        )

                if failed:
                    log.write(f"  [#ffaa00]{failed} file(s) could not be read (damaged sectors)[/]")

        elif source.lower().endswith(".img"):
            # Disk image — try FAT12 extraction
            log.write("  Disk image detected, extracting via FAT12...")

            try:
                from mavica_tools.fat12 import extract_with_names

                results = await asyncio.to_thread(
                    extract_with_names,
                    source,
                    output_dir,
                )
                progress.update(total=len(results), progress=0)

                for i, (_orig_name, out_path, size, deleted) in enumerate(results):
                    self._imported_files.append(out_path)
                    total_bytes += size
                    prefix = "[red]DEL[/] " if deleted else f"{i + 1}"
                    table.add_row(prefix, os.path.basename(out_path), f"{size / 1024:.0f}KB", "")
                    progress.update(progress=i + 1)

            except Exception as e:
                log.write(f"  [#ffaa00]FAT12 failed ({e}), trying JPEG carve...[/]")
                from mavica_tools.carve import carve_jpegs

                carved = await asyncio.to_thread(carve_jpegs, source, output_dir)
                self._imported_files = carved
                progress.update(total=len(carved), progress=len(carved))
                for i, path in enumerate(carved):
                    name = os.path.basename(path)
                    fsize = os.path.getsize(path)
                    total_bytes += fsize
                    table.add_row(str(i + 1), name, f"{fsize / 1024:.0f}KB", "")

        self._finish_import(output_dir, t_start, total_bytes, stopped=False)

    def _finish_import(
        self, output_dir: str, t_start: float, total_bytes: int, stopped: bool
    ) -> None:
        import time

        log = self.query_one("#log", RichLog)
        status = self.query_one("#status", Static)

        elapsed = time.monotonic() - t_start
        speed = total_bytes / 1024 / elapsed if elapsed > 0 else 0
        if elapsed >= 60:
            time_str = f"{int(elapsed // 60)}m {elapsed % 60:.1f}s"
        else:
            time_str = f"{elapsed:.1f}s"
        total_kb = total_bytes / 1024
        stats = f"{total_kb:.0f}KB in {time_str} ({speed:.1f} KB/s)"

        if not self._imported_files:
            if not stopped:
                log.write("[red]No photos found.[/]")
                status.update("  [red]No photos found. Check the path.[/]")
            self._reset_buttons()
            return

        count = len(self._imported_files)
        if stopped:
            status.update(
                f"  [bold #ffaa00]Stopped.[/] {count} photo(s) imported  [dim]{stats}[/]\n"
                f"  Saved to [bold]{output_dir}/[/]"
            )
            log.write(f"[#ffaa00]{count} photo(s) imported (stopped)  {stats}[/]")
        else:
            status.update(
                f"  [bold #33ff33]Done![/] {count} photo(s) imported  [dim]{stats}[/]\n"
                f"  Saved to [bold]{output_dir}/[/]"
            )
            log.write(f"\n[bold #33ff33]{count} photo(s) imported[/]  {stats}")
            log.write("[dim]Use 'Stamp Photos' to add EXIF metadata.[/]")

            from mavica_tools.fun import random_trivia

            log.write(f"\n  [dim italic]{random_trivia()}[/]")

        # Preview first photo
        if self._imported_files:
            self._show_preview(self._imported_files[0])

        # Enable post-import actions
        self.query_one("#btn-next-disk", Button).disabled = False
        self.query_one("#btn-stamp", Button).disabled = False
        self.query_one("#btn-gps", Button).disabled = False

        self._reset_buttons()

    def _open_stamp(self) -> None:
        """Push to stamp screen with imported files pre-filled."""
        from mavica_tools.tui.screens.stamp_screen import StampScreen

        screen = StampScreen()
        # Point to the disk subdir if we have imported files
        if self._imported_files:
            screen._prefill_path = os.path.dirname(self._imported_files[0])
        else:
            screen._prefill_path = self.query_one("#output-dir", Input).value.strip()
        self.app.push_screen(screen)

    def _next_disk(self) -> None:
        """Reset for the next floppy disk with eject animation."""
        log = self.query_one("#log", RichLog)
        defrag = self.query_one("#defrag-map", DefragMap)

        # Eject animation in the log
        from mavica_tools.fun import floppy_art

        log.write("\n" + "\u2500" * 40)
        log.write(floppy_art("EJECT", small=True))
        log.write("\n[bold]Ready for next disk.[/] Insert floppy and press F2 to Import.")

        # Clear results but keep settings
        self.query_one("#results-table", DataTable).clear()
        self.query_one("#preview", ImagePreview).image_path = ""
        self.query_one("#status", Static).update("")
        self.query_one("#progress", ProgressBar).update(total=100, progress=0)
        defrag.reset(clear_files=True)

        # New output dir for the next disk
        self._regenerate_output_dir()

        # Disable post-import buttons
        for btn_id in (
            "#btn-next-disk",
            "#btn-stamp",
            "#btn-gps",
        ):
            self.query_one(btn_id, Button).disabled = True

        self._imported_files = []
        self._source_files = []

        # Re-run autodetect for the new disk
        drive_input = self.query_one("#drive-input", DriveInput)
        drive_input.value = ""
        drive_input._start_autodetect()

    def _reset_buttons(self) -> None:
        self.query_one("#btn-import", Button).disabled = False
        self.query_one("#btn-stop", Button).disabled = True
