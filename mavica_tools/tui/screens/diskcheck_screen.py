"""Disk checker screen — test if a floppy is safe for camera use."""

import os
import platform

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog, ProgressBar
from textual.containers import Horizontal, VerticalScroll
from textual.worker import get_current_worker

from mavica_tools.multipass import TOTAL_SECTORS
from mavica_tools.tui.widgets.defrag_map import DefragMap


class _StopRequested(Exception):
    pass


def _default_floppy_device() -> str:
    system = platform.system()
    if system == "Windows":
        return r"\\.\A:"
    elif system == "Darwin":
        return "/dev/disk2"
    return "/dev/fd0"


class DiskCheckScreen(Screen):
    """Test a floppy disk before putting it in the camera."""

    DEFAULT_CSS = """
    VerticalScroll {
        height: 1fr;
    }
    #progress {
        width: 1fr;
    }
    #check-buttons {
        margin: 0 1 0 1 !important;
    }
    #help-text {
        margin: 0 0 0 1;
        padding: 0;
    }
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("f", "full_check", "Full Check"),
        Binding("q", "quick_check", "Quick Check"),
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
        with VerticalScroll():
            yield Static(
                "[bold #ffaa00]Disk Checker[/]  [dim]Test if a floppy is safe for camera use[/]\n",
                id="title-bar",
            )
            with Horizontal(classes="input-row"):
                yield Static("  [bold]Device[/] ", classes="row-label")
                yield Input(value=_default_floppy_device(), placeholder="Device path", id="device-path")
                yield Button("Browse", id="btn-browse-device")
            with Horizontal(classes="button-row", id="check-buttons"):
                yield Button("Full (f)", variant="success", id="btn-full")
                yield Button("Quick (q)", variant="warning", id="btn-quick")
                yield Button("Write Test", variant="error", id="btn-write")
                yield Static("  [dim][red]Erases all data!")
            yield Static("[dim]  Full: read every sector (~2 min) · Quick: spot-check sampled tracks (~20 sec)[/]\n", id="help-text")
            with Horizontal(classes="button-row"):
                yield ProgressBar(total=TOTAL_SECTORS, show_percentage=True, show_eta=True, id="progress")
                yield Button("Stop", variant="error", id="btn-stop", disabled=True)
            yield DefragMap(id="defrag-map")
            yield Static("", id="verdict")
            yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse-device":
            self._browse_device()
        elif event.button.id == "btn-full":
            self._start_check(quick=False, write=False)
        elif event.button.id == "btn-quick":
            self._start_check(quick=True, write=False)
        elif event.button.id == "btn-write":
            self._confirm_write()
        elif event.button.id == "btn-stop":
            self._stop_requested = True
            self.query_one("#btn-stop", Button).disabled = True

    def action_full_check(self) -> None:
        btn = self.query_one("#btn-full", Button)
        if not btn.disabled:
            self._start_check(quick=False, write=False)

    def action_quick_check(self) -> None:
        btn = self.query_one("#btn-quick", Button)
        if not btn.disabled:
            self._start_check(quick=True, write=False)

    def _browse_device(self) -> None:
        """Show detected floppy drives for selection."""
        from textual.screen import ModalScreen
        from textual.widgets import Static, OptionList
        from textual.widgets.option_list import Option
        from textual.containers import Vertical
        from mavica_tools.detect import detect_floppy_drives

        drives = detect_floppy_drives()

        class DrivePickerScreen(ModalScreen[str]):
            DEFAULT_CSS = """
            DrivePickerScreen {
                align: center middle;
            }
            #drive-dialog {
                width: 50;
                height: auto;
                max-height: 16;
                border: thick #33ff33;
                background: #0a0a0a;
                padding: 1 2;
            }
            #drive-dialog OptionList {
                height: auto;
                max-height: 10;
            }
            """
            BINDINGS = [("escape", "cancel", "Cancel")]

            def compose(self):
                with Vertical(id="drive-dialog"):
                    yield Static("[bold #ffaa00]Select Drive[/]\n")
                    options = []
                    for d in drives:
                        size = f" ({d.size_bytes:,} bytes)" if d.size_bytes else ""
                        options.append(Option(
                            f"[bold]{d.device}[/]  [dim]{d.label}{size}[/]",
                            id=d.device,
                        ))
                    if not options:
                        options.append(Option("[dim]No floppy drives detected[/]", disabled=True))
                    yield OptionList(*options, id="drive-list")

            def on_option_list_option_selected(self, event):
                if event.option.id:
                    self.dismiss(event.option.id)

            def action_cancel(self):
                self.dismiss("")

        def on_result(device: str) -> None:
            if device:
                self.query_one("#device-path", Input).value = device

        self.app.push_screen(DrivePickerScreen(), on_result)

    def _start_check(self, quick: bool, write: bool) -> None:
        device = self.query_one("#device-path", Input).value.strip()
        if not device:
            self.notify("Enter a device path", severity="warning")
            return
        self._stop_requested = False
        for btn_id in ("#btn-full", "#btn-quick", "#btn-write"):
            self.query_one(btn_id, Button).disabled = True
        self.query_one("#btn-stop", Button).disabled = False
        self.query_one("#verdict", Static).update("")
        self.run_worker(self._run_check(device, quick, write), exclusive=True)

    def _confirm_write(self) -> None:
        """Show write test warning before starting."""
        log = self.query_one("#log", RichLog)
        device = self.query_one("#device-path", Input).value.strip()
        if not device:
            self.notify("Enter a device path", severity="warning")
            return

        # First do a read to check for existing files
        log.write("[bold red]WARNING: Write test will DESTROY ALL DATA on the disk.[/]")
        log.write("[dim]Starting read-only check first to show existing files...[/]")
        self._stop_requested = False
        for btn_id in ("#btn-full", "#btn-quick", "#btn-write"):
            self.query_one(btn_id, Button).disabled = True
        self.query_one("#btn-stop", Button).disabled = False
        self.run_worker(self._run_write_preflight(device), exclusive=True)

    async def _run_write_preflight(self, device: str) -> None:
        """Read disk to show files, then confirm and run write test."""
        import asyncio
        from mavica_tools.diskcheck import check_read_only

        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        defrag = self.query_one("#defrag-map", DefragMap)
        progress = self.query_one("#progress", ProgressBar)

        defrag.reset(clear_files=True)
        progress.update(total=TOTAL_SECTORS, progress=0)
        sectors_read = [0]
        pending_result = [None]

        def on_sector(idx, state):
            if self._stop_requested or worker.is_cancelled:
                raise _StopRequested()
            if state == "reading":
                if pending_result[0] is not None:
                    pi, ps = pending_result[0]
                    self.app.call_from_thread(defrag.update_sector, pi, ps)
                    pending_result[0] = None
                self.app.call_from_thread(defrag.update_sector, idx, state)
            else:
                pending_result[0] = (idx, state)
            sectors_read[0] += 1
            if sectors_read[0] % 50 == 0:
                self.app.call_from_thread(progress.update, progress=idx)

        def on_metadata_ready(data_bytes):
            try:
                from mavica_tools.fat12 import file_sector_map_from_data
                boundaries = file_sector_map_from_data(data_bytes)
                if boundaries:
                    self.app.call_from_thread(defrag.set_file_boundaries, boundaries)
            except Exception:
                pass

        try:
            result = await asyncio.to_thread(
                check_read_only, device,
                on_sector=on_sector,
                on_metadata_ready=on_metadata_ready,
            )
        except _StopRequested:
            log.write("[yellow]Cancelled.[/]")
            self._reset_buttons()
            return
        except (FileNotFoundError, OSError) as e:
            log.write(f"[red]Error: {e}[/]")
            self._reset_buttons()
            return

        if pending_result[0] is not None:
            pi, ps = pending_result[0]
            defrag.update_sector(pi, ps)

        progress.update(progress=TOTAL_SECTORS)
        defrag._current_sector = -1
        defrag.refresh()

        if result.file_list:
            log.write(f"\n[bold red]This disk contains {len(result.file_list)} file(s):[/]")
            for name, size in result.file_list:
                log.write(f"  {name:<15s}  {size:>6,} bytes")
            log.write("[bold red]Write test will DESTROY these files.[/]")

        log.write("\n[bold]Click 'Confirm Write Test' to proceed, or 'Stop' to cancel.[/]")

        # Replace buttons with confirm/cancel
        self.query_one("#btn-write", Button).label = "Confirm Write Test"
        self.query_one("#btn-write", Button).disabled = False
        self.query_one("#btn-stop", Button).disabled = False

        # Swap the write handler to actually run the write test
        self._pending_write_device = device
        self._write_confirmed = True
        self._reset_buttons()
        self.query_one("#btn-write", Button).label = "Confirm Write Test"
        self.query_one("#btn-write", Button).disabled = False

    async def _run_check(self, device: str, quick: bool, write: bool) -> None:
        import asyncio

        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        progress = self.query_one("#progress", ProgressBar)
        defrag = self.query_one("#defrag-map", DefragMap)

        defrag.reset(clear_files=True)
        log.clear()

        if write:
            mode = "Write-verify test"
        elif quick:
            mode = "Quick spot check"
        else:
            mode = "Full read check"
        log.write(f"[bold]{mode}[/]: {device}")

        sectors_read = [0]
        progress.update(total=TOTAL_SECTORS, progress=0)
        pending_result = [None]  # (idx, state) waiting to be flushed

        def on_sector(idx, state):
            if self._stop_requested or worker.is_cancelled:
                raise _StopRequested()
            if state == "reading":
                # Flush previous sector's final state together with new reading indicator
                if pending_result[0] is not None:
                    pi, ps = pending_result[0]
                    self.app.call_from_thread(defrag.update_sector, pi, ps)
                    pending_result[0] = None
                self.app.call_from_thread(defrag.update_sector, idx, state)
            else:
                # Defer good/bad — will be flushed when next "reading" arrives
                pending_result[0] = (idx, state)
            sectors_read[0] += 1
            if sectors_read[0] % 50 == 0:
                self.app.call_from_thread(progress.update, progress=idx)

        def on_metadata_ready(data_bytes):
            try:
                from mavica_tools.fat12 import file_sector_map_from_data
                boundaries = file_sector_map_from_data(data_bytes)
                if boundaries:
                    self.app.call_from_thread(defrag.set_file_boundaries, boundaries)
                    self.app.call_from_thread(
                        log.write,
                        f"  [dim]FAT12: {len(boundaries)} file(s) on disk[/]",
                    )
            except Exception:
                pass

        try:
            if write:
                from mavica_tools.diskcheck import check_write_verify
                result = await asyncio.to_thread(
                    check_write_verify, device, on_sector=on_sector,
                )
            else:
                from mavica_tools.diskcheck import check_read_only
                result = await asyncio.to_thread(
                    check_read_only, device,
                    on_sector=on_sector,
                    on_metadata_ready=on_metadata_ready if not write else None,
                    quick=quick,
                )
        except _StopRequested:
            log.write("[yellow]Cancelled.[/]")
            self._reset_buttons()
            return
        except FileNotFoundError:
            log.write(f"[red]Device not found: {device}[/]")
            system = platform.system()
            if system == "Windows":
                log.write(r"  [dim]Windows device path should be \\.\A: — run as Administrator.[/]")
            elif system == "Darwin":
                log.write("  [dim]Check 'diskutil list' for the correct device path.[/]")
            else:
                log.write("  [dim]Check that /dev/fd0 exists and you have read permission.[/]")
            self.notify(f"Device not found: {device}", severity="error", timeout=5)
            self._reset_buttons()
            return
        except (OSError, PermissionError) as e:
            if "write-protected" in str(e).lower() or "permission" in str(e).lower():
                log.write("[red]Disk is write-protected or permission denied.[/]")
                log.write("[dim]For write test: slide the write-protect tab on the disk.[/]")
            else:
                log.write(f"[red]Error: {e}[/]")
            self._reset_buttons()
            return

        # Flush last pending sector result
        if pending_result[0] is not None:
            pi, ps = pending_result[0]
            defrag.update_sector(pi, ps)

        progress.update(progress=TOTAL_SECTORS)

        # Stop the spinning read head indicator
        defrag._current_sector = -1
        defrag.refresh()

        # Show verdict
        self._show_verdict(result)
        self._reset_buttons()

    def _show_verdict(self, result) -> None:
        log = self.query_one("#log", RichLog)
        verdict_widget = self.query_one("#verdict", Static)

        if result.safe:
            verdict_widget.update(
                f"\n  [bold white on green]  PASS  [/]  "
                f"[bold green]{result.headline}[/]\n"
            )
        elif "CAUTION" in result.headline:
            verdict_widget.update(
                f"\n  [bold black on yellow]  CAUTION  [/]  "
                f"[bold #ffaa00]{result.headline}[/]\n"
            )
        else:
            verdict_widget.update(
                f"\n  [bold white on red]  FAIL  [/]  "
                f"[bold red]{result.headline}[/]\n"
            )

        # Stats
        good = result.tested_sectors - len(result.bad_sectors)
        log.write(f"\n  Tested: {result.tested_sectors}/{result.total_sectors} sectors")
        log.write(f"  [green]Good: {good}[/]  [red]Bad: {len(result.bad_sectors)}[/]")
        if result.elapsed_seconds > 0:
            elapsed = result.elapsed_seconds
            bytes_read = result.tested_sectors * 512
            speed_kbs = bytes_read / 1024 / elapsed if elapsed > 0 else 0
            if elapsed >= 60:
                time_str = f"{int(elapsed // 60)}m {elapsed % 60:.1f}s"
            else:
                time_str = f"{elapsed:.1f}s"
            log.write(f"  Time: {time_str}  Read speed: {speed_kbs:.1f} KB/s")
        if result.write_errors:
            log.write(f"  Write errors: {result.write_errors}")
        if result.bad_tracks:
            log.write(f"  Bad tracks: {sorted(result.bad_tracks)}")

        if result.file_list:
            log.write(f"\n  [bold]Files on disk ({len(result.file_list)}):[/]")
            for name, size in result.file_list:
                log.write(f"    {name:<15s}  {size:>6,} bytes")

        # Diagnosis
        if result.diagnosis:
            from mavica_tools.diagnose import format_diagnosis
            log.write(f"\n[bold]Diagnosis:[/]")
            log.write(format_diagnosis(result.diagnosis, rich=True))

    def _reset_buttons(self) -> None:
        for btn_id in ("#btn-full", "#btn-quick", "#btn-write"):
            btn = self.query_one(btn_id, Button)
            btn.disabled = False
        self.query_one("#btn-write", Button).label = "Write Test"
        self.query_one("#btn-stop", Button).disabled = True
        self._write_confirmed = False
