"""Format screen — create Mavica-compatible FAT12 disk images."""

import os
import platform

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog
from textual.containers import Horizontal

from mavica_tools.format import create_disk_image, format_floppy


class FormatScreen(Screen):
    """Create Mavica-compatible FAT12 format."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Format Disk[/]  "
            "[dim]Create Mavica-compatible FAT12 format[/]\n",
            id="title-bar",
        )
        yield Static(
            "  Create a blank 1.44MB FAT12 disk image, or format\n"
            "  a physical floppy for use with Mavica cameras.\n"
        )

        yield Static("  [bold]Create Image File[/]", classes="section-title")
        with Horizontal(classes="input-row"):
            yield Input(value="mavica_blank.img", placeholder="Output filename", id="image-output")
            yield Input(value="MAVICA", placeholder="Volume label", id="label")
            yield Button("Create Image", variant="success", id="btn-create")

        yield Static("")

        system = platform.system()
        device_hint = {
            "Windows": r"\\.\A:",
            "Darwin": "/dev/diskN",
        }.get(system, "/dev/fd0")

        yield Static("  [bold]Format Physical Floppy[/]  [red](erases all data!)[/]", classes="section-title")
        with Horizontal(classes="input-row"):
            yield Input(value=device_hint, placeholder="Device path", id="device-path")
            yield Button("Format Device", variant="error", id="btn-format", disabled=True)
        yield Static(
            "  [dim]Check the 'I understand' box to enable device formatting.[/]"
        )
        with Horizontal(classes="button-row"):
            yield Button("I understand this erases all data", variant="warning", id="btn-confirm")

        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-create":
            self._create_image()
        elif event.button.id == "btn-confirm":
            self.query_one("#btn-format", Button).disabled = False
            self.query_one("#btn-confirm", Button).disabled = True
            self.query_one("#btn-confirm", Button).label = "Confirmed"
        elif event.button.id == "btn-format":
            self._format_device()

    def _create_image(self) -> None:
        output = self.query_one("#image-output", Input).value.strip()
        label = self.query_one("#label", Input).value.strip() or "MAVICA"
        log = self.query_one("#log", RichLog)

        if not output:
            self.notify("Enter an output filename", severity="warning")
            return

        try:
            image = create_disk_image(label)
            with open(output, "wb") as f:
                f.write(image)
            log.write(f"[green]Created {output} ({len(image):,} bytes)[/]")
            log.write(f"  Volume label: {label}")
            log.write(f"  Format: FAT12, 1.44MB, Mavica-compatible")
        except Exception as e:
            log.write(f"[red]Error: {e}[/]")

    def _format_device(self) -> None:
        device = self.query_one("#device-path", Input).value.strip()
        label = self.query_one("#label", Input).value.strip() or "MAVICA"
        log = self.query_one("#log", RichLog)

        if not device:
            self.notify("Enter a device path", severity="warning")
            return

        log.write(f"Formatting {device}...")
        try:
            if format_floppy(device, label):
                log.write("[green]Done! Disk is ready for Mavica use.[/]")
            else:
                log.write("[red]Format failed. Check permissions and device path.[/]")
        except Exception as e:
            log.write(f"[red]Error: {e}[/]")

        # Re-lock the format button
        self.query_one("#btn-format", Button).disabled = True
        self.query_one("#btn-confirm", Button).disabled = False
        self.query_one("#btn-confirm", Button).label = "I understand this erases all data"
