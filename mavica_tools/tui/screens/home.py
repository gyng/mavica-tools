"""Home screen — main menu."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Static, Header, Footer, OptionList
from textual.widgets.option_list import Option


TOOLS = [
    ("1", "multipass", "Multipass Read", "Multi-pass floppy imager — merge best sectors"),
    ("2", "carve", "Carve JPEGs", "Extract images from raw disk images"),
    ("3", "check", "Check Files", "Batch JPEG corruption checker"),
    ("4", "repair", "Repair Images", "Salvage pixels from corrupt JPEGs"),
    ("5", "swaptest", "Swap Test", "Cross-camera test tracker"),
    ("w", "workflow", "Guided Workflow", "Step-by-step recovery (recommended)"),
]


class HomeScreen(Screen):
    """Landing screen with tool selection."""

    BINDINGS = [
        Binding("1", "tool('multipass')", "Multipass", show=False),
        Binding("2", "tool('carve')", "Carve", show=False),
        Binding("3", "tool('check')", "Check", show=False),
        Binding("4", "tool('repair')", "Repair", show=False),
        Binding("5", "tool('swaptest')", "Swap Test", show=False),
        Binding("w", "tool('workflow')", "Workflow", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #33ff33]mavica-tools[/] — Floppy Recovery Toolkit\n",
            id="title-bar",
        )
        yield Static(
            "  Select a tool or press [bold #ffaa00]w[/] for the guided workflow:\n",
        )
        yield OptionList(
            *[
                Option(
                    f"[bold #ffaa00][{key}][/]  [bold]{name}[/]\n"
                    f"     [dim]{desc}[/]",
                    id=screen_id,
                )
                for key, screen_id, name, desc in TOOLS
            ],
            id="tool-list",
        )
        yield Static(
            "\n  [dim]Supports Windows, macOS, and Linux.[/]\n"
            "  [dim]Floppy device reads require platform-appropriate drivers.[/]",
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        screen_id = event.option.id
        if screen_id:
            self.app.push_screen(screen_id)

    def action_tool(self, screen_id: str) -> None:
        self.app.push_screen(screen_id)
