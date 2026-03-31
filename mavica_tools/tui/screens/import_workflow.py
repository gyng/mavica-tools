"""Import workflow — photographer's daily driver.

Insert floppy → see photos → tag → export. One screen does it all.
Also supports "next disk" flow for batch importing a stack of floppies.
"""

import os
import glob as globmod

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Static, Input, Button, DataTable, RichLog, ProgressBar,
)
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.tui.widgets.image_preview import ImagePreview
from mavica_tools.tui.widgets.file_picker import FilePicker


class ImportWorkflowScreen(Screen):
    """One-screen photographer workflow: read → preview → tag → export."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Import from Floppy[/]\n",
            id="title-bar",
        )

        # Settings bar
        with Horizontal(classes="input-row"):
            yield Input(
                placeholder="Floppy path or mounted drive (e.g., E:\\, /mnt/floppy, disk.img)",
                id="source-path",
            )
            yield Button("Browse", id="btn-browse")
        with Horizontal(classes="input-row"):
            yield Input(value="photos", placeholder="Save photos to...", id="output-dir")
            yield Input(placeholder="Camera model (e.g., fd7, fd88)", id="camera-model")

        # Main action
        with Horizontal(classes="button-row"):
            yield Button("Import Photos", variant="success", id="btn-import")
            yield Button("Import + Tag + Export", variant="warning", id="btn-import-all")

        yield ProgressBar(total=100, show_percentage=True, show_eta=False, id="progress")
        yield Static("", id="status")

        # Results
        yield DataTable(id="results-table")
        yield ImagePreview(id="preview")

        # Post-import actions
        with Horizontal(classes="button-row"):
            yield Button("Next Disk", variant="success", id="btn-next-disk", disabled=True)
            yield Button("Open in Export", variant="default", id="btn-open-export", disabled=True)
            yield Button("Add GPS Track", variant="default", id="btn-gps", disabled=True)
            yield Button("Contact Sheet", variant="default", id="btn-contact", disabled=True)

        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("", "Filename", "Size", "Date")
        table.cursor_type = "row"
        self._imported_files = []
        self._disk_count = 0

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-import":
            self._start_import(tag=False, export=False)
        elif event.button.id == "btn-import-all":
            self._start_import(tag=True, export=True)
        elif event.button.id == "btn-next-disk":
            self._next_disk()
        elif event.button.id == "btn-open-export":
            screen = self.app.SCREENS["export"]()
            screen._prefill_path = self.query_one("#output-dir", Input).value.strip()
            self.app.push_screen(screen)
        elif event.button.id == "btn-gps":
            self.app.push_screen("gps")
        elif event.button.id == "btn-contact":
            self._make_contact_sheet()

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#source-path", Input).value = path
        self.app.push_screen(
            FilePicker(
                extensions=(".img", ".jpg", ".jpeg"),
                title="Select floppy drive, mounted folder, or disk image",
                select_directory=True,
            ),
            on_selected,
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._imported_files and event.cursor_row < len(self._imported_files):
            self.query_one("#preview", ImagePreview).image_path = self._imported_files[event.cursor_row]

    def _start_import(self, tag: bool, export: bool) -> None:
        source = self.query_one("#source-path", Input).value.strip()
        if not source:
            self.notify("Enter a floppy path, mounted drive, or disk image", severity="warning")
            return

        for btn_id in ("#btn-import", "#btn-import-all"):
            self.query_one(btn_id, Button).disabled = True

        self.run_worker(self._do_import(source, tag, export), exclusive=True)

    async def _do_import(self, source: str, tag: bool, export: bool) -> None:
        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        table = self.query_one("#results-table", DataTable)
        progress = self.query_one("#progress", ProgressBar)
        status = self.query_one("#status", Static)
        output_dir = self.query_one("#output-dir", Input).value.strip() or "photos"
        model = self.query_one("#camera-model", Input).value.strip() or None

        table.clear()
        self._imported_files = []
        self._disk_count += 1

        os.makedirs(output_dir, exist_ok=True)

        # Step 1: Find/extract photos
        status.update("  [bold]Reading floppy...[/]")
        log.write(f"[bold]Disk {self._disk_count}:[/] Reading from {source}...")

        files = []
        if os.path.isdir(source):
            # Mounted floppy or directory — copy JPEGs directly
            for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
                files.extend(globmod.glob(os.path.join(source, ext)))
            files.sort()

            if files:
                log.write(f"  Found {len(files)} photo(s) on mounted disk")
                progress.update(total=len(files), progress=0)

                for i, src_file in enumerate(files):
                    if worker.is_cancelled:
                        self._reset_buttons()
                        return

                    name = os.path.basename(src_file)
                    dest = os.path.join(output_dir, name)

                    # Avoid overwriting — add disk number suffix
                    if os.path.exists(dest):
                        base, ext_str = os.path.splitext(name)
                        dest = os.path.join(output_dir, f"{base}_disk{self._disk_count}{ext_str}")

                    import shutil
                    shutil.copy2(src_file, dest)
                    self._imported_files.append(dest)

                    size_kb = os.path.getsize(dest) / 1024
                    from mavica_tools.utils import get_photo_date
                    date = get_photo_date(dest) or ""

                    table.add_row(str(i + 1), os.path.basename(dest), f"{size_kb:.0f}KB", date)
                    progress.update(progress=i + 1)

        elif source.lower().endswith(".img"):
            # Disk image — try FAT12 extraction
            log.write("  Disk image detected, extracting via FAT12...")
            try:
                from mavica_tools.fat12 import extract_with_names
                results = extract_with_names(source, output_dir, auto_stamp=tag, camera_model=model)
                progress.update(total=len(results), progress=0)

                for i, (orig_name, out_path, size, deleted) in enumerate(results):
                    self._imported_files.append(out_path)
                    prefix = "[red]DEL[/] " if deleted else f"{i + 1}"
                    table.add_row(prefix, os.path.basename(out_path), f"{size / 1024:.0f}KB", "")
                    progress.update(progress=i + 1)

                if tag and results:
                    tag = False  # Already stamped via auto_stamp
                    log.write("  [green]Photos extracted and tagged via FAT12[/]")

            except Exception as e:
                log.write(f"  [#ffaa00]FAT12 failed ({e}), trying JPEG carve...[/]")
                from mavica_tools.carve import carve_jpegs
                carved = carve_jpegs(source, output_dir)
                self._imported_files = carved
                progress.update(total=len(carved), progress=len(carved))
                for i, path in enumerate(carved):
                    name = os.path.basename(path)
                    size_kb = os.path.getsize(path) / 1024
                    table.add_row(str(i + 1), name, f"{size_kb:.0f}KB", "")

        if not self._imported_files:
            log.write("[red]No photos found.[/]")
            status.update("  [red]No photos found. Check the path.[/]")
            self._reset_buttons()
            return

        # Step 2: Tag (if requested and not already done via FAT12)
        if tag and model and self._imported_files:
            status.update("  [bold]Adding camera info...[/]")
            log.write(f"  Stamping with [bold]{model}[/]...")
            from mavica_tools.stamp import stamp_jpeg
            for path in self._imported_files:
                if path.lower().endswith((".jpg", ".jpeg")):
                    stamp_jpeg(path, model=model, date="auto", overwrite=True)
            log.write(f"  [green]Tagged {len(self._imported_files)} photo(s)[/]")

        # Step 3: Export (if requested — organize + contact sheet)
        contact_path = None
        if export and self._imported_files:
            status.update("  [bold]Creating contact sheet...[/]")
            from mavica_tools.export import make_contact_sheet
            contact_path = os.path.join(output_dir, "contact_sheet.jpg")
            make_contact_sheet(
                self._imported_files,
                contact_path,
                columns=4,
                title=f"Mavica {model.upper() if model else 'Photos'} — Disk {self._disk_count}",
            )
            log.write(f"  [green]Contact sheet: {contact_path}[/]")

        # Done
        count = len(self._imported_files)
        actions = ["imported"]
        if tag and model:
            actions.append("tagged")
        if contact_path:
            actions.append("contact sheet created")
        action_str = ", ".join(actions)

        status.update(
            f"  [bold #33ff33]Done![/] {count} photo(s) {action_str}\n"
            f"  Saved to [bold]{output_dir}/[/]"
        )
        log.write(f"\n[bold #33ff33]{count} photo(s) {action_str}[/]")
        log.write("[dim]Select a row to preview. Press 'Next Disk' to import another floppy.[/]")

        from mavica_tools.fun import random_trivia
        log.write(f"\n  [dim italic]{random_trivia()}[/]")

        # Show contact sheet in preview if we made one
        if contact_path:
            self.query_one("#preview", ImagePreview).image_path = contact_path
        elif self._imported_files:
            self.query_one("#preview", ImagePreview).image_path = self._imported_files[0]

        # Enable post-import actions
        self.query_one("#btn-next-disk", Button).disabled = False
        self.query_one("#btn-open-export", Button).disabled = False
        self.query_one("#btn-gps", Button).disabled = False
        self.query_one("#btn-contact", Button).disabled = False

        self._reset_buttons()

    def _make_contact_sheet(self) -> None:
        if not self._imported_files:
            return

        output_dir = self.query_one("#output-dir", Input).value.strip() or "photos"
        model = self.query_one("#camera-model", Input).value.strip()
        log = self.query_one("#log", RichLog)

        from mavica_tools.export import make_contact_sheet
        path = os.path.join(output_dir, "contact_sheet.jpg")
        make_contact_sheet(
            self._imported_files,
            path,
            columns=4,
            title=f"Mavica {model.upper() if model else 'Photos'} — Disk {self._disk_count}",
        )
        log.write(f"[green]Contact sheet: {path}[/]")
        self.query_one("#preview", ImagePreview).image_path = path

    def _next_disk(self) -> None:
        """Reset for the next floppy disk with eject animation."""
        log = self.query_one("#log", RichLog)

        # Eject animation in the log
        from mavica_tools.fun import floppy_art
        log.write(f"\n{'─' * 40}")
        log.write(floppy_art("EJECT", small=True))
        log.write("\n[bold]Ready for next disk.[/] Insert floppy and click Import.")

        # Clear results but keep settings
        self.query_one("#results-table", DataTable).clear()
        self.query_one("#source-path", Input).value = ""
        self.query_one("#preview", ImagePreview).image_path = ""
        self.query_one("#status", Static).update("")
        self.query_one("#progress", ProgressBar).update(total=100, progress=0)

        # Disable post-import buttons
        for btn_id in ("#btn-next-disk", "#btn-open-export", "#btn-gps", "#btn-contact"):
            self.query_one(btn_id, Button).disabled = True

        self._imported_files = []

    def _reset_buttons(self) -> None:
        for btn_id in ("#btn-import", "#btn-import-all"):
            self.query_one(btn_id, Button).disabled = False
