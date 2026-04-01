"""Reusable drive/device input widget with async autodetect and browse.

Used by import, disk checker, and format screens for consistent
floppy drive selection.
"""

import asyncio
import platform

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Static


def _default_floppy_device() -> str:
    system = platform.system()
    if system == "Windows":
        return r"\\.\A:"
    elif system == "Darwin":
        return "/dev/disk2"
    return "/dev/fd0"


_SPINNER = "\u280b\u2819\u2838\u2830\u2826\u2807"  # braille spinner ⠋⠙⠸⠰⠦⠇


def _fmt_size(size_bytes: int) -> str:
    """Format bytes as a human-readable size."""
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    elif size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.0f} KB"
    return f"{size_bytes:,} B"


def _mount_info(path: str) -> str:
    """Get volume label and size info for a mounted path."""
    import shutil

    parts = []
    try:
        usage = shutil.disk_usage(path)
        parts.append(_fmt_size(usage.total))
        used_pct = 100 * usage.used / usage.total if usage.total else 0
        parts.append(f"{used_pct:.0f}% used")
    except OSError:
        pass
    if parts:
        sep = " \u2014 "
        return f"[dim]mounted  {sep.join(parts)}[/]"
    return "[dim]mounted[/]"


class DriveInput(Widget):
    """Input row for selecting a floppy drive/device/image path.

    Emits ``DriveInput.Changed`` when the value changes.

    Parameters
    ----------
    label : str
        Row label text (e.g. "Source", "Device").
    default : str
        Default input value. Use ``"auto"`` to use the platform default device.
    show_mounts : bool
        If True, browse also shows mounted floppy paths (for import).
        If False, browse only shows raw device paths (for diskcheck/format).
    autodetect_on_mount : bool
        If True, automatically detect drives when the widget mounts.
    """

    DEFAULT_CSS = """
    DriveInput {
        height: auto;
        width: 100%;
    }
    """

    class Changed(Message):
        """Posted when the drive path changes."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(
        self,
        label: str = "Device",
        default: str = "auto",
        show_mounts: bool = False,
        autodetect_on_mount: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._label = label
        self._default = default
        self._show_mounts = show_mounts
        self._autodetect_on_mount = autodetect_on_mount
        self._anim_timer = None
        self._anim_frame = 0

    def compose(self) -> ComposeResult:
        with Horizontal(classes="input-row"):
            # Pad label to 8 chars for alignment
            padded = self._label.rjust(6)
            yield Static(f"  [bold]{padded}[/] ", classes="row-label")
            default_val = ""
            if self._default and self._default != "auto":
                default_val = self._default
            elif self._default == "auto" and not self._autodetect_on_mount:
                default_val = _default_floppy_device()
            yield Input(
                value=default_val,
                placeholder="Device path",
                id="drive-path",
            )
            yield Button("Detect", id="btn-detect")
            yield Button("Browse", id="btn-browse-drive")
            yield Button("Open", id="btn-open-drive")

    def on_mount(self) -> None:
        if self._autodetect_on_mount:
            self._start_autodetect()

    @property
    def value(self) -> str:
        return self.query_one("#drive-path", Input).value.strip()

    @value.setter
    def value(self, val: str) -> None:
        self.query_one("#drive-path", Input).value = val

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "drive-path":
            self.post_message(self.Changed(event.value.strip()))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-detect":
            self._start_autodetect()
        elif event.button.id == "btn-browse-drive":
            self._start_browse()
        elif event.button.id == "btn-open-drive":
            self._open_path()

    # ── Autodetect ────────────────────────────────────────────────

    def _start_autodetect(self) -> None:
        inp = self.query_one("#drive-path", Input)
        inp.disabled = True
        self.query_one("#btn-detect", Button).disabled = True
        self.query_one("#btn-detect", Button).label = "..."
        self._anim_frame = 0
        self._anim_timer = self.set_interval(0.3, self._animate)
        self.run_worker(self._do_autodetect(), exclusive=False)

    def _animate(self) -> None:
        inp = self.query_one("#drive-path", Input)
        if not inp.disabled:
            return
        ch = _SPINNER[self._anim_frame % len(_SPINNER)]
        self._anim_frame += 1
        inp.placeholder = f"{ch} Detecting floppy drives..."

    async def _do_autodetect(self) -> None:
        from mavica_tools.detect import detect_floppy_drives, detect_floppy_mount_points

        mounts: list[str] = []
        drives = []
        try:
            drives = await asyncio.to_thread(detect_floppy_drives)
            if self._show_mounts:
                mounts = await asyncio.to_thread(detect_floppy_mount_points)
        except Exception:
            pass

        if self._anim_timer:
            self._anim_timer.stop()
            self._anim_timer = None

        inp = self.query_one("#drive-path", Input)
        inp.disabled = False
        inp.placeholder = "Device path"
        btn = self.query_one("#btn-detect", Button)
        btn.disabled = False
        btn.label = "Detect"

        # Pick best result: mount points first (for import), then raw devices
        if self._show_mounts and mounts:
            inp.value = mounts[0]
            count = len(mounts) + len(drives)
            if count == 1:
                self.app.notify(f"Found floppy: {mounts[0]}", severity="information")
            else:
                self.app.notify(
                    f"Found {count} drive(s), using {mounts[0]}", severity="information"
                )
        elif drives:
            inp.value = drives[0].device
            if len(drives) == 1:
                self.app.notify(f"Found drive: {drives[0].device}", severity="information")
            else:
                self.app.notify(
                    f"Found {len(drives)} drive(s), using {drives[0].device}",
                    severity="information",
                )

    # ── Browse ────────────────────────────────────────────────────

    def _start_browse(self) -> None:
        btn = self.query_one("#btn-browse-drive", Button)
        btn.disabled = True
        btn.label = "..."
        self.run_worker(self._do_browse(), exclusive=False)

    async def _do_browse(self) -> None:
        from mavica_tools.detect import detect_floppy_drives, detect_floppy_mount_points

        drives = []
        mounts: list[str] = []
        try:
            drives = await asyncio.to_thread(detect_floppy_drives)
            if self._show_mounts:
                mounts = await asyncio.to_thread(detect_floppy_mount_points)
        except Exception:
            pass

        btn = self.query_one("#btn-browse-drive", Button)
        btn.disabled = False
        btn.label = "Browse"

        self._show_picker(drives, mounts)

    def _show_picker(self, drives, mounts) -> None:
        from textual.containers import Horizontal as H
        from textual.containers import Vertical
        from textual.screen import ModalScreen
        from textual.widgets import OptionList
        from textual.widgets import Static as S
        from textual.widgets.option_list import Option

        class DrivePickerScreen(ModalScreen[str]):
            DEFAULT_CSS = """
            DrivePickerScreen {
                align: center middle;
            }
            #drive-dialog {
                width: 65;
                height: auto;
                max-height: 80%;
                border: thick #33ff33;
                background: #0a0a0a;
                padding: 1 2;
            }
            #drive-dialog OptionList {
                height: auto;
                max-height: 50%;
            }
            #drive-dialog Input {
                margin: 1 0 0 0;
            }
            #picker-buttons {
                height: auto;
                margin-top: 1;
                width: 100%;
            }
            """
            BINDINGS = [("escape", "cancel", "Cancel")]

            def compose(self_inner):
                with Vertical(id="drive-dialog"):
                    yield S("[bold #ffaa00]Select Drive[/]\n")
                    options = []
                    for mp in mounts:
                        info = _mount_info(mp)
                        options.append(
                            Option(
                                f"[bold]{mp}[/]  {info}",
                                id=mp,
                            )
                        )
                    for d in drives:
                        if d.device not in [o.id for o in options]:
                            size = _fmt_size(d.size_bytes) if d.size_bytes else ""
                            label = d.label or "Floppy drive"
                            detail = f"[dim]{label}[/]"
                            if size:
                                detail += f"  [dim]{size}[/]"
                            options.append(
                                Option(
                                    f"[bold]{d.device}[/]  {detail}",
                                    id=d.device,
                                )
                            )
                    if not options:
                        options.append(Option("[dim]No floppy drives detected[/]", disabled=True))
                    yield OptionList(*options, id="drive-list")
                    yield Input(placeholder="Or type a device path manually...", id="manual-path")
                    with H(id="picker-buttons"):
                        yield Button("Select", variant="success", id="btn-pick-select")
                        yield Button("Cancel", variant="default", id="btn-pick-cancel")

            def on_option_list_option_selected(self_inner, event):
                if event.option.id:
                    self_inner.dismiss(event.option.id)

            def on_input_submitted(self_inner, event):
                if event.input.id == "manual-path" and event.value.strip():
                    self_inner.dismiss(event.value.strip())

            def on_button_pressed(self_inner, event):
                if event.button.id == "btn-pick-select":
                    # Manual input takes priority
                    manual = self_inner.query_one("#manual-path", Input).value.strip()
                    if manual:
                        self_inner.dismiss(manual)
                        return
                    ol = self_inner.query_one("#drive-list", OptionList)
                    idx = ol.highlighted
                    if idx is not None:
                        try:
                            opt = ol.get_option_at_index(idx)
                            if opt.id:
                                self_inner.dismiss(opt.id)
                        except Exception:
                            pass
                elif event.button.id == "btn-pick-cancel":
                    self_inner.dismiss("")

            def action_cancel(self_inner):
                self_inner.dismiss("")

        def on_result(value: str) -> None:
            if value:
                self.query_one("#drive-path", Input).value = value

        self.app.push_screen(DrivePickerScreen(), on_result)

    # ── Open ──────────────────────────────────────────────────────

    def _open_path(self) -> None:
        """Open the current path in the system file manager."""
        import os

        from mavica_tools.utils import open_directory

        path = self.value
        if not path:
            return
        d = path if os.path.isdir(path) else os.path.dirname(path)
        d = os.path.abspath(d) if d else ""
        if d and os.path.isdir(d):
            open_directory(d)
