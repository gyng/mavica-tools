"""GPS screen — merge GPS track data into photos."""

import glob as globmod
import os
import webbrowser
from datetime import UTC

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    ProgressBar,
    RichLog,
    Select,
    Static,
)
from textual.worker import get_current_worker

from mavica_tools.tui.widgets.file_picker import FilePicker
from mavica_tools.tui.widgets.image_preview import ImagePreview
from mavica_tools.tui.widgets.track_map import TrackMap


class GpsScreen(Screen):
    """Merge GPS tracks into recovered Mavica photos."""

    DEFAULT_CSS = """
    GpsScreen VerticalScroll {
        height: 1fr;
    }
    #gps-main {
        height: auto;
        min-height: 10;
    }
    #gps-left {
        width: 1fr;
        min-width: 30;
    }
    #gps-right {
        width: 40;
        min-width: 30;
        align: center top;
    }
    #gps-right ImagePreview {
        height: 1fr;
        min-height: 6;
        content-align: center top;
        margin-bottom: 1;
    }
    #gps-right TrackMap {
        height: 1fr;
        min-height: 5;
    }
    GpsScreen #results-table {
        height: auto;
        margin: 0;
    }
    GpsScreen #tolerance {
        width: 12;
    }
    GpsScreen #interpolate-select {
        width: 1fr;
        height: auto;
    }
    GpsScreen #log {
        height: 2;
        max-height: 3;
        margin: 0;
        border: none;
    }
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
        Binding("f2", "merge", "Merge", show=True),
        Binding("p", "preview", "Preview", show=True),
        Binding("i", "open_source", "Open In", show=True),
    ]

    _prefill_photos: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static(
                "[bold #ffaa00]GPS Track Merge[/]  [dim]Match photo timestamps to GPS logger data[/]\n",
                id="title-bar",
            )

            # Photos row
            with Horizontal(classes="input-row"):
                yield Static(" [bold]Photos[/] ", classes="row-label")
                yield Input(placeholder="Photos directory...", id="photos-path")
                yield Button("Browse", id="btn-browse-photos")
                yield Button("Open", id="btn-open-source")

            # GPX row
            with Horizontal(classes="input-row"):
                yield Static("    [bold]GPX[/] ", classes="row-label")
                yield Input(placeholder="GPX track file...", id="gpx-path")
                yield Button("Browse", id="btn-browse-gpx")

            # Tolerance + Interpolate row
            with Horizontal(classes="input-row"):
                yield Static("    [bold]Tol[/] ", classes="row-label")
                yield Input(value="5m", placeholder="e.g., 5m, 30s, 1h", id="tolerance")
                yield Select[str](
                    [("Interpolate: Yes", "yes"), ("Interpolate: No", "no")],
                    value="yes",
                    id="interpolate-select",
                    allow_blank=False,
                    compact=True,
                )

            # Action buttons + progress
            with Horizontal(classes="button-row"):
                yield Button("Preview (p)", variant="warning", id="btn-preview", disabled=True)
                yield Button("Merge (F2)", variant="success", id="btn-merge", disabled=True)
                yield Button("Open Map", variant="default", id="btn-map", disabled=True)
                yield ProgressBar(total=100, show_percentage=True, show_eta=True, id="progress")
            yield Static("", id="status")

            # Two-pane: file list on left, map+preview on right
            with Horizontal(id="gps-main"):
                with Vertical(id="gps-left"):
                    with Horizontal(classes="button-row"):
                        yield Button("All", variant="default", id="btn-select-all")
                        yield Button("None", variant="default", id="btn-select-none")
                        yield Static("  [dim]Space: toggle  Enter/o: open in OSM[/]")
                    yield DataTable(id="results-table")
                with Vertical(id="gps-right"):
                    yield TrackMap(id="track-map")
                    yield ImagePreview(id="preview")

            yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("", "Filename", "Size", "Date")
        table.cursor_type = "row"
        self._files: list[str] = []
        self._selected: set[int] = set()
        self._matches: list = []  # GpsMatch | None per file
        self._track: list = []  # GpsPoint list
        self._previewed = False

        log = self.query_one("#log", RichLog)
        log.write("[green]piexif installed[/] — GPS coordinates will be written to EXIF.")

        if self._prefill_photos:
            self.call_later(self._apply_prefill)
        else:
            self.call_later(self._apply_latest_import)

    # ── Input events ──────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "photos-path":
            path = event.value.strip()
            if path and os.path.isdir(path):
                self._list_files(path)
            self._update_button_states()
        elif event.input.id == "gpx-path":
            path = event.value.strip()
            if path and os.path.isfile(path):
                self._load_gpx(path)
            self._update_button_states()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "photos-path":
            path = event.value.strip()
            if path:
                self._list_files(path)
        elif event.input.id == "gpx-path":
            path = event.value.strip()
            if path:
                self._load_gpx(path)

    # ── File listing ──────────────────────────────────────────────

    def _list_files(self, source: str) -> None:
        """List JPEG files from photos directory."""
        table = self.query_one("#results-table", DataTable)
        table.clear()
        self._files = []
        self._matches = []
        self._previewed = False

        files = self._gather_jpegs(source)
        if not files:
            table.add_row("", "[dim]No JPEG files found[/]", "", "")
            return

        self._files = files
        self._selected = set(range(len(files)))

        self._refresh_file_list()
        self._update_button_labels()

        log = self.query_one("#log", RichLog)
        log.write(f"[dim]{len(files)} photo(s) loaded[/]")

        # Preview first file
        if files and files[0].lower().endswith((".jpg", ".jpeg")):
            self.query_one("#preview", ImagePreview).image_path = files[0]
        table.focus()

        # Auto-detect GPX in the photos directory if not already specified
        gpx_input = self.query_one("#gpx-path", Input)
        if not gpx_input.value.strip() and os.path.isdir(source):
            gpx_file, reason = self._find_gpx_in_dir(source, files)
            if gpx_file:
                gpx_input.value = gpx_file
                self.notify(
                    f"Auto-loaded {os.path.basename(gpx_file)} — {reason}",
                    severity="information",
                )

        # Auto-preview if GPX is already loaded
        if self._track:
            self._run_merge(dry_run=True)

    def _refresh_file_list(self) -> None:
        """Rebuild table with current selection state and match data."""
        table = self.query_one("#results-table", DataTable)
        cursor = table.cursor_row
        table.clear()

        # Set columns based on whether we've previewed
        table.columns.clear()
        if self._previewed and self._matches:
            table.add_columns("", "Filename", "Size", "Date", "Location", "Offset")
        else:
            table.add_columns("", "Filename", "Size", "Date")

        highlighted = table.cursor_row

        for i, f in enumerate(self._files):
            selected = i in self._selected
            name = os.path.basename(f)
            try:
                size_kb = os.path.getsize(f) / 1024
                size_str = f"{size_kb:.0f}KB"
            except OSError:
                size_str = "?"

            date_str = self._get_photo_date(f)
            sel = "[green]\u25cf[/]" if selected else "[dim]\u25cb[/]"

            if not selected:
                name = f"[dim]{name}[/]"
                size_str = f"[dim]{size_str}[/]"
                date_str = f"[dim]{date_str}[/]"

            if self._previewed and self._matches:
                match = self._matches[i] if i < len(self._matches) else None
                if match:
                    loc = f"{match.point.lat:.3f}, {match.point.lon:.3f}"
                    # Compact offset: time (sec/min) + interpolation distance (metres/km)
                    secs = match.offset_seconds
                    time_str = f"{secs / 60:.0f}min" if secs >= 60 else f"{secs:.0f}sec"
                    offset_parts = [time_str]
                    if match.interpolated and match.nearest_distance_m > 0:
                        d = match.nearest_distance_m
                        if d >= 1000:
                            offset_parts.append(f"~{d / 1000:.1f}km")
                        else:
                            offset_parts.append(f"~{d:.0f}m")
                    offset = " ".join(offset_parts)
                    if not selected:
                        loc = f"[dim]{loc}[/]"
                        offset = f"[dim]{offset}[/]"
                    elif i == highlighted:
                        loc = f"[green]{loc}[/] [dim](o)[/]"
                    else:
                        loc = f"[green]{loc}[/]"
                else:
                    loc = "[dim]-[/]"
                    offset = "[dim]-[/]"
                table.add_row(sel, name, size_str, date_str, loc, offset)
            else:
                table.add_row(sel, name, size_str, date_str)

        if cursor is not None and cursor < len(self._files):
            table.move_cursor(row=cursor)

        self._update_button_labels()

    @staticmethod
    def _get_photo_date(path: str) -> str:
        """Get short date string from photo."""
        try:
            from mavica_tools.utils import get_photo_timestamp

            ts = get_photo_timestamp(path)
            if ts:
                return ts.strftime("%m-%d %H:%M")
        except Exception:
            pass
        try:
            from datetime import datetime

            mtime = os.path.getmtime(path)
            return datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
        except Exception:
            return "?"

    @staticmethod
    def _find_gpx_in_dir(directory: str, photos: list[str] | None = None) -> tuple[str | None, str]:
        """Find the best .gpx file in the directory or its parent.

        Selection strategy (first match wins):
        1. GPX track time range overlaps the photos' timestamps
        2. GPX filename contains a date that matches the photos' date
        3. GPX filename matches the directory name
        4. Only one GPX file — use it
        5. Most recently modified GPX file

        Returns (path, reason) or (None, "").
        """
        import re

        gpx_files: list[str] = []
        for d in (directory, os.path.dirname(directory)):
            if not d or not os.path.isdir(d):
                continue
            gpx_files.extend(globmod.glob(os.path.join(d, "*.gpx")))
            gpx_files.extend(globmod.glob(os.path.join(d, "*.GPX")))
        if not gpx_files:
            return None, ""

        # Deduplicate
        gpx_files = sorted(set(gpx_files))

        if len(gpx_files) == 1:
            return gpx_files[0], "only GPX file found"

        # Get photo timestamps for matching
        photo_times = []
        photo_dates: set[str] = set()
        if photos:
            from mavica_tools.utils import get_photo_timestamp

            for p in photos[:10]:  # sample first 10
                try:
                    ts = get_photo_timestamp(p)
                    if ts:
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=UTC)
                        photo_times.append(ts)
                        photo_dates.add(ts.strftime("%Y-%m-%d"))
                        photo_dates.add(ts.strftime("%Y%m%d"))
                except Exception:
                    pass

        # Strategy 1: GPX track time range overlaps photo timestamps
        if photo_times:
            from mavica_tools.gps import parse_gpx

            photo_min = min(photo_times)
            photo_max = max(photo_times)
            best_gpx = None
            best_overlap = -1
            best_reason = ""

            for gpx in gpx_files:
                try:
                    track = parse_gpx(gpx)
                    if not track:
                        continue
                    track_min = track[0].time
                    track_max = track[-1].time
                    # Check overlap: expand track window by tolerance (5min)
                    from datetime import timedelta

                    margin = timedelta(minutes=5)
                    if track_min - margin <= photo_max and track_max + margin >= photo_min:
                        # Compute overlap quality: how many photos fall within track range
                        overlap = sum(
                            1 for t in photo_times if track_min - margin <= t <= track_max + margin
                        )
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_gpx = gpx
                            date_range = track_min.strftime("%m-%d %H:%M")
                            best_reason = (
                                f"track covers {overlap}/{len(photo_times)} photo timestamps "
                                f"({date_range}\u2013{track_max.strftime('%H:%M')})"
                            )
                except Exception:
                    continue

            if best_gpx:
                return best_gpx, best_reason

        # Strategy 2: GPX filename contains a photo date
        if photo_dates:
            for gpx in gpx_files:
                gpx_name = os.path.basename(gpx).lower()
                for date_str in photo_dates:
                    if date_str in gpx_name:
                        return gpx, f"filename matches photo date {date_str}"

        # Strategy 3: GPX filename matches directory name
        dir_name = os.path.basename(directory).lower()
        dir_dates = re.findall(r"\d{4}[-_]?\d{2}[-_]?\d{2}", dir_name)
        for gpx in gpx_files:
            gpx_name = os.path.basename(gpx).lower()
            for dd in dir_dates:
                clean = dd.replace("-", "").replace("_", "")
                if clean in gpx_name.replace("-", "").replace("_", ""):
                    return gpx, "filename matches directory date"

        # Strategy 4: most recently modified
        gpx_files.sort(key=os.path.getmtime, reverse=True)
        n = len(gpx_files)
        return gpx_files[0], f"most recent of {n} GPX files"

    @staticmethod
    def _gather_jpegs(source: str) -> list[str]:
        """Gather JPEG files from a directory."""
        files = []
        if os.path.isdir(source):
            for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
                files.extend(globmod.glob(os.path.join(source, ext)))
        elif os.path.isfile(source):
            files.append(source)

        seen: set[str] = set()
        deduped: list[str] = []
        for f in files:
            key = os.path.normcase(f)
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        return sorted(deduped)

    # ── GPX loading ───────────────────────────────────────────────

    def _load_gpx(self, gpx_path: str) -> None:
        """Load GPX file and update track map."""
        try:
            from mavica_tools.gps import parse_gpx

            track = parse_gpx(gpx_path)
            self._track = track
            if track:
                track_map = self.query_one("#track-map", TrackMap)
                track_map.set_track([(p.lat, p.lon) for p in track])
                log = self.query_one("#log", RichLog)
                log.write(f"[dim]{len(track)} trackpoints loaded[/]")
                self._update_button_states()
                # Auto-preview if photos are already loaded
                if self._files:
                    self._run_merge(dry_run=True)
        except Exception as e:
            self.notify(f"Failed to load GPX: {e}", severity="error")

    # ── Selection ─────────────────────────────────────────────────

    def _toggle_row(self, idx: int) -> None:
        if idx >= len(self._files):
            return
        if idx in self._selected:
            self._selected.discard(idx)
        else:
            self._selected.add(idx)
        self._refresh_file_list()

    def _toggle_all(self, select: bool) -> None:
        if select:
            self._selected = set(range(len(self._files)))
        else:
            self._selected = set()
        self._refresh_file_list()

    def _update_button_labels(self) -> None:
        n = len(self._selected)
        self.query_one("#btn-preview", Button).label = f"Preview {n} (p)" if n else "Preview (p)"
        self.query_one("#btn-merge", Button).label = f"Merge {n} (F2)" if n else "Merge (F2)"

    def _update_button_states(self) -> None:
        """Enable/disable buttons based on current inputs."""
        has_photos = bool(self._files)
        has_gpx = bool(self._track)
        both = has_photos and has_gpx
        self.query_one("#btn-preview", Button).disabled = not both
        self.query_one("#btn-merge", Button).disabled = not both
        self.query_one("#btn-map", Button).disabled = not has_gpx

    # ── Preview / highlight ───────────────────────────────────────

    _highlighted_row: int = -1

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None:
            return
        if self._files and event.cursor_row < len(self._files):
            path = self._files[event.cursor_row]
            if path.lower().endswith((".jpg", ".jpeg")):
                self.query_one("#preview", ImagePreview).image_path = path
            # Highlight on track map
            self.query_one("#track-map", TrackMap).highlight_index = event.cursor_row
            # Move (o) hint to the new row
            prev = self._highlighted_row
            self._highlighted_row = event.cursor_row
            if self._previewed and self._matches:
                self._update_location_hint(prev)
                self._update_location_hint(event.cursor_row)

    def _update_location_hint(self, row: int) -> None:
        """Update the Location cell for a row to show/hide the (o) hint."""
        if row < 0 or row >= len(self._files) or row >= len(self._matches):
            return
        table = self.query_one("#results-table", DataTable)
        match = self._matches[row]
        selected = row in self._selected
        if match:
            loc = f"{match.point.lat:.3f}, {match.point.lon:.3f}"
            if not selected:
                loc = f"[dim]{loc}[/]"
            elif row == self._highlighted_row:
                loc = f"[green]{loc}[/] [dim](o)[/]"
            else:
                loc = f"[green]{loc}[/]"
        else:
            loc = "[dim]-[/]"
        try:
            row_key = table.ordered_rows[row].key
            col_key = table.ordered_columns[4].key  # Location column
            table.update_cell(row_key, col_key, loc)
        except (IndexError, KeyError):
            pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a row opens its matched location in OSM."""
        if event.cursor_row is not None:
            self._open_row_in_osm(event.cursor_row)

    # ── Key handling ──────────────────────────────────────────────

    def on_key(self, event) -> None:
        table = self.query_one("#results-table", DataTable)
        if not table.has_focus or not self._files:
            return
        if event.key == "space":
            event.prevent_default()
            event.stop()
            self._toggle_row(table.cursor_row)
        elif event.key == "o":
            event.prevent_default()
            event.stop()
            self._open_row_in_osm(table.cursor_row)

    def _open_row_in_osm(self, row: int) -> None:
        """Open the matched GPS location for this row in OSM."""
        if not self._matches or row >= len(self._matches):
            self.notify("Run Preview first to match photos to GPS", severity="warning")
            return
        match = self._matches[row]
        if match is None:
            self.notify("No GPS match for this photo", severity="warning")
            return
        url = f"https://www.openstreetmap.org/#map=17/{match.point.lat:.6f}/{match.point.lon:.6f}"
        webbrowser.open(url)

    # ── Button handlers ───────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse-photos":
            self.action_browse()
        elif event.button.id == "btn-browse-gpx":
            self._browse_gpx()
        elif event.button.id == "btn-open-source":
            self.action_open_source()
        elif event.button.id == "btn-preview":
            self.action_preview()
        elif event.button.id == "btn-merge":
            self.action_merge()
        elif event.button.id == "btn-map":
            self.action_open_map()
        elif event.button.id == "btn-select-all":
            self._toggle_all(True)
        elif event.button.id == "btn-select-none":
            self._toggle_all(False)

    # ── Actions / keybindings ─────────────────────────────────────

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#photos-path", Input).value = path

        self.app.push_screen(
            FilePicker(title="Select photos directory", select_directory=True),
            on_selected,
        )

    def _browse_gpx(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#gpx-path", Input).value = path

        self.app.push_screen(
            FilePicker(extensions=(".gpx",), title="Select GPX file"),
            on_selected,
        )

    def action_open_source(self) -> None:
        from mavica_tools.utils import open_directory

        source = self.query_one("#photos-path", Input).value.strip()
        if source:
            d = source if os.path.isdir(source) else os.path.dirname(source)
            d = os.path.abspath(d) if d else ""
            if d and os.path.isdir(d):
                open_directory(d)

    def action_preview(self) -> None:
        self._run_merge(dry_run=True)

    def action_merge(self) -> None:
        self._run_merge(dry_run=False)

    def action_open_map(self) -> None:
        """Open OSM centered on the track bounding box."""
        if not self._track:
            self.notify("Load a GPX file first", severity="warning")
            return
        lats = [p.lat for p in self._track]
        lons = [p.lon for p in self._track]
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)
        # Calculate zoom from bounding box span
        lat_span = max(lats) - min(lats)
        lon_span = max(lons) - min(lons)
        span = max(lat_span, lon_span)
        if span > 10:
            zoom = 6
        elif span > 1:
            zoom = 8
        elif span > 0.1:
            zoom = 11
        elif span > 0.01:
            zoom = 14
        else:
            zoom = 16
        url = f"https://www.openstreetmap.org/#map={zoom}/{center_lat:.6f}/{center_lon:.6f}"
        webbrowser.open(url)

    # ── Prefill ───────────────────────────────────────────────────

    def _apply_prefill(self) -> None:
        self.query_one("#photos-path", Input).value = self._prefill_photos

    def _apply_latest_import(self) -> None:
        """Auto-detect latest import directory with JPEGs."""
        out_dir = "mavica_out"
        if not os.path.isdir(out_dir):
            return
        candidates = []
        for name in os.listdir(out_dir):
            path = os.path.join(out_dir, name)
            if os.path.isdir(path) and name.startswith("import_"):
                jpegs = globmod.glob(os.path.join(path, "*.jpg")) + globmod.glob(
                    os.path.join(path, "*.JPG")
                )
                if jpegs:
                    candidates.append((os.path.getmtime(path), path, len(jpegs)))
        if candidates:
            candidates.sort(reverse=True)
            _, path, count = candidates[0]
            self.query_one("#photos-path", Input).value = path
            self.notify(
                f"Loaded {os.path.basename(path)} ({count} photo{'s' if count != 1 else ''})",
                severity="information",
            )

    # ── Merge / preview worker ────────────────────────────────────

    def _run_merge(self, dry_run: bool) -> None:
        photos = self.query_one("#photos-path", Input).value.strip()
        gpx = self.query_one("#gpx-path", Input).value.strip()
        if not photos or not gpx:
            self.notify("Enter both photos directory and GPX file", severity="warning")
            return
        if not self._files:
            self.notify("No photos loaded", severity="warning")
            return

        btn = self.query_one("#btn-merge" if not dry_run else "#btn-preview", Button)
        btn.disabled = True
        btn.label = "Merging\u2026" if not dry_run else "Matching\u2026"
        self.run_worker(self._do_merge(photos, gpx, dry_run), exclusive=True)

    async def _do_merge(self, photos_dir: str, gpx_path: str, dry_run: bool) -> None:
        from mavica_tools.gps import match_photos_to_track, parse_gpx, stamp_gps_exif

        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        progress = self.query_one("#progress", ProgressBar)
        status = self.query_one("#status", Static)

        # Parse tolerance
        tol_str = self.query_one("#tolerance", Input).value.strip().lower()
        if tol_str.endswith("m"):
            tolerance = float(tol_str[:-1]) * 60
        elif tol_str.endswith("h"):
            tolerance = float(tol_str[:-1]) * 3600
        elif tol_str.endswith("s"):
            tolerance = float(tol_str[:-1])
        else:
            tolerance = float(tol_str) * 60

        interpolate_val = self.query_one("#interpolate-select", Select).value
        interpolate = interpolate_val != "no"

        # Ensure track is loaded
        if not self._track:
            self._track = parse_gpx(gpx_path)
        track = self._track

        if not track:
            log.write("[red]No trackpoints found in GPX file.[/]")
            self._reset_buttons()
            return

        files = self._files
        to_process = [(i, files[i]) for i in sorted(self._selected) if i < len(files)]
        if not to_process:
            log.write("[red]No files selected.[/]")
            self._reset_buttons()
            return

        progress.update(total=len(to_process), progress=0)

        # Match all files
        all_paths = [files[i] for i in range(len(files))]
        matches = match_photos_to_track(
            all_paths, track, tolerance_seconds=tolerance, interpolate=interpolate
        )
        self._matches = matches
        self._previewed = True

        # Update track map with match positions
        track_map = self.query_one("#track-map", TrackMap)
        match_coords = []
        for m in matches:
            if m is not None:
                match_coords.append((m.point.lat, m.point.lon))
            else:
                match_coords.append(None)
        track_map.set_matches(match_coords)

        # Process selected files
        matched = 0
        failed = 0
        for progress_idx, (i, filepath) in enumerate(to_process):
            if worker.is_cancelled:
                log.write("[yellow]Cancelled.[/]")
                self._reset_buttons()
                return

            match = matches[i] if i < len(matches) else None
            if match:
                matched += 1
                if not dry_run:
                    ok, msg = stamp_gps_exif(
                        filepath,
                        match.point.lat,
                        match.point.lon,
                        match.point.alt,
                        match.point.time,
                    )
                    if not ok:
                        failed += 1
            progress.update(progress=progress_idx + 1)

        # Refresh table with match data
        self._refresh_file_list()

        # Status summary
        total = len(to_process)
        if dry_run:
            status.update(
                f"  [bold]Preview:[/] [green]{matched}[/]/{total} matched, "
                f"[dim]{total - matched} no match[/]  [dim](dry run — no files modified)[/]"
            )
        else:
            parts = [f"[green]{matched} geotagged[/]"]
            if failed:
                parts.append(f"[red]{failed} failed[/]")
            unmatched = total - matched
            if unmatched:
                parts.append(f"[dim]{unmatched} no match[/]")
            status.update(f"  [bold #33ff33]Done![/] {', '.join(parts)}")

        self._reset_buttons()

    def _reset_buttons(self) -> None:
        self._update_button_labels()
        self._update_button_states()
