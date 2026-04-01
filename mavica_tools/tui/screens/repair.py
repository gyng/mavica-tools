"""Repair screen — salvage pixels from corrupt JPEGs."""

import glob as globmod
import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
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
    Switch,
)
from textual.worker import get_current_worker

from mavica_tools.repair import repair_jpeg
from mavica_tools.tui.widgets.file_picker import FilePicker
from mavica_tools.tui.widgets.image_preview import ImagePreview


class RepairScreen(Screen):
    """Repair corrupt/truncated JPEG files."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
    ]

    _prefill_files: list[str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]JPEG Repair[/]  [dim]Salvage pixels from corrupt files[/]\n",
            id="title-bar",
        )
        yield Static("  [bold]Source[/]")
        with Horizontal(classes="input-row"):
            yield Input(
                placeholder="Source path (directory or file)...",
                id="source-path",
            )
            yield Button("Browse", id="btn-browse")
        yield Static("  [bold]Output Dir[/]")
        with Horizontal(classes="input-row"):
            yield Input(
                placeholder="Output directory",
                value="mavica_out/repaired",
                id="output-dir",
            )
            yield Button("Repair", variant="success", id="btn-repair")
        with Horizontal(classes="input-row"):
            yield Static("  ", classes="row-label")
            yield Switch(value=False, id="use-411")
            yield Static("  Use .411 thumbnails to fill missing areas", id="label-411")
        yield ProgressBar(total=100, show_percentage=True, show_eta=True, id="progress")
        yield DataTable(id="results-table")
        yield Static(
            "  [dim]Select a row to preview original vs repaired side-by-side[/]", id="preview-hint"
        )
        with Horizontal():
            yield ImagePreview(id="preview-original", classes="preview-pane")
            yield ImagePreview(id="preview-repaired", classes="preview-pane")
        with Horizontal(classes="button-row"):
            yield Button(
                "Next: Add Photo Info", variant="success", id="btn-next-stamp", disabled=True
            )
            yield Button(
                "Next: Export & Share", variant="default", id="btn-next-export", disabled=True
            )
            yield Button("Open Folder", variant="default", id="btn-open-folder", disabled=True)
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Status", "Filename", "Strategy", "Details")
        table.cursor_type = "row"
        self._repair_results = []

        # Handle pre-filled files from check screen
        if self._prefill_files:
            log = self.query_one("#log", RichLog)
            log.write(f"[dim]{len(self._prefill_files)} file(s) received from Check screen[/]")
            # Use the directory of the first file
            first_dir = os.path.dirname(self._prefill_files[0])
            self.query_one("#source-path", Input).value = first_dir

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-repair":
            self._start_repair()
        elif event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-next-stamp":
            self.app.push_screen("stamp")
        elif event.button.id == "btn-next-export":
            self.app.push_screen("export")
        elif event.button.id == "btn-open-folder":
            output_dir = self.query_one("#output-dir", Input).value.strip()
            if output_dir and os.path.isdir(output_dir):
                from mavica_tools.utils import open_directory

                open_directory(output_dir)

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#source-path", Input).value = path

        self.app.push_screen(
            FilePicker(
                extensions=(".jpg", ".jpeg"),
                title="Select JPEG files or directory",
                select_directory=True,
            ),
            on_selected,
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._repair_results and event.cursor_row < len(self._repair_results):
            original, repaired = self._repair_results[event.cursor_row]
            self.query_one("#preview-original", ImagePreview).image_path = original
            if repaired:
                self.query_one("#preview-repaired", ImagePreview).image_path = repaired
            else:
                self.query_one("#preview-repaired", ImagePreview).image_path = ""

    def _start_repair(self) -> None:
        source = self.query_one("#source-path", Input).value.strip()
        output_dir = self.query_one("#output-dir", Input).value.strip()
        if not source and not self._prefill_files:
            self.notify("Enter a source path", severity="warning")
            return
        btn = self.query_one("#btn-repair", Button)
        btn.disabled = True
        btn.label = "Repairing..."
        self.run_worker(self._repair_files(source, output_dir), exclusive=True)

    async def _repair_files(self, source: str, output_dir: str) -> None:
        worker = get_current_worker()
        table = self.query_one("#results-table", DataTable)
        log = self.query_one("#log", RichLog)
        progress = self.query_one("#progress", ProgressBar)
        table.clear()
        self._repair_results = []

        # Use pre-filled files if available, otherwise gather from source
        if self._prefill_files:
            files = list(self._prefill_files)
            self._prefill_files = None
        else:
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
            self._reset_button()
            return

        os.makedirs(output_dir, exist_ok=True)
        log.write(f"Repairing {len(files)} file(s)...\n")
        progress.update(total=len(files), progress=0)

        success = fail = 0

        for i, filepath in enumerate(files):
            if worker.is_cancelled:
                log.write("[yellow]Cancelled.[/]")
                self._reset_button()
                return

            name = os.path.basename(filepath)
            base, _ = os.path.splitext(name)
            out_path = os.path.join(output_dir, base + "_repaired.png")

            use_411 = self.query_one("#use-411", Switch).value
            ok, result_path, msg = repair_jpeg(filepath, out_path, use_411=use_411)

            if ok:
                success += 1
                strategy = "Pillow"
                if ".411" in msg:
                    strategy = ".411 assist"
                elif "truncated at" in msg:
                    strategy = "Sector trim"
                elif "trimmed" in msg:
                    strategy = "Tail trim"
                table.add_row("[green]FIXED[/]", name, strategy, msg)
                self._repair_results.append((filepath, result_path))
            else:
                fail += 1
                table.add_row("[red]FAIL[/]", name, "-", msg)
                self._repair_results.append((filepath, None))

            progress.update(progress=i + 1)

        log.write(f"\n[bold]Results:[/] [green]{success} fixed[/], [red]{fail} failed[/]")
        if success:
            log.write("[dim]Select a row to preview original vs repaired.[/]")
            self.query_one("#btn-next-stamp", Button).disabled = False
            self.query_one("#btn-next-export", Button).disabled = False
            self.query_one("#btn-open-folder", Button).disabled = False
        self._reset_button()

    def _reset_button(self) -> None:
        btn = self.query_one("#btn-repair", Button)
        btn.disabled = False
        btn.label = "Repair"
