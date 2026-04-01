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

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

TOTAL_SECTORS = 2880
DEFAULT_COLS = 60

# Block characters and colors for each state
STATE_STYLE = {
    "waiting": ("░", "#333333"),
    "reading": ("▓", "#ffffff"),
    "good": ("▓", "#33ff33"),
    "recovered": ("▓", "#33aaff"),
    "bad": ("▓", "#ff3333"),
    "marked": ("▓", "#ff8800"),  # marked bad in FAT but readable
    "marked_bad": ("▓", "#ff3333"),  # marked bad AND failed to read
    "conflict": ("▓", "#ff33ff"),
    "blank": ("▓", "#ff3333"),  # alias for bad
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
        self._file_boundaries: list[tuple[str, list[int]]] = []  # (name, [sectors])

    def reset(self, pass_num: int = 0, clear_files: bool = False) -> None:
        """Reset all sectors to waiting state for a new pass."""
        self._cells = ["waiting"] * TOTAL_SECTORS
        self._current_sector = -1
        self._pass_num = pass_num
        if clear_files:
            self._file_boundaries = []
        self.refresh()

    def update_sector(self, index: int, state: str) -> None:
        """Update a single sector's state."""
        if 0 <= index < TOTAL_SECTORS:
            # Clear previous "reading" indicator only when moving to a different sector
            if (
                self._current_sector >= 0
                and self._current_sector != index
                and self._cells[self._current_sector] == "reading"
            ):
                self._cells[self._current_sector] = "waiting"

            self._cells[index] = state
            if state == "reading":
                self._current_sector = index
            elif state in ("good", "bad"):
                # Track read head position even for non-reading states
                # so the indicator shows during bulk track reads
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

    def set_file_boundaries(self, boundaries: list[tuple[str, list[int]]]) -> None:
        """Set file boundary overlay: list of (filename, [sector_indices])."""
        self._file_boundaries = boundaries
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

        # Build file boundary lookup: sector -> file_index
        sector_to_file: dict[int, int] = {}  # sector -> file_index
        file_start_sectors: dict[int, int] = {}  # sector -> file_index
        if self._file_boundaries:
            for fi, (_name, sectors) in enumerate(self._file_boundaries):
                if sectors:
                    file_start_sectors[sectors[0]] = fi
                for s in sectors:
                    sector_to_file[s] = fi

        # Header
        if self._pass_num > 0:
            text.append(f"  Pass {self._pass_num}  ", style="bold")
        text.append("░ waiting  ", style="#333333")
        text.append("▓ reading  ", style="#ffffff")
        text.append("▓ good  ", style="#33ff33")
        text.append("▓ recovered  ", style="#33aaff")
        text.append("▓ bad  ", style="#ff3333")
        text.append("▓ marked", style="#ff8800")
        text.append("\n\n")

        # File colors — cycle for visual distinction between files
        _FILE_COLORS = [
            "#ffaa00",
            "#00ccff",
            "#ff66cc",
            "#66ff66",
            "#ffff44",
            "#cc88ff",
            "#ff8844",
            "#44ffcc",
        ]

        # Sector state as background color — shows progress under filename text
        _STATE_BG = {
            "good": "#1a6b1a",
            "recovered": "#1a4a6b",
            "reading": "#666666",
            "waiting": "#1a1a1a",
            "bad": "#6b1a1a",
            "marked": "#6b4400",
            "marked_bad": "#6b1a1a",
            "blank": "#6b1a1a",
            "conflict": "#6b1a6b",
        }

        # Build sector -> overlay info for filename text on grid
        # Each entry: (char_to_show, file_color)
        # First sector of each file gets a space separator, then the filename
        # is spelled out across the file's sectors. If the name is longer than
        # the sectors, it's truncated.
        sector_char: dict[int, tuple[str, str]] = {}
        if self._file_boundaries:
            for fi, (name, sectors) in enumerate(self._file_boundaries):
                fc = _FILE_COLORS[fi % len(_FILE_COLORS)]
                if not sectors:
                    continue
                # If filename fits within sectors (with leading space), use it.
                # Otherwise truncate the name to fit.
                display_name = " " + name if len(name) + 1 <= len(sectors) else name
                for ci, s in enumerate(sectors):
                    if ci < len(display_name):
                        sector_char[s] = (display_name[ci], fc)
                    else:
                        # Past the filename — show normal sector state with tinted bg
                        sector_char[s] = ("", fc)

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

                # File overlay: filename text with sector state as background
                if idx in sector_char:
                    oc, fc = sector_char[idx]
                    bg = _STATE_BG.get(state, "#1a1a1a")

                    if oc:
                        text.append(oc, style=f"{fc} on {bg}")
                    else:
                        text.append(char, style=f"{color} on {bg}")
                else:
                    text.append(char, style=color)
            text.append("\n")

        # Read head indicator (during live reads — hidden after completion
        # when the screen resets _current_sector to -1)
        if self._current_sector >= 0:
            sectors_per_track = 18
            track = self._current_sector // (sectors_per_track * 2)
            head = (self._current_sector // sectors_per_track) % 2
            sector_in_track = self._current_sector % sectors_per_track

            bar_width = 40
            pos = int(bar_width * track / 80)

            text.append("  Reading: ", style="bold")
            text.append(f"Track {track:02d}", style="bold #33ff33")
            text.append(f"  Side {'A' if head == 0 else 'B'}", style="bold")
            text.append(f"  Sector {sector_in_track + 1}/18  ", style="dim")
            text.append("─" * pos, style="dim")
            text.append("▸", style="bold #33ff33")
            text.append("─" * (bar_width - pos - 1), style="dim")
            text.append("\n")

        # Stats
        good = self._cells.count("good")
        recovered = self._cells.count("recovered")
        bad = (
            self._cells.count("bad") + self._cells.count("blank") + self._cells.count("marked_bad")
        )
        marked = self._cells.count("marked")
        waiting = self._cells.count("waiting")
        reading = self._cells.count("reading")
        done = TOTAL_SECTORS - waiting - reading

        if done > 0:
            pct = 100 * done / TOTAL_SECTORS
            parts = f"{good} good"
            if recovered:
                parts += f", {recovered} recovered"
            if bad:
                parts += f", {bad} bad"
            if marked:
                parts += f", {marked} marked"
            text.append(f"\n  {done}/{TOTAL_SECTORS} sectors ({pct:.0f}%)  [{parts}]", style="dim")

        # File boundary legend with details
        if self._file_boundaries:
            text.append("\n\n  Files on disk:\n", style="bold")
            for fi, (name, sectors) in enumerate(self._file_boundaries):
                if not sectors:
                    continue
                size_kb = len(sectors) * 512 / 1024
                start_offset = sectors[0] * 512
                # Count how many sectors are good/recovered vs bad
                file_good = sum(
                    1
                    for s in sectors
                    if s < len(self._cells) and self._cells[s] in ("good", "recovered")
                )
                file_total = len(sectors)
                health = f"{100 * file_good // file_total}%" if file_total else "?"
                fc = _FILE_COLORS[fi % len(_FILE_COLORS)]
                text.append(f"    {name:<15s}", style=f"{fc} bold")
                text.append(f"  {size_kb:.0f}KB  @ 0x{start_offset:06X}  ", style="dim")
                if file_good == file_total:
                    text.append(f"{health} OK", style="green")
                elif file_good == 0:
                    text.append(f"{health} damaged", style="red bold")
                else:
                    text.append(f"{health} partial", style="#ffaa00")
                text.append("\n")

        return text
