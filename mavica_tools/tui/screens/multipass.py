"""Multipass screen — multi-pass floppy disk imager."""

import os
import platform

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog, ProgressBar
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.multipass import merge_passes, DISK_SIZE, SECTOR_SIZE
from mavica_tools.tui.widgets.sector_map import SectorMap
from mavica_tools.tui.widgets.file_picker import FilePicker


def _default_floppy_device() -> str:
    system = platform.system()
    if system == "Windows":
        return r"\\.\A:"
    elif system == "Darwin":
        return "/dev/disk2"
    return "/dev/fd0"


class MultipassScreen(Screen):
    """Multi-pass floppy disk imager with sector map."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
    ]

    _prefill_output_dir: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #ffaa00]Multi-Pass Floppy Imager[/]  [dim]Merge best sectors from multiple reads[/]\n", id="title-bar")

        system = platform.system()
        if system == "Windows":
            yield Static("  [dim]Windows: use [bold]\\\\.\\A:[/bold] for floppy drive A:[/]\n")
        elif system == "Darwin":
            yield Static("  [dim]macOS: use [bold]/dev/diskN[/bold] for USB floppy drive[/]\n")

        with Horizontal(classes="input-row"):
            yield Input(value=_default_floppy_device(), placeholder="Device or image path", id="device-path")
            yield Input(value="5", placeholder="Passes", id="pass-count")
            yield Input(value="disk_recovery", placeholder="Output dir", id="output-dir")
        with Horizontal(classes="button-row"):
            yield Button("Read Device", variant="success", id="btn-read")
            yield Button("Browse & Merge", variant="warning", id="btn-merge")
        yield ProgressBar(total=100, show_percentage=True, show_eta=False, id="progress")
        yield Static("", id="pass-status")
        yield SectorMap(id="sector-map")
        yield Static("", id="sector-summary")
        yield Static("", id="next-step")
        with Horizontal(classes="button-row"):
            yield Button("Next: Extract with Names", variant="success", id="btn-next-fat12", disabled=True)
            yield Button("Next: Carve from Raw", variant="warning", id="btn-next-carve", disabled=True)
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        if self._prefill_output_dir:
            self.query_one("#output-dir", Input).value = self._prefill_output_dir

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-read":
            self._start_read()
        elif event.button.id == "btn-merge":
            self.action_browse()
        elif event.button.id == "btn-next-carve":
            self._go_to_carve()
        elif event.button.id == "btn-next-fat12":
            self._go_to_fat12()

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#output-dir", Input).value = os.path.dirname(path) or "."
                self._start_merge_from_dir(os.path.dirname(path) or ".")
        self.app.push_screen(
            FilePicker(
                extensions=(".img",),
                title="Select a directory containing .img files",
                select_directory=True,
            ),
            on_selected,
        )

    def _start_read(self) -> None:
        device = self.query_one("#device-path", Input).value.strip()
        passes = int(self.query_one("#pass-count", Input).value.strip() or "5")
        output_dir = self.query_one("#output-dir", Input).value.strip()
        if not device:
            self.notify("Enter a device path", severity="warning")
            return
        btn = self.query_one("#btn-read", Button)
        btn.disabled = True
        btn.label = "Reading..."
        self.run_worker(self._read_device(device, passes, output_dir), exclusive=True)

    def _start_merge_from_dir(self, output_dir: str) -> None:
        self.run_worker(self._merge_images(output_dir), exclusive=True)

    async def _read_device(self, device: str, passes: int, output_dir: str) -> None:
        import subprocess

        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        status = self.query_one("#pass-status", Static)
        progress = self.query_one("#progress", ProgressBar)
        system = platform.system()

        os.makedirs(output_dir, exist_ok=True)
        progress.update(total=passes, progress=0)
        log.write(f"[bold]Multi-pass read[/]: {device}, {passes} passes ({system})\n")

        image_paths = []

        for p in range(1, passes + 1):
            if worker.is_cancelled:
                log.write("[yellow]Cancelled.[/]")
                self._reset_read_button()
                return

            img_path = os.path.join(output_dir, f"pass_{p:02d}.img")
            log_path = os.path.join(output_dir, f"pass_{p:02d}.log")
            status.update(f"  Pass {p}/{passes}: reading {device}...")

            try:
                if system == "Windows":
                    log.write(f"  Pass {p}: reading via direct I/O...")
                    try:
                        with open(device, "rb") as dev:
                            data = dev.read(DISK_SIZE)
                        with open(img_path, "wb") as f:
                            f.write(data)
                        log.write(f"  Pass {p}: [green]read {len(data):,} bytes[/]")
                    except PermissionError:
                        log.write(f"  Pass {p}: [red]Permission denied — run as Administrator[/]")
                        continue
                    except OSError as e:
                        log.write(f"  Pass {p}: [red]{e}[/]")
                        continue
                else:
                    result = subprocess.run(
                        ["dd", f"if={device}", f"of={img_path}",
                         f"bs={SECTOR_SIZE}", "conv=noerror,sync"],
                        capture_output=True, text=True,
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
                self.notify(f"Device not found: {device}", severity="error", timeout=5)
                self._reset_read_button()
                return

            progress.update(progress=p)

        if not image_paths:
            log.write("[red]No successful reads.[/]")
            self._reset_read_button()
            return

        status.update("  Merging passes...")
        log.write("\n[bold]Merging...[/]")
        merged, sector_status = merge_passes(image_paths)

        merged_path = os.path.join(output_dir, "merged.img")
        with open(merged_path, "wb") as f:
            f.write(merged)

        self._show_results(sector_status, merged_path)
        self._reset_read_button()

    async def _merge_images(self, output_dir: str) -> None:
        import glob as globmod

        log = self.query_one("#log", RichLog)
        status = self.query_one("#pass-status", Static)

        img_files = sorted(globmod.glob(os.path.join(output_dir, "pass_*.img")))
        if not img_files:
            img_files = sorted(globmod.glob(os.path.join(output_dir, "*.img")))
            img_files = [f for f in img_files if "merged" not in os.path.basename(f)]

        if not img_files:
            log.write("[red]No .img files found.[/]")
            self.notify("No .img files found in directory", severity="error")
            return

        log.write(f"Merging {len(img_files)} image(s)...")
        status.update("  Merging...")
        merged, sector_status = merge_passes(img_files)

        merged_path = os.path.join(output_dir, "merged.img")
        with open(merged_path, "wb") as f:
            f.write(merged)

        self._show_results(sector_status, merged_path)

    def _show_results(self, sector_status, merged_path):
        log = self.query_one("#log", RichLog)
        status = self.query_one("#pass-status", Static)

        self.query_one("#sector-map", SectorMap).sector_status = sector_status

        total = len(sector_status)
        good = sector_status.count("good")
        recovered = sector_status.count("recovered")
        blank = sector_status.count("blank")
        conflict = sector_status.count("conflict")

        self.query_one("#sector-summary", Static).update(
            f"  [bold]Sectors:[/] {total} total — "
            f"[green]{good} good ({100 * good / total:.1f}%)[/]  "
            f"[#33aaff]{recovered} recovered[/]  "
            f"[red]{blank} blank[/]  "
            f"[magenta]{conflict} conflict[/]"
        )
        log.write(f"\n[green]Merged image: {merged_path}[/]")
        status.update(f"  Done — {merged_path}")

        self.query_one("#next-step", Static).update(
            "\n  [bold #33ff33]What next?[/]\n"
            "  [bold]Extract with Names[/] — tries to recover original filenames (MVC-001.JPG)\n"
            "  [bold]Carve from Raw[/] — scans for JPEG data directly (works if filesystem is damaged)\n"
        )
        self.query_one("#btn-next-fat12", Button).disabled = False
        self.query_one("#btn-next-carve", Button).disabled = False
        self._merged_path = merged_path

    def _reset_read_button(self) -> None:
        btn = self.query_one("#btn-read", Button)
        btn.disabled = False
        btn.label = "Read Device"

    def _go_to_carve(self) -> None:
        if hasattr(self, "_merged_path"):
            screen = self.app.SCREENS["carve"]()
            screen._prefill_image = self._merged_path
            self.app.push_screen(screen)

    def _go_to_fat12(self) -> None:
        if hasattr(self, "_merged_path"):
            screen = self.app.SCREENS["fat12"]()
            screen._prefill_image = self._merged_path
            self.app.push_screen(screen)
