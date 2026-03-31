"""Import workflow — regular floppy-to-export for working disks.

This is the happy path: your floppy works fine, you just want to
get the photos off, add metadata, and export them nicely.
"""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog
from textual.containers import Horizontal


class ImportWorkflowScreen(Screen):
    """Guided import: read → tag → export."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Import from Floppy[/]  "
            "[dim]Read > Tag > Export — for working disks[/]\n",
            id="title-bar",
        )
        yield Static(
            "  Your floppy works fine? Great — follow these steps to\n"
            "  get your photos off, add camera/date info, and export.\n\n"
            "  [dim]If your disk is damaged or photos are corrupt,\n"
            "  use [bold]Repair & Recovery[/dim] from the main menu instead.[/]\n"
        )

        yield Static("  [bold]Settings[/]", classes="section-title")
        with Horizontal(classes="input-row"):
            yield Input(value="import", placeholder="Output directory", id="output-dir")
            yield Input(placeholder="Camera model (e.g., fd7, fd88)", id="camera-model")

        yield Static("\n  [bold #33ff33]Step 1: Get the photos[/]")
        yield Static("  [dim]Extract files from the floppy with original names.[/]")
        with Horizontal(classes="button-row"):
            yield Button("Browse Floppy Files", variant="success", id="btn-browse-floppy")
            yield Button("Quick Extract All", variant="success", id="btn-extract")

        yield Static("\n  [bold #33ff33]Step 2: Add photo info[/]")
        yield Static(
            "  [dim]Add camera model, date, focal length, and aperture to EXIF.\n"
            "  This makes your photos sortable and searchable in any photo app.[/]"
        )
        with Horizontal(classes="button-row"):
            yield Button("Stamp All Photos", variant="success", id="btn-stamp", disabled=True)
            yield Button("Add GPS Track", variant="default", id="btn-gps", disabled=True)

        yield Static("\n  [bold #33ff33]Step 3: Export[/]")
        yield Static("  [dim]Organize, create a contact sheet, add watermarks.[/]")
        with Horizontal(classes="button-row"):
            yield Button("Export & Share", variant="success", id="btn-export", disabled=True)
            yield Button("Generate Report", variant="default", id="btn-report", disabled=True)

        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        log = self.query_one("#log", RichLog)
        output = self.query_one("#output-dir", Input).value.strip() or "import"
        model = self.query_one("#camera-model", Input).value.strip()

        if event.button.id == "btn-browse-floppy":
            log.write("[bold]Step 1:[/] Opening FAT12 browser...")
            self.app.push_screen("fat12")
            self._enable_step2()

        elif event.button.id == "btn-extract":
            log.write("[bold]Step 1:[/] Opening one-click recover...")
            log.write(f"  Output: {output}/")
            self.app.push_screen("recover")
            self._enable_step2()

        elif event.button.id == "btn-stamp":
            if model:
                log.write(f"[bold]Step 2:[/] Stamping with model {model}...")
            else:
                log.write("[bold]Step 2:[/] Opening stamp tool...")
                log.write("[dim]Tip: enter your camera model above for accurate lens data.[/]")
            screen = self.app.SCREENS["stamp"]()
            self.app.push_screen(screen)
            self._enable_step3()

        elif event.button.id == "btn-gps":
            log.write("[bold]Step 2b:[/] Opening GPS merge...")
            self.app.push_screen("gps")
            self._enable_step3()

        elif event.button.id == "btn-export":
            log.write("[bold]Step 3:[/] Opening export...")
            self.app.push_screen("export")

        elif event.button.id == "btn-report":
            log.write("[bold]Step 3:[/] Opening report...")
            if "report" in self.app.SCREENS:
                self.app.push_screen("report")

    def _enable_step2(self) -> None:
        self.query_one("#btn-stamp", Button).disabled = False
        self.query_one("#btn-gps", Button).disabled = False

    def _enable_step3(self) -> None:
        self.query_one("#btn-export", Button).disabled = False
        self.query_one("#btn-report", Button).disabled = False
