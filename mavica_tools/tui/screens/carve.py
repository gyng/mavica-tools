"""Carve screen — extract JPEGs from raw disk images."""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, DataTable, RichLog
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.carve import find_jpegs, MIN_JPEG_SIZE
from mavica_tools.tui.widgets.image_preview import ImagePreview


class CarveScreen(Screen):
    """Carve JPEG images from raw disk images."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #ffaa00]JPEG Carver[/]\n", id="title-bar")
        with Horizontal():
            yield Input(
                placeholder="Path to disk image (.img)...",
                id="image-path",
            )
            yield Input(
                placeholder="Output directory",
                value="carved_images",
                id="output-dir",
            )
        with Horizontal():
            yield Button("Carve", variant="success", id="btn-carve")
            yield Button("Check Carved ->", variant="warning", id="btn-check", disabled=True)
        yield DataTable(id="results-table")
        yield ImagePreview(id="preview")
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("#", "Filename", "Size", "Offset", "Status")
        table.cursor_type = "row"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-carve":
            self._start_carve()
        elif event.button.id == "btn-check":
            self.app.push_screen("check")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if hasattr(self, "_extracted_files") and event.cursor_row < len(self._extracted_files):
            path = self._extracted_files[event.cursor_row]
            preview = self.query_one("#preview", ImagePreview)
            preview.image_path = path

    def _start_carve(self) -> None:
        image_path = self.query_one("#image-path", Input).value.strip()
        output_dir = self.query_one("#output-dir", Input).value.strip()
        if not image_path:
            self.notify("Enter a disk image path", severity="warning")
            return
        if not os.path.isfile(image_path):
            self.notify("File not found", severity="error")
            return
        self.run_worker(self._carve(image_path, output_dir), exclusive=True)

    async def _carve(self, image_path: str, output_dir: str) -> None:
        worker = get_current_worker()
        table = self.query_one("#results-table", DataTable)
        log = self.query_one("#log", RichLog)
        table.clear()

        log.write(f"Reading {image_path}...")

        with open(image_path, "rb") as f:
            data = f.read()

        log.write(f"Scanning {len(data):,} bytes for JPEGs...")

        jpegs = find_jpegs(data)

        if not jpegs:
            log.write("[red]No JPEG images found.[/]")
            return

        os.makedirs(output_dir, exist_ok=True)
        self._extracted_files = []

        for i, (offset, length, truncated) in enumerate(jpegs):
            if worker.is_cancelled:
                return

            suffix = "_TRUNCATED" if truncated else ""
            filename = f"mavica_{i + 1:03d}{suffix}.jpg"
            filepath = os.path.join(output_dir, filename)

            jpeg_data = data[offset : offset + length]
            with open(filepath, "wb") as f:
                f.write(jpeg_data)

            status = "[red]TRUNCATED[/]" if truncated else "[green]OK[/]"
            table.add_row(
                str(i + 1),
                filename,
                f"{length:,}",
                f"0x{offset:06X}",
                status,
            )
            self._extracted_files.append(filepath)

        log.write(f"[green]{len(jpegs)} image(s) extracted to {output_dir}/[/]")
        self.query_one("#btn-check", Button).disabled = False
