"""Braille scatter plot widget for GPS tracks.

Renders GPX track points and photo match positions using braille
characters (U+2800 block). Each braille cell is 2x4 dots, giving
higher density than half-block characters.
"""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget


class TrackMap(Widget):
    """Braille scatter plot of a GPS track with photo match markers."""

    DEFAULT_CSS = """
    TrackMap {
        height: 1fr;
        min-height: 5;
        border: tall #333333;
        padding: 0 1;
    }
    """

    highlight_index: reactive[int] = reactive(-1, layout=False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._track: list[tuple[float, float]] = []  # (lat, lon)
        self._matches: list[tuple[float, float] | None] = []  # per-file match coords
        self._bounds: tuple[float, float, float, float] | None = (
            None  # min_lat, max_lat, min_lon, max_lon
        )
        self._label: str = ""
        self._n_matched: int = 0

    def set_track(self, points: list[tuple[float, float]]) -> None:
        """Set the background track as (lat, lon) pairs."""
        self._track = points
        self._bounds = self._compute_bounds(points)
        self._matches = []
        self._n_matched = 0
        self._label = f"{len(points)} trackpoints"
        self.refresh()

    def set_matches(self, matches: list[tuple[float, float] | None]) -> None:
        """Set photo match positions. None = no match for that file."""
        self._matches = matches
        self._n_matched = sum(1 for m in matches if m is not None)
        # Expand bounds to include match points
        all_pts = list(self._track)
        all_pts.extend(p for p in matches if p is not None)
        if all_pts:
            self._bounds = self._compute_bounds(all_pts)
        self.refresh()

    @staticmethod
    def _compute_bounds(
        points: list[tuple[float, float]],
    ) -> tuple[float, float, float, float]:
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        # Add small padding
        pad_lat = max((max_lat - min_lat) * 0.05, 0.0001)
        pad_lon = max((max_lon - min_lon) * 0.05, 0.0001)
        return (min_lat - pad_lat, max_lat + pad_lat, min_lon - pad_lon, max_lon + pad_lon)

    def _map_to_cell(self, lat: float, lon: float, cols: int, rows: int) -> tuple[int, int]:
        """Map lat/lon to braille dot coordinates (col, row)."""
        if not self._bounds:
            return (0, 0)
        min_lat, max_lat, min_lon, max_lon = self._bounds
        lat_range = max_lat - min_lat
        lon_range = max_lon - min_lon
        if lat_range == 0:
            lat_range = 0.001
        if lon_range == 0:
            lon_range = 0.001

        # Normalize to 0..1
        nx = (lon - min_lon) / lon_range
        # Lat is inverted (higher lat = top of screen = lower row)
        ny = 1.0 - (lat - min_lat) / lat_range

        # Braille: each cell is 2 dots wide, 4 dots tall
        dot_x = int(nx * (cols * 2 - 1))
        dot_y = int(ny * (rows * 4 - 1))
        dot_x = max(0, min(cols * 2 - 1, dot_x))
        dot_y = max(0, min(rows * 4 - 1, dot_y))
        return (dot_x, dot_y)

    def render(self) -> Text:
        w = self.size.width
        h = self.size.height
        if w < 2 or h < 2 or not self._bounds:
            if self._track:
                return Text("(loading map...)", style="dim")
            text = Text()
            text.append("  GPX Track Map\n", style="dim")
            text.append("  Load a GPX file to see the route", style="dim")
            return text

        # Reserve first line for label
        text = Text()
        label = Text()
        label.append("  Track Map", style="bold")
        label.append(f"  {self._label}", style="dim")
        if self._n_matched:
            label.append(f"  {self._n_matched} matched", style="green")
        text.append_text(label)
        text.append("\n")

        plot_h = h - 1  # subtract label row
        if plot_h < 1:
            return text

        # Build braille grid
        grid_colors: list[list[str]] = [["" for _ in range(w)] for _ in range(plot_h)]
        grid_dots: list[list[set]] = [[set() for _ in range(w)] for _ in range(plot_h)]

        # Braille dot offset mapping: (dx, dy) -> bit position
        dot_map = {
            (0, 0): 0x01,
            (0, 1): 0x02,
            (0, 2): 0x04,
            (0, 3): 0x40,
            (1, 0): 0x08,
            (1, 1): 0x10,
            (1, 2): 0x20,
            (1, 3): 0x80,
        }

        # Marker overlay: (row, col) -> (char, style) for match positions
        markers: dict[tuple[int, int], tuple[str, str]] = {}

        def _plot(lat: float, lon: float, color: str) -> None:
            dot_x, dot_y = self._map_to_cell(lat, lon, w, plot_h)
            cell_col = dot_x // 2
            cell_row = dot_y // 4
            dx = dot_x % 2
            dy = dot_y % 4
            if 0 <= cell_col < w and 0 <= cell_row < plot_h:
                grid_dots[cell_row][cell_col].add((dx, dy))
                if _color_priority(color) >= _color_priority(grid_colors[cell_row][cell_col]):
                    grid_colors[cell_row][cell_col] = color

        # Plot track (dim)
        for lat, lon in self._track:
            _plot(lat, lon, "dim white")

        # Plot match markers as ● (green) or ★ (highlighted) — overlays the braille cell
        for i, m in enumerate(self._matches):
            if m is not None:
                dot_x, dot_y = self._map_to_cell(m[0], m[1], w, plot_h)
                cell_col = dot_x // 2
                cell_row = dot_y // 4
                if 0 <= cell_col < w and 0 <= cell_row < plot_h:
                    if i == self.highlight_index:
                        markers[(cell_row, cell_col)] = ("\u2605", "bold yellow")  # ★
                    else:
                        markers[(cell_row, cell_col)] = ("\u25cf", "bold green")  # ●

        # Render braille grid with marker overlays
        for row in range(plot_h):
            for col in range(w):
                if (row, col) in markers:
                    char, style = markers[(row, col)]
                    text.append(char, style=style)
                elif grid_dots[row][col]:
                    cp = 0x2800
                    for dx, dy in grid_dots[row][col]:
                        cp |= dot_map.get((dx, dy), 0)
                    color = grid_colors[row][col] or "dim white"
                    text.append(chr(cp), style=color)
                else:
                    text.append(" ")
            if row < plot_h - 1:
                text.append("\n")

        return text

    def watch_highlight_index(self) -> None:
        self.refresh()


def _color_priority(color: str) -> int:
    """Priority for color overwriting — higher wins."""
    if "yellow" in color:
        return 3
    if "green" in color:
        return 2
    if "red" in color:
        return 1
    return 0
