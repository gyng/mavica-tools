"""Multipass screen — multi-pass floppy disk imager."""

import os
import platform

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog, ProgressBar
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.multipass import merge_passes, read_pass_sectored, identify_bad_sectors, DISK_SIZE, SECTOR_SIZE, TOTAL_SECTORS
from mavica_tools.tui.widgets.sector_map import SectorMap
from mavica_tools.tui.widgets.defrag_map import DefragMap
from mavica_tools.tui.widgets.file_picker import FilePicker


class _StopRequested(Exception):
    """Raised by on_sector callback when the user clicks Stop & Merge."""


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
    _stop_requested: bool = False

    def on_screen_suspend(self) -> None:
        """Called when screen is overlaid (e.g. command palette) or navigated away.

        Only stop workers if actually leaving via Escape/pop — not for transient
        overlays like the command palette or screenshot dialog.
        """
        # Check if we're being suspended by a modal overlay (palette, dialog)
        # vs actually navigating away. Modal overlays push onto the stack
        # but the screen below stays mounted.
        from textual.screen import ModalScreen
        top = self.app.screen
        if isinstance(top, ModalScreen):
            return  # Don't interrupt work for overlays
        self._stop_requested = True
        for worker in self.workers:
            worker.cancel()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #ffaa00]Multi-Pass Floppy Imager[/]  [dim]Merge best sectors from multiple reads[/]\n", id="title-bar")

        system = platform.system()
        if system == "Windows":
            yield Static("  [dim]Windows: use [bold]\\\\.\\A:[/bold] for floppy drive A:[/]\n")
        elif system == "Darwin":
            yield Static("  [dim]macOS: use [bold]/dev/diskN[/bold] for USB floppy drive[/]\n")

        yield Static("  [bold]Device[/]  /  [bold]Passes[/]  /  [bold]Output Dir[/]")
        with Horizontal(classes="input-row"):
            yield Input(value=_default_floppy_device(), placeholder="Device or image path", id="device-path")
            yield Input(value="5", placeholder="Passes", id="pass-count")
            yield Input(value="mavica_out/disk_images", placeholder="Output dir", id="output-dir")
        with Horizontal(classes="button-row"):
            yield Button("Read Device", variant="success", id="btn-read")
            yield Button("Stop & Merge", variant="error", id="btn-stop", disabled=True)
            yield Button("Browse & Merge", variant="warning", id="btn-merge")
        yield ProgressBar(total=100, show_percentage=True, show_eta=True, id="progress")
        yield Static("", id="pass-status")
        yield DefragMap(id="defrag-map")
        yield Static("", id="sector-summary")
        yield Static("", id="next-step")
        with Horizontal(classes="button-row"):
            yield Button("Next: Extract with Names", variant="success", id="btn-next-fat12", disabled=True)
            yield Button("Next: Carve from Raw", variant="warning", id="btn-next-carve", disabled=True)
            yield Button("Open Folder", variant="default", id="btn-open-folder", disabled=True)
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        if self._prefill_output_dir:
            self.query_one("#output-dir", Input).value = self._prefill_output_dir

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-read":
            self._start_read()
        elif event.button.id == "btn-stop":
            self._stop_requested = True
            self.query_one("#btn-stop", Button).disabled = True
        elif event.button.id == "btn-merge":
            self.action_browse()
        elif event.button.id == "btn-next-carve":
            self._go_to_carve()
        elif event.button.id == "btn-next-fat12":
            self._go_to_fat12()
        elif event.button.id == "btn-open-folder":
            output_dir = self.query_one("#output-dir", Input).value.strip()
            if output_dir and os.path.isdir(output_dir):
                from mavica_tools.utils import open_directory
                open_directory(output_dir)

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
        self._stop_requested = False
        btn = self.query_one("#btn-read", Button)
        btn.disabled = True
        btn.label = "Reading..."
        self.query_one("#btn-stop", Button).disabled = False
        self.run_worker(self._read_device(device, passes, output_dir), exclusive=True)

    def _start_merge_from_dir(self, output_dir: str) -> None:
        self.run_worker(self._merge_images(output_dir), exclusive=True)

    async def _read_device(self, device: str, passes: int, output_dir: str) -> None:
        import asyncio

        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        status = self.query_one("#pass-status", Static)
        progress = self.query_one("#progress", ProgressBar)
        defrag = self.query_one("#defrag-map", DefragMap)
        system = platform.system()

        os.makedirs(output_dir, exist_ok=True)
        progress.update(total=passes * TOTAL_SECTORS, progress=0)
        log.write(f"[bold]Multi-pass read[/]: {device}, {passes} passes ({system})\n")

        image_paths = []
        good_sectors: set[int] = set()  # Sectors known good from prior passes
        stale_count = 0  # Consecutive passes with no new recovery
        total_recovered = 0  # Sectors recovered by passes 2+
        pass1_bad = 0  # Bad sectors after pass 1

        for p in range(1, passes + 1):
            if worker.is_cancelled or self._stop_requested:
                if image_paths:
                    log.write(f"[yellow]Stopped after {len(image_paths)} pass(es). Merging...[/]")
                    break
                log.write("[yellow]Cancelled.[/]")
                self._reset_read_button()
                return

            skip = good_sectors if p > 1 else None
            remaining = TOTAL_SECTORS - len(good_sectors) if p > 1 else TOTAL_SECTORS

            img_path = os.path.join(output_dir, f"pass_{p:02d}.img")
            if skip:
                status.update(f"  Pass {p}/{passes}: retrying {remaining} bad sector(s)...")
            else:
                status.update(f"  Pass {p}/{passes}: reading {device}...")
            defrag.reset(pass_num=p, clear_files=(p == 1))

            # Sector-by-sector callback for live defrag visualization
            sectors_read = [0]

            def on_sector(idx, state, _p=p):
                if self._stop_requested or worker.is_cancelled:
                    raise _StopRequested()
                self.app.call_from_thread(defrag.update_sector, idx, state)
                sectors_read[0] += 1
                if sectors_read[0] % 50 == 0:
                    self.app.call_from_thread(progress.update, progress=(_p - 1) * TOTAL_SECTORS + idx)

            def on_metadata_ready(data_bytes):
                """Called from worker thread once FAT12 metadata sectors are read."""
                try:
                    from mavica_tools.fat12 import file_sector_map_from_data
                    boundaries = file_sector_map_from_data(data_bytes)
                    if boundaries:
                        self.app.call_from_thread(defrag.set_file_boundaries, boundaries)
                        self.app.call_from_thread(
                            log.write,
                            f"  [dim]FAT12: {len(boundaries)} file(s) mapped on sector grid[/]",
                        )
                except Exception:
                    pass  # FAT12 unreadable — will retry after merge

            try:
                img_path, errors = await asyncio.to_thread(
                    read_pass_sectored, device, p, output_dir,
                    on_sector=on_sector,
                    on_metadata_ready=on_metadata_ready if p == 1 else None,
                    skip_sectors=skip,
                )
                image_paths.append(img_path)

                # Update good sectors and check for improvement
                bad = await asyncio.to_thread(identify_bad_sectors, img_path)
                new_good = (set(range(TOTAL_SECTORS)) - bad) - good_sectors
                good_sectors |= (set(range(TOTAL_SECTORS)) - bad)

                if errors:
                    log.write(f"  Pass {p}: [#ffaa00]{errors} error(s)[/]")
                else:
                    log.write(f"  Pass {p}: [green]clean read[/]")

                if p == 1:
                    pass1_bad = len(bad)
                    if pass1_bad > 0:
                        log.write(f"    [dim]{TOTAL_SECTORS - pass1_bad} good, {pass1_bad} bad[/]")
                else:
                    if new_good:
                        total_recovered += len(new_good)
                        remaining = TOTAL_SECTORS - len(good_sectors)
                        log.write(
                            f"    [green]+{len(new_good)} sector(s) recovered[/]"
                            f" [dim]({total_recovered} total recovered, {remaining} still bad)[/]"
                        )
                        stale_count = 0
                    else:
                        stale_count += 1
                        remaining = TOTAL_SECTORS - len(good_sectors)
                        log.write(f"    [dim]no new sectors recovered ({stale_count}/2), {remaining} still bad[/]")

                # Adaptive stop: 2 consecutive stale passes
                if stale_count >= 2 and p < passes:
                    log.write(f"  [bold]Stopping early:[/] no improvement in last 2 passes")
                    break

            except _StopRequested:
                partial = os.path.join(output_dir, f"pass_{p:02d}.img")
                if os.path.exists(partial) and os.path.getsize(partial) > 0:
                    image_paths.append(partial)
                log.write(f"[yellow]Stopped during pass {p}. Merging {len(image_paths)} pass(es)...[/]")
                break

            except FileNotFoundError:
                log.write(f"  [red]Device not found: {device}[/]")
                if system == "Windows":
                    log.write("  [dim]Check that the floppy drive is connected and disk is inserted.[/]")
                    log.write(r"  [dim]Windows device path should be \\.\A: — run as Administrator.[/]")
                elif system == "Darwin":
                    log.write("  [dim]Check 'diskutil list' for the correct device path.[/]")
                else:
                    log.write("  [dim]Check that /dev/fd0 exists and you have read permission.[/]")
                    log.write("  [dim]USB floppy drives may appear as /dev/sdX instead.[/]")
                self.notify(f"Device not found: {device}", severity="error", timeout=5)
                self._reset_read_button()
                return

            progress.update(progress=p * TOTAL_SECTORS)

        if not image_paths:
            log.write("[red]No successful reads.[/]")
            self._reset_read_button()
            return

        status.update("  Merging passes...")
        if total_recovered > 0:
            log.write(
                f"\n[bold #33ff33]Multi-pass recovered {total_recovered} sector(s)[/] "
                f"that failed on the first read"
            )
        log.write("[bold]Merging...[/]")
        merged, sector_status = await asyncio.to_thread(merge_passes, image_paths)

        merged_path = os.path.join(output_dir, "merged.img")
        with open(merged_path, "wb") as f:
            f.write(merged)

        self._show_results(sector_status, merged_path, image_paths)
        self._reset_read_button()
        self.query_one("#btn-stop", Button).disabled = True

    async def _merge_images(self, output_dir: str) -> None:
        import asyncio
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
        merged, sector_status = await asyncio.to_thread(merge_passes, img_files)

        merged_path = os.path.join(output_dir, "merged.img")
        with open(merged_path, "wb") as f:
            f.write(merged)

        self._show_results(sector_status, merged_path, img_files)

    def _show_results(self, sector_status, merged_path, pass_image_paths=None):
        log = self.query_one("#log", RichLog)
        status = self.query_one("#pass-status", Static)
        defrag = self.query_one("#defrag-map", DefragMap)

        defrag.set_merged_result(sector_status)

        # Overlay file boundaries from FAT12
        try:
            from mavica_tools.fat12 import file_sector_map
            boundaries = file_sector_map(merged_path)
            if boundaries:
                defrag.set_file_boundaries(boundaries)
                log.write(f"  [dim]FAT12: {len(boundaries)} file(s) mapped on sector grid[/]")
            else:
                log.write("  [#ffaa00]No files found in FAT12 filesystem[/]")
        except Exception as e:
            log.write(f"  [#ffaa00]FAT12 unreadable ({e})[/]")
            self.notify("FAT12 damaged — file overlay unavailable. Try Carve from Raw.", severity="warning", timeout=5)

        total = len(sector_status)
        good = sector_status.count("good")
        recovered = sector_status.count("recovered")
        blank = sector_status.count("blank")
        conflict = sector_status.count("conflict")

        from mavica_tools.fun import health_bar_rich, sector_sparkline_rich, recovery_suggestions

        readable_pct = 100 * (good + recovered) / total if total else 0

        self.query_one("#sector-summary", Static).update(
            health_bar_rich(readable_pct) + "\n"
            + sector_sparkline_rich(sector_status) + "\n\n"
            f"  [bold]Sectors:[/] {total} total — "
            f"[green]{good} good ({100 * good / total:.1f}%)[/]  "
            f"[#33aaff]{recovered} recovered[/]  "
            f"[red]{blank} blank[/]  "
            f"[magenta]{conflict} conflict[/]"
        )
        log.write(f"\n[green]Merged image: {merged_path}[/]")

        # Show suggestions
        suggestions = recovery_suggestions(sector_status)
        for s in suggestions:
            log.write(f"  [dim]{s}[/]")

        # Drive vs disk diagnostics
        if blank > 0:
            try:
                from mavica_tools.diagnose import diagnose_errors, format_diagnosis
                diag = diagnose_errors(
                    pass_image_paths=pass_image_paths,
                    sector_status=sector_status,
                )
                if diag.evidence:
                    log.write(f"\n[bold]Diagnosis:[/]")
                    log.write(format_diagnosis(diag, rich=True))
            except Exception:
                pass  # Diagnostics are best-effort

        status.update(f"  Done — {merged_path}")

        self.query_one("#next-step", Static).update(
            "\n  [bold #33ff33]What next?[/]\n"
            "  [bold]Extract with Names[/] — tries to recover original filenames (MVC-001.JPG)\n"
            "  [bold]Carve from Raw[/] — scans for JPEG data directly (works if filesystem is damaged)\n"
        )
        self.query_one("#btn-next-fat12", Button).disabled = False
        self.query_one("#btn-next-carve", Button).disabled = False
        self.query_one("#btn-open-folder", Button).disabled = False
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
