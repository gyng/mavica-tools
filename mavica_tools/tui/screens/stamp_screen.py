"""Stamp metadata screen — add EXIF to recovered JPEGs."""

import os
import glob as globmod

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, DataTable, RichLog, ProgressBar
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.stamp import stamp_jpeg, MAVICA_MODELS
from mavica_tools.tui.widgets.file_picker import FilePicker


MODELS_HINT = "  [dim]Models: " + ", ".join(
    f"{k}" for k in sorted(MAVICA_MODELS.keys())[:10]
) + ", ...[/]"


class StampScreen(Screen):
    """Add EXIF metadata to recovered Mavica JPEGs."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
    ]

    _prefill_files: list[str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Stamp Metadata[/]  "
            "[dim]Add EXIF to bare Mavica JPEGs[/]\n",
            id="title-bar",
        )
        yield Static("  [bold]Source[/]")
        with Horizontal(classes="input-row"):
            yield Input(placeholder="Source path (directory or file)...", id="source-path")
            yield Button("Browse", id="btn-browse")
        yield Static("  [bold]Camera Model[/]  /  [bold]Date[/]")
        with Horizontal(classes="input-row"):
            yield Input(placeholder="Camera model (e.g., fd7, fd88)", id="model-input")
            yield Input(placeholder="Date (auto, YYYY-MM-DD, or full)", value="auto", id="date-input")
        yield Static(MODELS_HINT)
        yield Static("  [bold]Description[/]  /  [bold]Output Dir[/]")
        with Horizontal(classes="input-row"):
            yield Input(placeholder="Description / notes (optional)", id="desc-input")
            yield Input(placeholder="Output directory (blank = alongside)", id="output-dir")
        with Horizontal(classes="button-row"):
            yield Button("Stamp All", variant="success", id="btn-stamp")
        yield ProgressBar(total=100, show_percentage=True, show_eta=True, id="progress")
        yield DataTable(id="results-table")
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Status", "Filename", "Details")
        self._stamped_files = []

        if self._prefill_files:
            log = self.query_one("#log", RichLog)
            first_dir = os.path.dirname(self._prefill_files[0]) if self._prefill_files else ""
            self.query_one("#source-path", Input).value = first_dir
            log.write(f"[dim]{len(self._prefill_files)} file(s) received[/]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-stamp":
            self._start_stamp()

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

    def _start_stamp(self) -> None:
        source = self.query_one("#source-path", Input).value.strip()
        if not source and not self._prefill_files:
            self.notify("Enter a source path", severity="warning")
            return

        model = self.query_one("#model-input", Input).value.strip() or None
        date = self.query_one("#date-input", Input).value.strip() or None
        desc = self.query_one("#desc-input", Input).value.strip() or None
        output_dir = self.query_one("#output-dir", Input).value.strip() or None

        btn = self.query_one("#btn-stamp", Button)
        btn.disabled = True
        btn.label = "Stamping..."
        self.run_worker(
            self._do_stamp(source, model, date, desc, output_dir),
            exclusive=True,
        )

    async def _do_stamp(self, source, model, date, desc, output_dir) -> None:
        worker = get_current_worker()
        table = self.query_one("#results-table", DataTable)
        log = self.query_one("#log", RichLog)
        progress = self.query_one("#progress", ProgressBar)
        table.clear()

        # Gather files
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

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        progress.update(total=len(files), progress=0)
        log.write(f"Stamping {len(files)} file(s)...\n")

        success = fail = 0

        for i, filepath in enumerate(files):
            if worker.is_cancelled:
                log.write("[yellow]Cancelled.[/]")
                self._reset_button()
                return

            name = os.path.basename(filepath)
            if output_dir:
                out_path = os.path.join(output_dir, name)
            else:
                out_path = None

            ok, result_path, msg = stamp_jpeg(
                filepath, out_path,
                model=model, date=date, description=desc,
            )

            if ok:
                success += 1
                table.add_row("[green]OK[/]", name, msg)
            else:
                fail += 1
                table.add_row("[red]FAIL[/]", name, msg)

            progress.update(progress=i + 1)

        log.write(f"\n[bold]Results:[/] [green]{success} stamped[/], [red]{fail} failed[/]")
        if success:
            log.write("[bold #33ff33]Next:[/] Use [bold]Export & Share[/] (key [bold]e[/]) to organize and create contact sheets.")
        self._reset_button()

    def _reset_button(self) -> None:
        btn = self.query_one("#btn-stamp", Button)
        btn.disabled = False
        btn.label = "Stamp All"
