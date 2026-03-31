"""Main Textual application for mavica-tools."""

from textual.app import App, ComposeResult
from textual.binding import Binding

from mavica_tools.tui.screens.home import HomeScreen
from mavica_tools.tui.screens.check import CheckScreen
from mavica_tools.tui.screens.carve import CarveScreen
from mavica_tools.tui.screens.repair import RepairScreen
from mavica_tools.tui.screens.multipass import MultipassScreen
from mavica_tools.tui.screens.swaptest import SwapTestScreen
from mavica_tools.tui.screens.workflow import WorkflowScreen


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
}

Button.primary {
    background: #1a3a1a;
    color: #33ff33;
    border: tall #33ff33;
}

Button.primary:hover {
    background: #2a5a2a;
}

Button.warning {
    background: #3a3a1a;
    color: #ffaa00;
    border: tall #ffaa00;
}

DataTable {
    margin: 1 0;
    height: auto;
    max-height: 20;
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

#footer-bar {
    dock: bottom;
    height: 1;
    background: #1a1a1a;
    color: #666666;
    padding: 0 1;
}

.results-summary {
    margin: 1 0;
    padding: 1;
    background: #111111;
    border: tall #333333;
}

RichLog {
    margin: 1 0;
    height: auto;
    max-height: 8;
    border: tall #333333;
    background: #0a0a0a;
}

#sector-map {
    margin: 1 0;
    height: auto;
    max-height: 20;
    overflow-y: auto;
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
        "check": CheckScreen,
        "carve": CarveScreen,
        "repair": RepairScreen,
        "multipass": MultipassScreen,
        "swaptest": SwapTestScreen,
        "workflow": WorkflowScreen,
    }

    def on_mount(self) -> None:
        self.push_screen("home")

    def action_go_home(self) -> None:
        # Pop all screens back to the base, then push home
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen("home")

    def action_help(self) -> None:
        self.notify(
            "1-5: Tools  w: Workflow  h: Home  q: Quit\n"
            "Tab/Shift+Tab: Navigate  Enter: Select",
            title="Keyboard Shortcuts",
            timeout=5,
        )


def run():
    """Entry point for the TUI."""
    app = MavicaApp()
    app.run()
