"""Check screen — batch JPEG corruption checker."""

import os
import glob as globmod

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, DataTable, RichLog
from textual.containers import Horizontal, Vertical
from textual.worker import Worker, get_current_worker

from mavica_tools.check import check_jpeg_structure


class CheckScreen(Screen):
    """Batch-check JPEGs for corruption."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("r", "run_check", "Run", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #ffaa00]JPEG Health Check[/]\n", id="title-bar")
        with Horizontal():
            yield Input(
                placeholder="Path to directory or file(s)...",
                id="source-path",
            )
            yield Button("Check", variant="success", id="btn-check")
            yield Button("Repair Bad ->", variant="warning", id="btn-repair", disabled=True)
        yield DataTable(id="results-table")
        yield Static("", id="summary")
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Status", "Filename", "Size", "Dims", "Issues")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-check":
            self.action_run_check()
        elif event.button.id == "btn-repair":
            self._go_to_repair()

    def action_run_check(self) -> None:
        path = self.query_one("#source-path", Input).value.strip()
        if not path:
            self.notify("Enter a path first", severity="warning")
            return
        self.run_worker(self._check_files(path), exclusive=True)

    async def _check_files(self, path: str) -> None:
        worker = get_current_worker()
        table = self.query_one("#results-table", DataTable)
        log = self.query_one("#log", RichLog)
        summary_widget = self.query_one("#summary", Static)

        table.clear()

        # Expand path to JPEG files
        files = []
        if os.path.isdir(path):
            for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
                files.extend(globmod.glob(os.path.join(path, ext)))
        elif os.path.isfile(path):
            files.append(path)
        else:
            # Try as glob pattern
            files.extend(globmod.glob(path))

        files = [f for f in files if f.lower().endswith((".jpg", ".jpeg"))]
        files.sort()

        if not files:
            log.write("[red]No JPEG files found at that path.[/]")
            return

        log.write(f"Checking {len(files)} file(s)...\n")

        good = 0
        warn = 0
        bad = 0
        bad_files = []

        for filepath in files:
            if worker.is_cancelled:
                return

            result = check_jpeg_structure(filepath)
            name = os.path.basename(filepath)
            size_kb = f"{result['size'] / 1024:.0f}KB"
            dims = result.get("dimensions") or "-"
            issues = "; ".join(result["issues"]) if result["issues"] else ""

            if not result["issues"]:
                status = "[green]OK[/]"
                good += 1
            elif result["valid"]:
                status = "[#ffaa00]WARN[/]"
                warn += 1
                bad_files.append(filepath)
            else:
                status = "[red]BAD[/]"
                bad += 1
                bad_files.append(filepath)

            table.add_row(status, name, size_kb, dims, issues)

        total = len(files)
        summary_widget.update(
            f"\n  [bold]Results:[/] {total} checked — "
            f"[green]{good} OK[/]  "
            f"[#ffaa00]{warn} Warning[/]  "
            f"[red]{bad} Bad[/]"
        )

        if bad_files:
            self.query_one("#btn-repair", Button).disabled = False
            self._bad_files = bad_files

        log.write("Done.\n")

    def _go_to_repair(self) -> None:
        if hasattr(self, "_bad_files") and self._bad_files:
            self.app.push_screen("repair")
