"""Visual sector health map widget."""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text

SECTORS_PER_TRACK = 18
HEADS = 2

STATUS_STYLES = {
    "good": (".", "green"),
    "recovered": ("r", "#33aaff"),
    "blank": ("X", "red"),
    "conflict": ("!", "magenta"),
}


class SectorMap(Widget):
    """Renders a visual grid of sector health status."""

    DEFAULT_CSS = """
    SectorMap {
        height: auto;
        max-height: 24;
        overflow-y: auto;
        padding: 0 1;
    }
    """

    sector_status: reactive[list] = reactive(list, layout=True)

    def render(self) -> Text:
        if not self.sector_status:
            return Text("No sector data", style="dim")

        text = Text()
        text.append("  . good  ", style="green")
        text.append("r recovered  ", style="#33aaff")
        text.append("X blank  ", style="red")
        text.append("! conflict\n\n", style="magenta")

        for i in range(0, len(self.sector_status), SECTORS_PER_TRACK):
            track = i // (SECTORS_PER_TRACK * HEADS)
            head = (i // SECTORS_PER_TRACK) % HEADS
            chunk = self.sector_status[i : i + SECTORS_PER_TRACK]

            text.append(f"  T{track:02d}H{head} [", style="dim")
            for s in chunk:
                char, color = STATUS_STYLES.get(s, ("?", "white"))
                text.append(char, style=color)
            text.append("]\n", style="dim")

        return text
