"""Main Textual application for mavica-tools."""

import contextlib
import os
from typing import ClassVar

from textual.app import App
from textual.binding import Binding

from mavica_tools.tui.screens.diskcheck_screen import DiskCheckScreen
from mavica_tools.tui.screens.format_screen import FormatScreen
from mavica_tools.tui.screens.gps_screen import GpsScreen
from mavica_tools.tui.screens.home import HomeScreen
from mavica_tools.tui.screens.import_workflow import ImportWorkflowScreen
from mavica_tools.tui.screens.multipass import MultipassScreen
from mavica_tools.tui.screens.recover_image_screen import RecoverImageScreen
from mavica_tools.tui.screens.repair import RepairScreen
from mavica_tools.tui.screens.stamp_screen import StampScreen
from mavica_tools.tui.screens.thumb411_screen import Thumb411Screen

CSS = """
Screen {
    background: #0a0a0a;
}

#title-bar {
    dock: top;
    height: 1;
    background: #1a1a1a;
    color: #33ff33;
    text-style: bold;
    padding: 0 1;
    margin-bottom: 1;
}

.section-title {
    color: #ffaa00;
    text-style: bold;
    margin: 1 0 0 0;
}

.status-good {
    color: #33ff33;
}

.status-warn {
    color: #ffaa00;
}

.status-bad {
    color: #ff3333;
}

.status-recovered {
    color: #33aaff;
}

.status-conflict {
    color: #ff33ff;
}

.dim {
    color: #666666;
}

Button {
    margin: 0 1;
    min-width: 10;
    height: 1;
    min-height: 1;
    border: none;
    padding: 0 1;
}

Button.-active {
    background: #2a5a2a;
}

Button:disabled {
    opacity: 0.4;
}

DataTable {
    margin: 1 0;
    height: auto;
}


DataTable > .datatable--header {
    background: #1a1a1a;
    color: #ffaa00;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #1a3a1a;
    color: #33ff33;
}

Input {
    margin: 0 1 0 0;
    height: 1;
    border: none;
    padding: 0 0;
    background: #1a1a1a;
}

Input:focus {
    background: #0a2a0a;
}

ProgressBar {
    height: 1;
    padding: 0;
}

.input-row {
    height: 1;
    margin: 0 1 1 1;
    width: 100%;
}

.input-row Input {
    width: 1fr;
}

.row-label {
    width: auto;
    height: 1;
    min-width: 6;
}

.button-row {
    height: auto;
    max-height: 3;
    margin: 0 1 1 1;
    width: 100%;
}

.results-summary {
    margin: 1 0;
    padding: 1;
    background: #111111;
    border: tall #333333;
}

ProgressBar {
    margin: 0 1;
    padding: 0;
}

ProgressBar > .bar--bar {
    color: #33ff33;
}

ProgressBar > .bar--complete {
    color: #33ff33;
}

RichLog {
    margin: 0;
    height: auto;
    max-height: 8;
    border: none;
    background: #0a0a0a;
}

#sector-map {
    margin: 1 0;
    height: auto;
    max-height: 20;
    overflow-y: auto;
}

.preview-pane {
    width: 1fr;
    height: auto;
    min-height: 8;
}
"""


