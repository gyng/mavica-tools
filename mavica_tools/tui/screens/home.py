"""Home screen — main menu."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Static, Header, Footer, OptionList
from textual.widgets.option_list import Option


TOOLS = [
    ("w", "workflow", "Guided Workflow", "Step-by-step recovery (start here)"),
    ("1", "multipass", "Multipass Read", "Multi-pass floppy imager"),
    ("2", "carve", "Carve JPEGs", "Extract images from raw disk images"),
    ("3", "check", "Check Files", "Batch JPEG corruption checker"),
    ("4", "repair", "Repair Images", "Salvage pixels from corrupt JPEGs"),
    ("5", "swaptest", "Swap Test", "Cross-camera test tracker"),
    ("6", "fat12", "FAT12 Browser", "View/extract files with original names"),
    ("7", "recover", "Batch Recover", "Full pipeline in one step"),
    ("8", "format", "Format Disk", "Create Mavica-compatible FAT12 format"),
    ("9", "stamp", "Stamp Metadata", "Add EXIF to recovered JPEGs"),
    ("e", "export", "Photo Export", "Organize, contact sheets, watermarks"),
    ("g", "gps", "GPS Merge", "Match photos to GPS tracks"),
]


class HomeScreen(Screen):
    """Landing screen with tool selection."""

    BINDINGS = [
        Binding("1", "tool('multipass')", "Multipass", show=False),
        Binding("2", "tool('carve')", "Carve", show=False),
        Binding("3", "tool('check')", "Check", show=False),
        Binding("4", "tool('repair')", "Repair", show=False),
        Binding("5", "tool('swaptest')", "Swap Test", show=False),
        Binding("6", "tool('fat12')", "FAT12", show=False),
        Binding("7", "tool('recover')", "Recover", show=False),
        Binding("8", "tool('format')", "Format", show=False),
        Binding("9", "tool('stamp')", "Stamp", show=False),
        Binding("e", "tool('export')", "Export", show=False),
        Binding("g", "tool('gps')", "GPS", show=False),
        Binding("w", "tool('workflow')", "Workflow", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #33ff33]mavica-tools[/] — Floppy Recovery Toolkit for Sony Mavica\n",
            id="title-bar",
        )
        yield Static(
            "  Press [bold #ffaa00]w[/] for guided recovery, "
            "or select a tool:\n",
        )

        options = []
        for item in TOOLS:
            key, screen_id, name, desc = item
            options.append(Option(
                f"[bold #ffaa00][{key}][/]  [bold]{name}[/]\n"
                f"     [dim]{desc}[/]",
                id=screen_id,
            ))

        yield OptionList(*options, id="tool-list")
        yield Static(
            "\n  [dim]Windows / macOS / Linux  |  ? for help  |  q to quit[/]",
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        screen_id = event.option.id
        if screen_id:
            self.app.push_screen(screen_id)

    def action_tool(self, screen_id: str) -> None:
        self.app.push_screen(screen_id)
