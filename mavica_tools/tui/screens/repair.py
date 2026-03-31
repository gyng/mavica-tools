"""Repair screen — salvage pixels from corrupt JPEGs."""

import os
import glob as globmod

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, DataTable, RichLog
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.repair import repair_jpeg
from mavica_tools.tui.widgets.image_preview import ImagePreview


class RepairScreen(Screen):
    """Repair corrupt/truncated JPEG files."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #ffaa00]JPEG Repair[/]\n", id="title-bar")
        with Horizontal():
            yield Input(
                placeholder="Source path (directory or file)...",
                id="source-path",
            )
            yield Input(
                placeholder="Output directory",
                value="repaired",
                id="output-dir",
            )
            yield Button("Repair", variant="success", id="btn-repair")
        yield DataTable(id="results-table")
        with Horizontal(id="preview-row"):
            yield ImagePreview(id="preview-original")
            yield ImagePreview(id="preview-repaired")
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Status", "Filename", "Strategy", "Details")
        table.cursor_type = "row"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-repair":
            self._start_repair()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if hasattr(self, "_repair_results") and event.cursor_row < len(self._repair_results):
            original, repaired = self._repair_results[event.cursor_row]
            self.query_one("#preview-original", ImagePreview).image_path = original
            if repaired:
                self.query_one("#preview-repaired", ImagePreview).image_path = repaired
            else:
                self.query_one("#preview-repaired", ImagePreview).image_path = ""

    def _start_repair(self) -> None:
        source = self.query_one("#source-path", Input).value.strip()
        output_dir = self.query_one("#output-dir", Input).value.strip()
        if not source:
            self.notify("Enter a source path", severity="warning")
            return
        self.run_worker(self._repair_files(source, output_dir), exclusive=True)

    async def _repair_files(self, source: str, output_dir: str) -> None:
        worker = get_current_worker()
        table = self.query_one("#results-table", DataTable)
        log = self.query_one("#log", RichLog)
        table.clear()
        self._repair_results = []

        # Gather files
        files = []
        if os.path.isdir(source):
            for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
                files.extend(globmod.glob(os.path.join(source, ext)))
        elif os.path.isfile(source):
            files.append(source)
        else:
            files.extend(globmod.glob(source))
        files.sort()

        if not files:
            log.write("[red]No JPEG files found.[/]")
            return

        os.makedirs(output_dir, exist_ok=True)
        log.write(f"Attempting to repair {len(files)} file(s)...\n")

        success = 0
        fail = 0

        for filepath in files:
            if worker.is_cancelled:
                return

            name = os.path.basename(filepath)
            base, _ = os.path.splitext(name)
            out_path = os.path.join(output_dir, base + "_repaired.png")

            ok, result_path, msg = repair_jpeg(filepath, out_path)

            if ok:
                success += 1
                # Extract strategy from message
                strategy = "Pillow"
                if "truncated at" in msg:
                    strategy = "Sector trim"
                elif "trimmed" in msg:
                    strategy = "Tail trim"
                table.add_row("[green]FIXED[/]", name, strategy, msg)
                self._repair_results.append((filepath, result_path))
            else:
                fail += 1
                table.add_row("[red]FAIL[/]", name, "-", msg)
                self._repair_results.append((filepath, None))

        log.write(
            f"\n[bold]Results:[/] [green]{success} fixed[/], [red]{fail} failed[/]"
        )