class MavicaApp(App):
    """Mavica floppy disk recovery TUI."""

    TITLE = "mavica-tools"
    SUB_TITLE = "Floppy Recovery Toolkit"
    CSS = CSS

    BINDINGS: ClassVar[list] = [
        Binding("q", "request_quit", "Quit", show=True, priority=True),
        Binding("h", "go_home", "Home", show=True),
        Binding("question_mark", "help", "Help", show=True),
    ]

    SCREENS: ClassVar[dict] = {
        "home": HomeScreen,
        "import_workflow": ImportWorkflowScreen,
        "recover_image": RecoverImageScreen,
        "repair": RepairScreen,
        "multipass": MultipassScreen,
        "stamp": StampScreen,
        "format": FormatScreen,
        "gps": GpsScreen,
        "diskcheck": DiskCheckScreen,
        "thumb411": Thumb411Screen,
    }

    def get_system_commands(self, screen):
        from textual.app import SystemCommand

        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Screenshot to clipboard",
            "Copy SVG screenshot to clipboard",
            self._screenshot_to_clipboard,
        )

    def on_mount(self) -> None:
        self.push_screen("home")

    def action_go_home(self) -> None:
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen("home")

    def action_request_quit(self) -> None:
        """Ask for confirmation before quitting. Skip dialog on home screen."""
        # No confirmation needed if we're just on the home screen
        if len(self.screen_stack) <= 2:  # default + home
            has_workers = any(
                w for screen in self.screen_stack for w in screen.workers if w.is_running
            )
            if not has_workers:
                self.exit()
                return

        from textual.containers import Horizontal
        from textual.screen import ModalScreen
        from textual.widgets import Button, Static

        class QuitConfirm(ModalScreen[bool]):
            DEFAULT_CSS = """
            QuitConfirm {
                align: center middle;
            }
            #quit-dialog {
                width: 40;
                height: auto;
                max-height: 12;
                border: thick #ffaa00;
                background: #1a1a1a;
                padding: 1 2;
            }
            #quit-dialog Static {
                width: 100%;
                height: auto;
                content-align: center middle;
                margin-bottom: 1;
            }
            #quit-dialog Horizontal {
                width: 100%;
                height: auto;
                align: center middle;
            }
            #quit-dialog Button {
                margin: 0 1;
                min-width: 12;
            }
            """
            BINDINGS: ClassVar[list] = [
                Binding("y", "confirm", show=False),
                Binding("n", "cancel", show=False),
                Binding("q", "confirm", show=False),
                Binding("escape", "cancel", show=False),
            ]

            def compose(self):
                from textual.containers import Vertical

                with Vertical(id="quit-dialog"):
                    yield Static("Quit mavica-tools?")
                    with Horizontal():
                        yield Button("Yes (y)", variant="error", id="btn-yes")
                        yield Button("No (n)", variant="primary", id="btn-no")

            def on_button_pressed(self, event):
                if event.button.id == "btn-yes":
                    self.dismiss(True)
                else:
                    self.dismiss(False)

            def action_confirm(self):
                self.dismiss(True)

            def action_cancel(self):
                self.dismiss(False)

        def on_result(confirmed: bool) -> None:
            if confirmed:
                # Cancel all workers
                for screen in self.screen_stack:
                    for worker in screen.workers:
                        worker.cancel()
                for worker in self.workers:
                    worker.cancel()
                # Graceful exit — lets Textual restore the terminal.
                # Force-kill after 1s if a worker thread is stuck on I/O.
                import threading

                def _force_exit():
                    import os

                    os._exit(0)

                threading.Timer(1.0, _force_exit).daemon = True
                t = threading.Timer(1.0, _force_exit)
                t.daemon = True
                t.start()
                self.exit()

        self.push_screen(QuitConfirm(), on_result)

    @staticmethod
    def _get_screenshots_dir() -> str:
        """Get the OS default screenshots directory."""
        import platform

        system = platform.system()
        home = os.path.expanduser("~")
        if system == "Windows":
            # Windows: Pictures/Screenshots
            pictures = os.path.join(home, "Pictures", "Screenshots")
            if not os.path.isdir(pictures):
                # Fallback to Pictures
                pictures = os.path.join(home, "Pictures")
            if not os.path.isdir(pictures):
                pictures = home
            return pictures
        elif system == "Darwin":
            # macOS: Desktop (default screenshot location)
            return os.path.join(home, "Desktop")
        else:
            # Linux: Pictures or home
            pictures = os.path.join(home, "Pictures")
            return pictures if os.path.isdir(pictures) else home

    def _screenshot_to_file(self) -> None:
        import time

        screenshots_dir = self._get_screenshots_dir()
        os.makedirs(screenshots_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"mavica_{timestamp}.svg"
        path = self.save_screenshot(filename, path=screenshots_dir)
        if path and os.path.exists(str(path)):
            self.notify(f"Saved: {path}", timeout=3)
        else:
            self.notify(f"Saved: {os.path.join(screenshots_dir, filename)}", timeout=3)

    def _screenshot_to_clipboard(self) -> None:
        import os
        import subprocess
        import tempfile

        # Save to temp file first
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            tmp_path = f.name
        try:
            self.save_screenshot(os.path.basename(tmp_path), path=os.path.dirname(tmp_path))
            with open(tmp_path, "rb") as f:
                svg_bytes = f.read()

            # Try platform-specific clipboard — pass raw bytes to avoid
            # encoding errors (SVG contains Unicode that cp1252 can't handle)
            import platform

            system = platform.system()
            if system == "Windows":
                proc = subprocess.run(
                    ["clip.exe"],
                    input=svg_bytes,
                    capture_output=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    self.notify("SVG copied to clipboard", timeout=3)
                    return
            elif system == "Darwin":
                proc = subprocess.run(
                    ["pbcopy"],
                    input=svg_bytes,
                    capture_output=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    self.notify("SVG copied to clipboard", timeout=3)
                    return
            else:
                for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard"]):
                    try:
                        proc = subprocess.run(
                            cmd,
                            input=svg_bytes,
                            capture_output=True,
                            timeout=5,
                        )
                        if proc.returncode == 0:
                            self.notify("SVG copied to clipboard", timeout=3)
                            return
                    except FileNotFoundError:
                        continue

            # Fallback: save to file instead
            self.notify(
                "Clipboard unavailable, saving to file instead", severity="warning", timeout=3
            )
            self._screenshot_to_file()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    def action_help(self) -> None:
        self.notify(
            "1-9: Tools  w: Workflow  h: Home  q: Quit\n"
            "Tab/Shift+Tab: Navigate  Enter: Select  Esc: Back\n"
            "b: Browse  ^p: Command Palette",
            title="Keyboard Shortcuts",
            timeout=5,
        )


def run():
    """Entry point for the TUI."""
    app = MavicaApp()
    app.run()
