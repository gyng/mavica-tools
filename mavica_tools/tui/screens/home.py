"""Home screen — categorized main menu."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Static, Header, Footer, OptionList
from textual.widgets.option_list import Option


# Tools organized by user journey stage
TOOLS = [
    # Quick start
    ("w", "workflow", "Guided Recovery", "Start here — walks you through every step"),
    ("7", "recover", "One-Click Recover", "Full pipeline in one command"),
    # Recovery steps
    ("1", "multipass", "Read Floppy", "Multi-pass imager — merge best sectors"),
    ("6", "fat12", "Extract with Names", "Recover files with original Mavica names"),
    ("2", "carve", "Carve from Raw", "Extract JPEGs from damaged/raw disk images"),
    ("3", "check", "Check for Damage", "Scan JPEGs for corruption"),
    ("4", "repair", "Repair Images", "Salvage pixels from corrupt files"),
    # Post-processing
    ("9", "stamp", "Add Photo Info", "Add camera model, date, and lens data to EXIF"),
    ("g", "gps", "Add GPS Location", "Match photos to GPS tracks from a logger"),
    ("e", "export", "Export & Share", "Organize, contact sheets, watermarks, resize"),
    # Diagnostic & utility
    ("t", "troubleshoot", "Troubleshoot", "Interactive wizard — what's wrong with my floppy?"),
    ("5", "swaptest", "Camera Swap Test", "Find the faulty camera, disk, or drive"),
    ("8", "format", "Format Floppy", "Create Mavica-compatible FAT12 format"),
]


class HomeScreen(Screen):
    """Landing screen with categorized tool selection."""

    BINDINGS = [
        Binding("1", "tool('multipass')", "Read", show=False),
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
        Binding("t", "tool('troubleshoot')", "Troubleshoot", show=False),
        Binding("w", "tool('workflow')", "Workflow", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #33ff33]mavica-tools[/] — Floppy Recovery Toolkit for Sony Mavica\n",
            id="title-bar",
        )

        options = []

        # Section headers as styled options
        options.append(Option("[bold #33ff33]--- Start Here ---[/]", disabled=True))
        for item in TOOLS[:2]:
            options.append(self._make_option(item))

        options.append(Option("[bold #33ff33]--- Recovery Steps ---[/]", disabled=True))
        for item in TOOLS[2:7]:
            options.append(self._make_option(item))

        options.append(Option("[bold #33ff33]--- Post-Processing ---[/]", disabled=True))
        for item in TOOLS[7:10]:
            options.append(self._make_option(item))

        options.append(Option("[bold #33ff33]--- Diagnostic & Utility ---[/]", disabled=True))
        for item in TOOLS[10:]:
            options.append(self._make_option(item))

        yield OptionList(*options, id="tool-list")
        yield Static(
            "\n  [dim]Windows / macOS / Linux  |  ? for help  |  q to quit[/]",
        )
        yield Footer()

    def _make_option(self, item):
        key, screen_id, name, desc = item
        return Option(
            f"[bold #ffaa00][{key}][/]  [bold]{name}[/]\n"
            f"     [dim]{desc}[/]",
            id=screen_id,
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        screen_id = event.option.id
        if screen_id:
            self.app.push_screen(screen_id)

    def action_tool(self, screen_id: str) -> None:
        self.app.push_screen(screen_id)
