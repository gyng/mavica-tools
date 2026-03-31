"""Defrag-style sector visualization widget.

Inspired by the Windows 95/98 Disk Defragmenter. Shows a grid of
colored blocks representing disk sectors, updated in real-time
during reads.

Sector states:
  waiting   — not yet read (dark gray)
  reading   — currently being read (white/bright)
  good      — read successfully (green)
  recovered — failed before, succeeded this pass (cyan)
  bad       — read failed (red)
  conflict  — different data across passes (magenta)
"""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text

TOTAL_SECTORS = 2880
DEFAULT_COLS = 60

# Block characters and colors for each state
STATE_STYLE = {
    "waiting":   ("░", "#333333"),
    "reading":   ("▓", "#ffffff"),
    "good":      ("▓", "#33ff33"),
    "recovered": ("▓", "#33aaff"),
    "bad":       ("▓", "#ff3333"),
    "conflict":  ("▓", "#ff33ff"),
    "blank":     ("▓", "#ff3333"),   # alias for bad
}


class DefragMap(Widget):
    """Windows 95-style defrag sector grid.

    Set `sectors` to a list of 2880 state strings to update.
    For live updates during reads, call `update_sector(index, state)`.
    """

    DEFAULT_CSS = """
    DefragMap {
        height: auto;
        min-height: 8;
        max-height: 28;
        padding: 0 1;
        border: tall #333333;
        background: #0a0a0a;
    }
    """

    sectors: reactive[list] = reactive(list, layout=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._cells = ["waiting"] * TOTAL_SECTORS
        self._current_sector = -1
        self._pass_num = 0

    def reset(self, pass_num: int = 0) -> None:
        """Reset all sectors to waiting state for a new pass."""
        self._cells = ["waiting"] * TOTAL_SECTORS
        self._current_sector = -1
        self._pass_num = pass_num
        self.refresh()

    def update_sector(self, index: int, state: str) -> None:
        """Update a single sector's state."""
        if 0 <= index < TOTAL_SECTORS:
            # Clear previous "reading" indicator
            if self._current_sector >= 0 and self._cells[self._current_sector] == "reading":
                self._cells[self._current_sector] = "waiting"

            self._cells[index] = state
            if state == "reading":
                self._current_sector = index
            self.refresh()

    def update_range(self, start: int, end: int, state: str) -> None:
        """Update a range of sectors at once (batch update)."""
        for i in range(max(0, start), min(end, TOTAL_SECTORS)):
            self._cells[i] = state
        self.refresh()

    def set_merged_result(self, sector_status: list[str]) -> None:
        """Set the final merged result (replaces all cells)."""
        for i, s in enumerate(sector_status):
            if i < TOTAL_SECTORS:
                self._cells[i] = s
        self._current_sector = -1
        self.refresh()

    def watch_sectors(self, new_sectors: list) -> None:
        """React to the sectors reactive changing."""
        if new_sectors:
            self.set_merged_result(new_sectors)

    def render(self) -> Text:
        text = Text()

        # Dynamic columns based on widget width
        cols = max(20, self.size.width - 4) if self.size.width > 10 else DEFAULT_COLS
        rows = (TOTAL_SECTORS + cols - 1) // cols

        # Header
        if self._pass_num > 0:
            text.append(f"  Pass {self._pass_num}  ", style="bold")
        text.append(
            "░ waiting  ", style="#333333"
        )
        text.append("▓ reading  ", style="#ffffff")
        text.append("▓ good  ", style="#33ff33")
        text.append("▓ recovered  ", style="#33aaff")
        text.append("▓ bad\n\n", style="#ff3333")

        # Grid
        for row in range(rows):
            text.append("  ")
            for col in range(cols):
                idx = row * cols + col
                if idx >= TOTAL_SECTORS:
                    text.append(" ")
                    continue

                state = self._cells[idx] if idx < len(self._cells) else "waiting"
                char, color = STATE_STYLE.get(state, ("?", "#666666"))
                text.append(char, style=color)
            text.append("\n")

        # Read head indicator (during live reads)
        if self._current_sector >= 0:
            from mavica_tools.fun import read_head_indicator_rich
            text.append(read_head_indicator_rich(self._current_sector))
            text.append("\n")

        # Stats
        good = self._cells.count("good")
        recovered = self._cells.count("recovered")
        bad = self._cells.count("bad") + self._cells.count("blank")
        waiting = self._cells.count("waiting")
        reading = self._cells.count("reading")
        done = TOTAL_SECTORS - waiting - reading

        if done > 0:
            pct = 100 * done / TOTAL_SECTORS
            text.append(
                f"\n  {done}/{TOTAL_SECTORS} sectors ({pct:.0f}%)  "
                f"[{good} good, {recovered} recovered, {bad} bad]",
                style="dim"
            )

        return text
