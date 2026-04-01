"""Format screen — create Mavica-compatible FAT12 disk images."""

import os
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog, ProgressBar
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.format import (
    format_floppy, format_floppy_full, TOTAL_SECTORS,
    get_blocking_processes, force_dismount_volume,
)
from mavica_tools.tui.widgets.defrag_map import DefragMap
from mavica_tools.tui.widgets.drive_input import DriveInput


class _StopRequested(Exception):
    pass


class FormatScreen(Screen):
    """Create Mavica-compatible FAT12 format."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    _stop_requested: bool = False

    def on_screen_suspend(self) -> None:
        from textual.screen import ModalScreen
        top = self.app.screen
        if isinstance(top, ModalScreen):
            return
        self._stop_requested = True
        for worker in self.workers:
            worker.cancel()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Format Disk[/]  "
            "[dim]Create Mavica-compatible FAT12 format[/]\n",
            id="title-bar",
        )
        yield Static(
            "  Format a physical floppy for use with Mavica cameras.\n"
        )
        yield DriveInput(
            label="Device",
            default="auto",
            show_mounts=False,
            autodetect_on_mount=False,
            id="drive-input",
        )
        yield Static(
            "  [dim][bold]Quick[/] — writes FAT12 structures only (~1 sec)\n"
            "  [bold]Full[/] — zeros + verifies every sector, then writes FAT12 (~2 min)[/]\n"
        )
        with Horizontal(classes="button-row"):
            yield Button("Quick Format", variant="error", id="btn-format", disabled=True)
            yield Button("Full Format", variant="error", id="btn-format-full", disabled=True)
            yield Button("Stop", variant="error", id="btn-stop", disabled=True)
            yield Button("Force Dismount & Retry", variant="warning", id="btn-force-dismount", disabled=True)
        with Horizontal(classes="button-row"):
            yield Button("I understand this erases all data", variant="warning", id="btn-confirm")

        yield ProgressBar(total=TOTAL_SECTORS, show_percentage=True, show_eta=True, id="progress")
        yield DefragMap(id="defrag-map")
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    _pending_full: bool = False  # Which format mode to retry after force dismount

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.query_one("#btn-format", Button).disabled = False
            self.query_one("#btn-format-full", Button).disabled = False
            self.query_one("#btn-confirm", Button).disabled = True
            self.query_one("#btn-confirm", Button).label = "Confirmed"
        elif event.button.id == "btn-format":
            self._start_format(full=False)
        elif event.button.id == "btn-format-full":
            self._start_format(full=True)
        elif event.button.id == "btn-stop":
            self._stop_requested = True
            self.query_one("#btn-stop", Button).disabled = True
        elif event.button.id == "btn-force-dismount":
            self._do_force_dismount()

    def _start_format(self, full: bool) -> None:
        device = self.query_one("#drive-input", DriveInput).value
        label = "MAVICA"

        if not device:
            self.notify("Enter a device path", severity="warning")
            return

        self._stop_requested = False
        for btn_id in ("#btn-format", "#btn-format-full"):
            self.query_one(btn_id, Button).disabled = True
        self.query_one("#btn-stop", Button).disabled = False

        defrag = self.query_one("#defrag-map", DefragMap)
        defrag.reset(clear_files=True)

        self.run_worker(self._run_format(device, label, full), exclusive=True)

    async def _run_format(self, device: str, label: str, full: bool) -> None:
        import asyncio

        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        progress = self.query_one("#progress", ProgressBar)
        defrag = self.query_one("#defrag-map", DefragMap)

        progress.update(total=TOTAL_SECTORS, progress=0)

        if full:
            log.write(f"[bold]Full format:[/] {device} (zero + verify every sector)...")

            def on_sector(idx, state):
                if self._stop_requested or worker.is_cancelled:
                    raise _StopRequested()
                self.app.call_from_thread(defrag.update_sector, idx, state)
                if idx % 50 == 0:
                    self.app.call_from_thread(progress.update, progress=idx)

            try:
                ok, msg, bad = await asyncio.to_thread(
                    format_floppy_full, device, label, on_sector=on_sector,
                )
            except _StopRequested:
                log.write("[yellow]Format stopped.[/]")
                log.write("[red]WARNING: Disk is in an incomplete state. Format again before use.[/]")
                self._finish_format()
                return

            progress.update(progress=TOTAL_SECTORS)

            if ok:
                if bad:
                    log.write(f"[#ffaa00]Done with {bad} bad sector(s). Disk has defects but is formatted.[/]")
                else:
                    log.write("[green]Done! All sectors verified. Disk is ready for Mavica use.[/]")
            else:
                self._handle_format_error(msg, full=True)
                return

        else:
            log.write(f"Quick format: {device}...")

            for s in range(33):
                defrag.update_sector(s, "reading")
            progress.update(progress=0)

            try:
                ok, msg = await asyncio.to_thread(format_floppy, device, label)
            except _StopRequested:
                log.write("[yellow]Format stopped.[/]")
                self._finish_format()
                return

            if ok:
                defrag.update_sector(0, "good")
                log.write("  [dim]Sector 0: boot sector[/]")
                for s in range(1, 10):
                    defrag.update_sector(s, "good")
                progress.update(progress=10)
                log.write("  [dim]Sectors 1-9: FAT1[/]")
                for s in range(10, 19):
                    defrag.update_sector(s, "good")
                progress.update(progress=19)
                log.write("  [dim]Sectors 10-18: FAT2[/]")
                for s in range(19, 33):
                    defrag.update_sector(s, "good")
                progress.update(progress=33)
                log.write("  [dim]Sectors 19-32: root directory[/]")
                log.write(f"  [dim]Sectors 33-2879: data area (unchanged)[/]")
                log.write("[green]Done! Disk is ready for Mavica use.[/]")
            else:
                for s in range(33):
                    defrag.update_sector(s, "bad")
                self._handle_format_error(msg, full=False)
                return

        self._finish_format()

    def _handle_format_error(self, msg: str, full: bool) -> None:
        """Handle format failure — detect blockers and offer force dismount."""
        log = self.query_one("#log", RichLog)
        log.write(f"[red]Format failed: {msg}[/]")

        self._pending_full = full

        if "lock volume" in msg.lower():
            device = self.query_one("#drive-input", DriveInput).value
            log.write("\n[bold]Checking what's using the drive...[/]")

            blockers = get_blocking_processes(device)
            if blockers:
                log.write("[#ffaa00]These programs may be blocking access:[/]")
                for b in blockers:
                    log.write(f"  [bold]>[/] {b}")
            else:
                log.write("[dim]Could not identify specific programs, but something has the drive open.[/]")

            log.write(
                "\n[bold]Options:[/]\n"
                "  1. Close Explorer windows showing the floppy drive, then retry\n"
                "  2. Click [bold]Force Dismount & Retry[/] to forcefully release the drive"
            )
            self.query_one("#btn-force-dismount", Button).disabled = False
        else:
            self._finish_format()

    def _do_force_dismount(self) -> None:
        """Force-dismount the volume and retry the format."""
        device = self.query_one("#drive-input", DriveInput).value
        label = "MAVICA"
        log = self.query_one("#log", RichLog)

        log.write("\n[bold]Force dismounting volume...[/]")
        ok, msg = force_dismount_volume(device)
        if ok:
            log.write(f"[green]{msg}[/]")
            log.write("[bold]Retrying format...[/]\n")
            self.query_one("#btn-force-dismount", Button).disabled = True
            self._start_format(full=self._pending_full)
        else:
            log.write(f"[red]Force dismount failed: {msg}[/]")
            log.write("[dim]Try closing all programs and run as Administrator.[/]")
            self._finish_format()

    def _finish_format(self) -> None:
        self.query_one("#btn-stop", Button).disabled = True
        self.query_one("#btn-format", Button).disabled = True
        self.query_one("#btn-format-full", Button).disabled = True
        self.query_one("#btn-force-dismount", Button).disabled = True
        self.query_one("#btn-confirm", Button).disabled = False
        self.query_one("#btn-confirm", Button).label = "I understand this erases all data"
