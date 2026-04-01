"""Home screen — organized by user workflow priority."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

# Organized by frequency of use and workflow order.
# Primary: the main import→tag→GPS pipeline (what most users do every time)
# Recovery: for when things go wrong (less frequent but critical)
# Disk: hardware-level tools (least frequent)
SECTIONS = [
    {
        "header": "Photos",
        "tools": [
            ("1", "import_workflow", "Import Floppy", "Copy photos off a floppy disk"),
            ("2", "stamp", "Tag Photos", "Add camera model, date, and EXIF tags"),
            ("3", "gps", "Add GPS Location", "Match photos to a GPX track file"),
            ("4", "thumb411", ".411 Thumbnails", "View and convert Mavica camera thumbnails"),
        ],
    },
    {
        "header": "Disk",
        "tools": [
            ("5", "diskcheck", "Test Disk", "Check if a floppy is safe before using it"),
            ("6", "format", "Format Disk", "Prepare a floppy for Mavica use"),
        ],
    },
    {
        "header": "Recovery",
        "tools": [
            ("7", "multipass", "Image Disk", "Read a damaged floppy multiple times, keep best data"),
            ("8", "recover_image", "Recover Image", "Extract photos from a disk image (FAT12 + carve)"),
            ("9", "repair", "Check & Repair", "Scan photos for damage, then fix what's broken"),
            (None, "flux", "Flux Recovery", "Greaseweazle/KryoFlux raw flux capture"),
        ],
    },
]

# Collect all shortcut keys for bindings
_ALL_TOOLS = [(t[0], t[1]) for s in SECTIONS for t in s["tools"] if t[0] is not None]


class HomeScreen(Screen):
    """Landing screen — organized by workflow priority."""

    DEFAULT_CSS = """
    HomeScreen {
        overflow: hidden;
    }
    HomeScreen #tool-list {
        height: 1fr;
    }
    """

    BINDINGS = [Binding(key, f"tool('{screen_id}')", show=False) for key, screen_id in _ALL_TOOLS]

    _NAME_WIDTH = 20

    def compose(self) -> ComposeResult:
        from mavica_tools.fun import random_trivia

        yield Header()
        yield Static(
            f"[bold #33ff33]mavica-tools[/] — Sony Mavica Floppy Toolkit"
            f"    [dim italic]{random_trivia()}[/]\n",
            id="title-bar",
        )

        options = []
        for section in SECTIONS:
            options.append(
                Option(
                    f"[bold #33ff33]  {section['header']}[/]",
                    disabled=True,
                )
            )
            for tool in section["tools"]:
                key, screen_id, name, desc = tool
                padded = name.ljust(self._NAME_WIDTH)
                if key is None:
                    options.append(
                        Option(
                            f"  [dim]·  {padded}  {desc}  (not implemented)[/]",
                            disabled=True,
                        )
                    )
                else:
                    options.append(
                        Option(
                            f"  [bold #ffaa00]{key}[/]  [bold]{padded}[/]  [dim]{desc}[/]",
                            id=screen_id,
                        )
                    )

        yield OptionList(*options, id="tool-list")
        yield Static(
            "  [dim]? help  |  q quit[/]",
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self._open_screen(event.option.id)

    def action_tool(self, screen_id: str) -> None:
        self._open_screen(screen_id)

    def _open_screen(self, screen_id: str) -> None:
        if screen_id in self.app.SCREENS:
            self.app.push_screen(screen_id)
        else:
            self.app.notify(f"{screen_id}: not yet implemented", severity="warning")
