"""Main Textual application for mavica-tools."""

from textual.app import App, ComposeResult
from textual.binding import Binding

from mavica_tools.tui.screens.home import HomeScreen
from mavica_tools.tui.screens.import_workflow import ImportWorkflowScreen
from mavica_tools.tui.screens.recovery_workflow import RecoveryWorkflowScreen
from mavica_tools.tui.screens.check import CheckScreen
from mavica_tools.tui.screens.carve import CarveScreen
from mavica_tools.tui.screens.repair import RepairScreen
from mavica_tools.tui.screens.multipass import MultipassScreen
from mavica_tools.tui.screens.swaptest import SwapTestScreen
from mavica_tools.tui.screens.fat12_screen import Fat12Screen
from mavica_tools.tui.screens.recover_screen import RecoverScreen
from mavica_tools.tui.screens.stamp_screen import StampScreen
from mavica_tools.tui.screens.format_screen import FormatScreen
from mavica_tools.tui.screens.export_screen import ExportScreen
from mavica_tools.tui.screens.gps_screen import GpsScreen
from mavica_tools.tui.screens.troubleshoot import TroubleshootScreen


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
    max-height: 40%;
}

OptionList {
    height: auto;
    max-height: 70%;
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
    border: tall #333333;
}

Input:focus {
    border: tall #33ff33;
}

.input-row {
    height: 3;
    margin: 0 0 1 0;
    width: 100%;
}

.input-row Input {
    width: 1fr;
}

.button-row {
    height: 3;
    margin: 0 0 1 0;
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
    margin: 1 0;
    height: auto;
    max-height: 12;
    border: tall #333333;
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

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True, priority=True),
        Binding("h", "go_home", "Home", show=True),
        Binding("question_mark", "help", "Help", show=True),
    ]

    SCREENS = {
        "home": HomeScreen,
        "import_workflow": ImportWorkflowScreen,
        "recovery_workflow": RecoveryWorkflowScreen,
        "check": CheckScreen,
        "carve": CarveScreen,
        "repair": RepairScreen,
        "multipass": MultipassScreen,
        "swaptest": SwapTestScreen,
        "fat12": Fat12Screen,
        "recover": RecoverScreen,
        "stamp": StampScreen,
        "format": FormatScreen,
        "export": ExportScreen,
        "gps": GpsScreen,
        "troubleshoot": TroubleshootScreen,
    }

    def on_mount(self) -> None:
        self.push_screen("home")

    def action_go_home(self) -> None:
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen("home")

    def action_help(self) -> None:
        self.notify(
            "1-9: Tools  w: Workflow  h: Home  q: Quit\n"
            "Tab/Shift+Tab: Navigate  Enter: Select  Esc: Back\n"
            "b: Browse for file/directory",
            title="Keyboard Shortcuts",
            timeout=5,
        )


def run():
    """Entry point for the TUI."""
    app = MavicaApp()
    app.run()
