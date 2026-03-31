"""Carve screen — extract JPEGs from raw disk images."""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, DataTable, RichLog, ProgressBar
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.carve import find_jpegs
from mavica_tools.tui.widgets.image_preview import ImagePreview
from mavica_tools.tui.widgets.file_picker import FilePicker


class CarveScreen(Screen):
    """Carve JPEG images from raw disk images."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
    ]

    _prefill_image: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #ffaa00]JPEG Carver[/]  [dim]Extract images from raw disk images[/]\n", id="title-bar")
        with Horizontal(classes="input-row"):
            yield Input(
                placeholder="Path to disk image (.img)...",
                id="image-path",
            )
            yield Button("Browse", id="btn-browse")
        with Horizontal(classes="input-row"):
            yield Input(
                placeholder="Output directory",
                value="carved_images",
                id="output-dir",
            )
            yield Button("Carve", variant="success", id="btn-carve")
        yield ProgressBar(total=100, show_percentage=True, show_eta=False, id="progress")
        yield DataTable(id="results-table")
        with Horizontal(classes="button-row"):
            yield Button("Check All", variant="warning", id="btn-check", disabled=True)
        yield ImagePreview(id="preview")
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("#", "Filename", "Size", "Offset", "Status")
        table.cursor_type = "row"
        self._extracted_files = []

        if self._prefill_image:
            self.query_one("#image-path", Input).value = self._prefill_image
            self._prefill_image = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-carve":
            self._start_carve()
        elif event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-check":
            self._go_to_check()

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#image-path", Input).value = path
        self.app.push_screen(
            FilePicker(
                extensions=(".img", ".bin", ".raw"),
                title="Select disk image",
            ),
            on_selected,
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._extracted_files and event.cursor_row < len(self._extracted_files):
            path = self._extracted_files[event.cursor_row]
            self.query_one("#preview", ImagePreview).image_path = path

    def _start_carve(self) -> None:
        image_path = self.query_one("#image-path", Input).value.strip()
        output_dir = self.query_one("#output-dir", Input).value.strip()
        if not image_path:
            self.notify("Enter a disk image path", severity="warning")
            return
        if not os.path.isfile(image_path):
            self.notify(f"File not found: {image_path}", severity="error")
            return
        btn = self.query_one("#btn-carve", Button)
        btn.disabled = True
        btn.label = "Carving..."
        self.run_worker(self._carve(image_path, output_dir), exclusive=True)

    async def _carve(self, image_path: str, output_dir: str) -> None:
        worker = get_current_worker()
        table = self.query_one("#results-table", DataTable)
        log = self.query_one("#log", RichLog)
        progress = self.query_one("#progress", ProgressBar)
        table.clear()
        self._extracted_files = []

        file_size = os.path.getsize(image_path)
        log.write(f"Reading {image_path} ({file_size:,} bytes)...")

        with open(image_path, "rb") as f:
            data = f.read()

        log.write("Scanning for JPEG markers...")
        jpegs = find_jpegs(data)

        if not jpegs:
            log.write("[red]No JPEG images found.[/]")
            self._reset_button()
            return

        os.makedirs(output_dir, exist_ok=True)
        progress.update(total=len(jpegs), progress=0)

        for i, (offset, length, truncated) in enumerate(jpegs):
            if worker.is_cancelled:
                log.write("[yellow]Cancelled.[/]")
                self._reset_button()
                return

            suffix = "_TRUNCATED" if truncated else ""
            filename = f"mavica_{i + 1:03d}{suffix}.jpg"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "wb") as f:
                f.write(data[offset : offset + length])

            status = "[red]TRUNCATED[/]" if truncated else "[green]OK[/]"
            table.add_row(str(i + 1), filename, f"{length:,}", f"0x{offset:06X}", status)
            self._extracted_files.append(filepath)
            progress.update(progress=i + 1)

        log.write(f"[green]{len(jpegs)} image(s) extracted to {output_dir}/[/]")
        log.write("[dim]Select a row to preview the image.[/]")
        self.query_one("#btn-check", Button).disabled = False
        self._reset_button()

    def _reset_button(self) -> None:
        btn = self.query_one("#btn-carve", Button)
        btn.disabled = False
        btn.label = "Carve"

    def _go_to_check(self) -> None:
        if self._extracted_files:
            screen = self.app.SCREENS["check"]()
            # Pre-fill the output directory
            output_dir = self.query_one("#output-dir", Input).value.strip()
            screen._prefill_path = output_dir
            self.app.push_screen(screen)
