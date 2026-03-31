"""Multipass screen — multi-pass floppy disk imager."""

import os
import platform
import sys

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.multipass import (
    merge_passes,
    read_image_file,
    DISK_SIZE,
    SECTOR_SIZE,
    TOTAL_SECTORS,
)
from mavica_tools.tui.widgets.sector_map import SectorMap


def _default_floppy_device() -> str:
    """Return the default floppy device path for this platform."""
    system = platform.system()
    if system == "Linux":
        return "/dev/fd0"
    elif system == "Darwin":
        return "/dev/disk2"  # macOS — varies, user should verify
    elif system == "Windows":
        return r"\\.\A:"
    return "/dev/fd0"


def _platform_read_supported() -> bool:
    """Check if direct floppy reads are supported on this platform."""
    system = platform.system()
    if system == "Linux":
        return True
    elif system == "Windows":
        return True  # Can use PowerShell or direct device access
    elif system == "Darwin":
        return True  # Can use dd on macOS with USB floppy
    return False


class MultipassScreen(Screen):
    """Multi-pass floppy disk imager with sector map."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #ffaa00]Multi-Pass Floppy Imager[/]\n", id="title-bar")

        system = platform.system()
        if system == "Windows":
            yield Static(
                "  [dim]Windows: Use device path like [bold]\\\\.\\A:[/bold] "
                "for floppy drive A:[/]\n"
            )

        with Horizontal():
            yield Input(
                placeholder="Floppy device or image path",
                value=_default_floppy_device(),
                id="device-path",
            )
            yield Input(placeholder="Passes", value="5", id="pass-count")
            yield Input(placeholder="Output dir", value="disk_recovery", id="output-dir")
        with Horizontal():
            yield Button("Read Device", variant="success", id="btn-read")
            yield Button("Merge Images", variant="warning", id="btn-merge")
            yield Button("Carve Merged ->", variant="default", id="btn-carve", disabled=True)

        yield Static("", id="pass-status")
        yield SectorMap(id="sector-map")
        yield Static("", id="sector-summary")
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-read":
            self._start_read()
        elif event.button.id == "btn-merge":
            self._start_merge()
        elif event.button.id == "btn-carve":
            self.app.push_screen("carve")

    def _start_read(self) -> None:
        device = self.query_one("#device-path", Input).value.strip()
        passes = int(self.query_one("#pass-count", Input).value.strip() or "5")
        output_dir = self.query_one("#output-dir", Input).value.strip()

        if not device:
            self.notify("Enter a device path", severity="warning")
            return

        self.run_worker(
            self._read_device(device, passes, output_dir), exclusive=True
        )

    def _start_merge(self) -> None:
        output_dir = self.query_one("#output-dir", Input).value.strip()
        if not output_dir or not os.path.isdir(output_dir):
            self.notify("Enter an output directory with existing .img files", severity="warning")
            return
        self.run_worker(self._merge_images(output_dir), exclusive=True)

    async def _read_device(self, device: str, passes: int, output_dir: str) -> None:
        """Read floppy device multiple times using platform-appropriate method."""
        import subprocess

        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        status = self.query_one("#pass-status", Static)

        os.makedirs(output_dir, exist_ok=True)
        system = platform.system()

        log.write(f"[bold]Multi-pass read[/]: {device}, {passes} passes")
        log.write(f"Platform: {system}\n")

        image_paths = []

        for p in range(1, passes + 1):
            if worker.is_cancelled:
                return

            img_path = os.path.join(output_dir, f"pass_{p:02d}.img")
            log_path = os.path.join(output_dir, f"pass_{p:02d}.log")
            status.update(f"  Pass {p}/{passes}: reading {device}...")

            try:
                if system == "Windows":
                    # Windows: use PowerShell to read raw device
                    # Or use python's own file I/O for \\.\A:
                    log.write(f"  Pass {p}: reading via direct I/O...")
                    try:
                        with open(device, "rb") as dev:
                            data = dev.read(DISK_SIZE)
                        with open(img_path, "wb") as f:
                            f.write(data)
                        log.write(f"  Pass {p}: [green]read {len(data):,} bytes[/]")
                    except PermissionError:
                        log.write(
                            f"  Pass {p}: [red]Permission denied.[/] "
                            "Try running as Administrator."
                        )
                        continue
                    except OSError as e:
                        log.write(f"  Pass {p}: [red]Error: {e}[/]")
                        continue
                else:
                    # Linux/macOS: use dd
                    result = subprocess.run(
                        [
                            "dd",
                            f"if={device}",
                            f"of={img_path}",
                            f"bs={SECTOR_SIZE}",
                            "conv=noerror,sync",
                        ],
                        capture_output=True,
                        text=True,
                    )
                    with open(log_path, "w") as f:
                        f.write(result.stderr)

                    errors = result.stderr.lower().count("error")
                    if errors:
                        log.write(f"  Pass {p}: [#ffaa00]{errors} error(s)[/]")
                    else:
                        log.write(f"  Pass {p}: [green]clean read[/]")

                image_paths.append(img_path)

            except FileNotFoundError:
                log.write(f"  [red]Device not found: {device}[/]")
                log.write("  Check that the floppy drive is connected and the disk is inserted.")
                return

        if not image_paths:
            log.write("[red]No successful reads.[/]")
            return

        # Merge
        status.update("  Merging passes...")
        log.write("\n[bold]Merging passes...[/]")
        merged, sector_status = merge_passes(image_paths)

        merged_path = os.path.join(output_dir, "merged.img")
        with open(merged_path, "wb") as f:
            f.write(merged)

        self._update_sector_display(sector_status)
        log.write(f"\n[green]Merged image: {merged_path}[/]")
        status.update(f"  Done — merged image: {merged_path}")
        self.query_one("#btn-carve", Button).disabled = False

    async def _merge_images(self, output_dir: str) -> None:
        """Merge existing .img files from a directory."""
        import glob as globmod

        log = self.query_one("#log", RichLog)
        status = self.query_one("#pass-status", Static)

        img_files = sorted(globmod.glob(os.path.join(output_dir, "pass_*.img")))
        if not img_files:
            img_files = sorted(globmod.glob(os.path.join(output_dir, "*.img")))
            # Exclude merged.img
            img_files = [f for f in img_files if "merged" not in os.path.basename(f)]

        if not img_files:
            log.write("[red]No .img files found in directory.[/]")
            return

        log.write(f"Merging {len(img_files)} image(s)...")
        status.update("  Merging...")

        merged, sector_status = merge_passes(img_files)

        merged_path = os.path.join(output_dir, "merged.img")
        with open(merged_path, "wb") as f:
            f.write(merged)

        self._update_sector_display(sector_status)
        log.write(f"\n[green]Merged image: {merged_path}[/]")
        status.update(f"  Done — merged image: {merged_path}")
        self.query_one("#btn-carve", Button).disabled = False

    def _update_sector_display(self, sector_status: list) -> None:
        sector_map = self.query_one("#sector-map", SectorMap)
        sector_map.sector_status = sector_status

        total = len(sector_status)
        good = sector_status.count("good")
        recovered = sector_status.count("recovered")
        blank = sector_status.count("blank")
        conflict = sector_status.count("conflict")

        summary = self.query_one("#sector-summary", Static)
        summary.update(
            f"  [bold]Sectors:[/] {total} total — "
            f"[green]{good} good ({100 * good / total:.1f}%)[/]  "
            f"[#33aaff]{recovered} recovered[/]  "
            f"[red]{blank} blank[/]  "
            f"[magenta]{conflict} conflict[/]"
        )
