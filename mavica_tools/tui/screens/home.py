"""Home screen — organized around 3 major use cases."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Static, Header, Footer, OptionList
from textual.widgets.option_list import Option


# Three use cases with their tools
USE_CASES = [
    # Use case 1: Regular use — get photos off floppy, tag, export
    {
        "header": "Import & Tag Photos",
        "desc": "Get photos off your Mavica floppy, add metadata, and export",
        "tools": [
            ("1", "import_workflow", "Import from Floppy", "Read floppy > tag > organize > export"),
            ("f", "fat12", "Browse Floppy Files", "View and extract files with original Mavica names"),
            ("s", "stamp", "Add Photo Info", "Add camera model, date, lens data to EXIF"),
            ("g", "gps", "Add GPS Location", "Match photos to a GPS track file"),
            ("e", "export", "Export & Share", "Organize, contact sheets, watermarks, resize"),
        ],
    },
    # Use case 2: Recovery — damaged disk, corrupt photos
    {
        "header": "Repair & Recovery",
        "desc": "Recover photos from damaged or unreadable floppies",
        "tools": [
            ("r", "recovery_workflow", "Guided Recovery", "Step by step: image > extract > check > repair"),
            ("m", "multipass", "Multi-Pass Read", "Read floppy multiple times, merge best sectors"),
            ("c", "carve", "Carve from Raw", "Extract JPEGs directly from raw disk data"),
            ("k", "check", "Check for Damage", "Scan JPEGs for corruption"),
            ("p", "repair", "Repair Images", "Salvage pixels from corrupt files"),
        ],
    },
    # Use case 3: Debugging — which hardware is broken?
    {
        "header": "Diagnose Problems",
        "desc": "Figure out if the problem is the camera, disk, or drive",
        "tools": [
            ("t", "troubleshoot", "Troubleshooting Wizard", "Guided Q&A to find the problem"),
            ("w", "swaptest", "Camera Swap Test", "Test camera+disk combos to isolate the fault"),
            ("d", "detect", "Detect Floppy Drives", "Auto-detect available floppy drives"),
            ("h", "history", "Disk Health History", "Track sector health over time"),
        ],
    },
]

# Utility tools (less prominent)
UTILITY_TOOLS = [
    ("8", "format", "Format Floppy", "Create Mavica-compatible FAT12 format"),
    ("9", "report", "Recovery Report", "Generate HTML summary with thumbnails"),
    ("7", "recover", "One-Click Recover", "Full pipeline in one command"),
]


class HomeScreen(Screen):
    """Landing screen organized by use case."""

    BINDINGS = [
        # Import & Tag
        Binding("1", "tool('import_workflow')", show=False),
        Binding("f", "tool('fat12')", show=False),
        Binding("s", "tool('stamp')", show=False),
        Binding("g", "tool('gps')", show=False),
        Binding("e", "tool('export')", show=False),
        # Recovery
        Binding("r", "tool('recovery_workflow')", show=False),
        Binding("m", "tool('multipass')", show=False),
        Binding("c", "tool('carve')", show=False),
        Binding("k", "tool('check')", show=False),
        Binding("p", "tool('repair')", show=False),
        # Diagnostic
        Binding("t", "tool('troubleshoot')", show=False),
        Binding("w", "tool('swaptest')", show=False),
        Binding("d", "tool('detect')", show=False),
        # Utility
        Binding("7", "tool('recover')", show=False),
        Binding("8", "tool('format')", show=False),
        Binding("9", "tool('report')", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #33ff33]mavica-tools[/] — Sony Mavica Floppy Toolkit\n",
            id="title-bar",
        )
        yield Static("  [dim]What do you want to do?[/]\n")

        options = []

        for uc in USE_CASES:
            options.append(Option(
                f"[bold #33ff33]--- {uc['header']} ---[/]\n"
                f"     [dim]{uc['desc']}[/]",
                disabled=True,
            ))
            for tool in uc["tools"]:
                options.append(self._make_option(tool))

        options.append(Option("[bold #33ff33]--- Other Tools ---[/]", disabled=True))
        for tool in UTILITY_TOOLS:
            options.append(self._make_option(tool))

        yield OptionList(*options, id="tool-list")
        yield Static(
            "\n  [dim]? help  |  q quit  |  Windows / macOS / Linux[/]",
        )
        yield Footer()

    # Longest tool name across all sections (for alignment)
    _NAME_WIDTH = 22

    def _make_option(self, item):
        key, screen_id, name, desc = item
        padded = name.ljust(self._NAME_WIDTH)
        return Option(
            f"[bold #ffaa00][{key}][/]  [bold]{padded}[/]  [dim]{desc}[/]",
            id=screen_id,
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        screen_id = event.option.id
        if screen_id:
            self.app.push_screen(screen_id)

    def action_tool(self, screen_id: str) -> None:
        self.app.push_screen(screen_id)
