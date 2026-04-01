"""GPS screen — merge GPS track data into photos."""

import glob as globmod
import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, ProgressBar, RichLog, Static

from mavica_tools.tui.widgets.file_picker import FilePicker


class GpsScreen(Screen):
    """Merge GPS tracks into recovered Mavica photos."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]GPS Track Merge[/]  [dim]Match photo timestamps to GPS logger data[/]\n",
            id="title-bar",
        )
        yield Static(
            "  [dim]Pair your Mavica photos with GPS tracks from a Garmin,\n"
            "  phone GPX export, or Google Timeline.\n"
            "  Uses EXIF DateTimeOriginal (from 'Add Photo Info') or file modification time.[/]\n"
        )
        # Show piexif status
        try:
            import piexif  # noqa: F401

            yield Static(
                "  [green]piexif installed[/] — GPS coordinates will be written to EXIF.\n"
            )
        except ImportError:
            yield Static(
                "  [#ffaa00]piexif not installed[/] — preview works, but GPS won't be saved to files.\n"
                "  [dim]Install with:[/] [bold]pip install mavica-tools\\[gps][/]\n"
            )
        yield Static("  [bold]Photos[/]")
        with Horizontal(classes="input-row"):
            yield Input(placeholder="Photos directory...", id="photos-path")
            yield Button("Browse Photos", id="btn-browse-photos")
        yield Static("  [bold]GPX Track[/]")
        with Horizontal(classes="input-row"):
            yield Input(placeholder="GPX track file...", id="gpx-path")
            yield Button("Browse GPX", id="btn-browse-gpx")
        yield Static("  [bold]Tolerance[/]")
        with Horizontal(classes="input-row"):
            yield Input(value="5m", placeholder="Tolerance (e.g., 5m, 30s, 1h)", id="tolerance")
        with Horizontal(classes="button-row"):
            yield Button("Preview (Dry Run)", variant="warning", id="btn-preview")
            yield Button("Merge GPS", variant="success", id="btn-merge")
            yield Button("Generate Map", variant="default", id="btn-map", disabled=True)
        yield ProgressBar(total=100, show_percentage=True, show_eta=True, id="progress")
        yield DataTable(id="results-table")
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Status", "Filename", "Location", "Offset")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse-photos":
            self._browse("photos-path", select_directory=True, title="Select photos directory")
        elif event.button.id == "btn-browse-gpx":
            self._browse("gpx-path", extensions=(".gpx",), title="Select GPX file")
        elif event.button.id == "btn-preview":
            self._run_merge(dry_run=True)
        elif event.button.id == "btn-merge":
            self._run_merge(dry_run=False)
        elif event.button.id == "btn-map":
            self._gen_map()

    def _browse(self, input_id, **kwargs):
        def on_selected(path: str) -> None:
            if path:
                self.query_one(f"#{input_id}", Input).value = path

        self.app.push_screen(FilePicker(**kwargs), on_selected)

    def _run_merge(self, dry_run: bool) -> None:
        photos = self.query_one("#photos-path", Input).value.strip()
        gpx = self.query_one("#gpx-path", Input).value.strip()
        if not photos or not gpx:
            self.notify("Enter both photos directory and GPX file", severity="warning")
            return
        self.run_worker(self._do_merge(photos, gpx, dry_run), exclusive=True)

    async def _do_merge(self, photos_dir: str, gpx_path: str, dry_run: bool) -> None:
        from mavica_tools.gps import match_photos_to_track, parse_gpx, stamp_gps_exif

        log = self.query_one("#log", RichLog)
        table = self.query_one("#results-table", DataTable)
        progress = self.query_one("#progress", ProgressBar)
        table.clear()

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

        track = parse_gpx(gpx_path)
        log.write(f"Loaded {len(track)} trackpoints from GPX")

        files = []
        for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
            files.extend(globmod.glob(os.path.join(photos_dir, ext)))
        files.sort()
        log.write(f"Found {len(files)} photo(s)\n")

        if not files or not track:
            log.write("[red]Need both photos and GPS data.[/]")
            return

        progress.update(total=len(files), progress=0)
        matches = match_photos_to_track(files, track, tolerance_seconds=tolerance)

        matched = 0
        for i, (path, match) in enumerate(zip(files, matches)):
            name = os.path.basename(path)
            if match:
                matched += 1
                loc = f"{match.point.lat:.6f}, {match.point.lon:.6f}"
                offset = f"{match.offset_seconds:.0f}s"

                if dry_run:
                    table.add_row("[#ffaa00]PREVIEW[/]", name, loc, offset)
                else:
                    ok, msg = stamp_gps_exif(
                        path,
                        match.point.lat,
                        match.point.lon,
                        match.point.alt,
                        match.point.time,
                    )
                    status = "[green]OK[/]" if ok else "[red]FAIL[/]"
                    table.add_row(status, name, loc, offset)
            else:
                table.add_row("[dim]SKIP[/]", name, "-", "-")

            progress.update(progress=i + 1)

        log.write(f"\n[bold]{matched}/{len(files)} photos matched[/]")
        if dry_run:
            log.write("[dim](dry run — no files modified)[/]")

        if matched:
            self.query_one("#btn-map", Button).disabled = False
            self._photos_dir = photos_dir

    def _gen_map(self) -> None:
        if hasattr(self, "_photos_dir"):
            self.run_worker(self._do_map(), exclusive=True)

    async def _do_map(self) -> None:
        from datetime import timezone

        from mavica_tools.gps import GpsMatch, GpsPoint, generate_map_html

        log = self.query_one("#log", RichLog)
        photos_dir = self._photos_dir

        # Read GPS from EXIF
        files = []
        for ext in ("*.jpg", "*.JPG"):
            files.extend(globmod.glob(os.path.join(photos_dir, ext)))

        matches = []
        for path in sorted(files):
            try:
                from PIL import Image

                img = Image.open(path)
                exif = img.getexif()
                gps = exif.get(0x8825)
                if gps and 0x0002 in gps:
                    lat_dms = gps[0x0002]
                    lon_dms = gps[0x0004]
                    lat = (
                        lat_dms[0][0] / lat_dms[0][1]
                        + lat_dms[1][0] / (lat_dms[1][1] * 60)
                        + lat_dms[2][0] / (lat_dms[2][1] * 3600)
                    )
                    lon = (
                        lon_dms[0][0] / lon_dms[0][1]
                        + lon_dms[1][0] / (lon_dms[1][1] * 60)
                        + lon_dms[2][0] / (lon_dms[2][1] * 3600)
                    )
                    if gps.get(0x0001) == "S":
                        lat = -lat
                    if gps.get(0x0003) == "W":
                        lon = -lon
                    from datetime import datetime

                    matches.append(
                        GpsMatch(
                            photo_path=path,
                            point=GpsPoint(
                                lat=lat, lon=lon, alt=None, time=datetime.now(tz=timezone.utc)
                            ),
                            offset_seconds=0,
                        )
                    )
            except Exception:
                pass

        if matches:
            out = os.path.join(photos_dir, "map.html")
            generate_map_html(matches, out, title="Mavica Photo Map")
            log.write(f"[green]Map generated: {out} ({len(matches)} photos)[/]")
        else:
            log.write("[red]No geotagged photos found.[/]")
