"""Check screen — batch JPEG corruption checker."""

import os
import glob as globmod

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, DataTable, RichLog, ProgressBar
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.check import check_jpeg_structure
from mavica_tools.tui.widgets.file_picker import FilePicker


class CheckScreen(Screen):
    """Batch-check JPEGs for corruption."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("r", "run_check", "Run", show=True),
        Binding("b", "browse", "Browse", show=True),
    ]

    _prefill_path: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #ffaa00]JPEG Health Check[/]\n", id="title-bar")
        with Horizontal(classes="input-row"):
            yield Input(
                placeholder="Path to directory or JPEG file(s)...",
                id="source-path",
            )
            yield Button("Browse", id="btn-browse")
            yield Button("Check", variant="success", id="btn-check")
        yield ProgressBar(total=100, show_percentage=True, show_eta=False, id="progress")
        yield DataTable(id="results-table")
        yield Static("", id="summary")
        with Horizontal(classes="button-row"):
            yield Button("Repair Bad Files", variant="warning", id="btn-repair", disabled=True)
            yield Button("Stamp Metadata", variant="default", id="btn-stamp", disabled=True)
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Status", "Filename", "Size", "Dims", "Issues")
        self.query_one("#progress", ProgressBar).update(total=100, progress=0)
        self._good_files = []
        self._bad_files = []

        if self._prefill_path:
            self.query_one("#source-path", Input).value = self._prefill_path
            self._prefill_path = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-check":
            self.action_run_check()
        elif event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-repair":
            self._go_to_repair()
        elif event.button.id == "btn-stamp":
            self._go_to_stamp()

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

    def action_run_check(self) -> None:
        path = self.query_one("#source-path", Input).value.strip()
        if not path:
            self.notify("Enter a path first", severity="warning")
            return
        btn = self.query_one("#btn-check", Button)
        btn.disabled = True
        btn.label = "Checking..."
        self.run_worker(self._check_files(path), exclusive=True)

    async def _check_files(self, path: str) -> None:
        worker = get_current_worker()
        table = self.query_one("#results-table", DataTable)
        log = self.query_one("#log", RichLog)
        summary_widget = self.query_one("#summary", Static)
        progress = self.query_one("#progress", ProgressBar)

        table.clear()
        self._good_files = []
        self._bad_files = []

        files = []
        if os.path.isdir(path):
            for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
                files.extend(globmod.glob(os.path.join(path, ext)))
        elif os.path.isfile(path):
            files.append(path)
        else:
            files.extend(globmod.glob(path))

        files = [f for f in files if f.lower().endswith((".jpg", ".jpeg"))]
        files.sort()

        if not files:
            log.write("[red]No JPEG files found at that path.[/]")
            self._reset_button()
            return

        log.write(f"Checking {len(files)} file(s)...\n")
        progress.update(total=len(files), progress=0)

        good = warn = bad = 0

        for i, filepath in enumerate(files):
            if worker.is_cancelled:
                log.write("[yellow]Cancelled.[/]")
                self._reset_button()
                return

            result = check_jpeg_structure(filepath)
            name = os.path.basename(filepath)
            size_kb = f"{result['size'] / 1024:.0f}KB"
            dims = result.get("dimensions") or "-"
            issues = "; ".join(result["issues"]) if result["issues"] else ""

            if not result["issues"]:
                status = "[green]OK[/]"
                good += 1
                self._good_files.append(filepath)
            elif result["valid"]:
                status = "[#ffaa00]WARN[/]"
                warn += 1
                self._bad_files.append(filepath)
            else:
                status = "[red]BAD[/]"
                bad += 1
                self._bad_files.append(filepath)

            table.add_row(status, name, size_kb, dims, issues)
            progress.update(progress=i + 1)

        summary_widget.update(
            f"\n  [bold]Results:[/] {len(files)} checked — "
            f"[green]{good} OK[/]  "
            f"[#ffaa00]{warn} Warning[/]  "
            f"[red]{bad} Bad[/]"
        )

        if self._bad_files:
            self.query_one("#btn-repair", Button).disabled = False
            log.write(f"[bold #33ff33]Next:[/] Click [bold]Repair Bad Files[/] to salvage corrupt images.")
        elif self._good_files:
            log.write("[bold #33ff33]All photos OK![/] Click [bold]Stamp Metadata[/] to add camera info.")
        if self._good_files:
            self.query_one("#btn-stamp", Button).disabled = False

        self._reset_button()

    def _reset_button(self) -> None:
        btn = self.query_one("#btn-check", Button)
        btn.disabled = False
        btn.label = "Check"

    def _go_to_repair(self) -> None:
        if self._bad_files:
            screen = self.app.SCREENS["repair"]()
            screen._prefill_files = self._bad_files
            self.app.push_screen(screen)

    def _go_to_stamp(self) -> None:
        all_files = self._good_files + self._bad_files
        if all_files:
            screen = self.app.SCREENS["stamp"]()
            screen._prefill_files = all_files
            self.app.push_screen(screen)
