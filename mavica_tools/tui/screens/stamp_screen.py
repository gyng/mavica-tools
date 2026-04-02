"""Stamp metadata screen — add EXIF to recovered Mavica JPEGs.

Standalone screen for tagging photos with camera model, date/timezone,
and description. Can be launched from the home screen or post-import.
"""

import glob as globmod
import os
from datetime import UTC
from typing import ClassVar

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

from mavica_tools.stamp import MAVICA_SPECS, stamp_jpeg
from mavica_tools.tui.widgets.file_picker import FilePicker
from mavica_tools.tui.widgets.image_preview import ImagePreview, inline_thumbnail

# Build camera model options: ("Sony Mavica MVC-FD7", "fd7"), ...
_CAMERA_OPTIONS = [
    (spec["model"], key)
    for key, spec in sorted(MAVICA_SPECS.items(), key=lambda kv: kv[1].get("year", 0))
]

# Timezones covering all UTC offsets where Mavica cameras were sold/used
_TIMEZONE_OPTIONS = [
    ("UTC+0  — UTC / London / Lisbon", "UTC"),
    ("UTC-12 — Baker Island", "-12"),
    ("UTC-11 — Samoa", "-11"),
    ("UTC-10 — Hawaii", "-10"),
    ("UTC-9  — Alaska", "-9"),
    ("UTC-8  — US Pacific / LA", "-8"),
    ("UTC-7  — US Mountain / Denver", "-7"),
    ("UTC-6  — US Central / Chicago", "-6"),
    ("UTC-5  — US Eastern / New York", "-5"),
    ("UTC-4  — Atlantic / Santiago", "-4"),
    ("UTC-3  — Buenos Aires / São Paulo", "-3"),
    ("UTC-2  — Mid-Atlantic", "-2"),
    ("UTC-1  — Azores / Cape Verde", "-1"),
    ("UTC+1  — Berlin / Paris / Rome", "+1"),
    ("UTC+2  — Cairo / Helsinki / Kyiv", "+2"),
    ("UTC+3  — Moscow / Istanbul / Nairobi", "+3"),
    ("UTC+4  — Dubai / Baku", "+4"),
    ("UTC+5  — Karachi / Tashkent", "+5"),
    ("UTC+5.5 — Mumbai / Delhi", "+5.5"),
    ("UTC+6  — Dhaka / Almaty", "+6"),
    ("UTC+7  — Bangkok / Jakarta", "+7"),
    ("UTC+8  — Shanghai / Singapore / Perth", "+8"),
    ("UTC+9  — Tokyo / Seoul", "+9"),
    ("UTC+9.5 — Adelaide", "+9.5"),
    ("UTC+10 — Sydney / Melbourne", "+10"),
    ("UTC+11 — Solomon Islands", "+11"),
    ("UTC+12 — Auckland / Fiji", "+12"),
    ("UTC+13 — Tonga / Samoa", "+13"),
]


class StampScreen(Screen):
    """Add EXIF metadata to Mavica JPEGs — camera model, date, timezone."""

    DEFAULT_CSS = """
    StampScreen VerticalScroll {
        height: 1fr;
    }
    #stamp-main {
        height: auto;
        min-height: 10;
    }
    #stamp-left {
        width: 1fr;
        min-width: 30;
    }
    #stamp-right {
        width: 40;
        min-width: 30;
        align: center top;
    }
    #stamp-right ImagePreview {
        height: auto;
        min-height: 12;
        content-align: center top;
        margin-bottom: 1;
    }
    StampScreen #results-table {
        height: auto;
        margin: 0;
    }
    StampScreen #camera-model-select {
        width: 1fr;
        height: auto;
    }
    StampScreen #date-select {
        width: 1fr;
        height: auto;
    }
    StampScreen #timezone-select {
        width: 1fr;
        height: auto;
    }
    StampScreen #exif-mode-select {
        width: 1fr;
        height: auto;
    }
    StampScreen #log {
        height: 2;
        max-height: 2;
        margin: 0;
        border: none;
    }
    """

    BINDINGS: ClassVar[list] = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
        Binding("f2", "stamp", "Tag", show=True),
        Binding("i", "open_source", "Open In", show=True),
    ]

    # Set by caller to pre-fill the source path
    _prefill_path: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static(
                "[bold #ffaa00]Stamp Metadata[/]  [dim]Add EXIF to bare Mavica JPEGs[/]\n",
                id="title-bar",
            )

            # Source row
            with Horizontal(classes="input-row"):
                yield Static("  [bold]Source[/] ", classes="row-label")
                yield Input(placeholder="Directory or JPEG file...", id="source-path")
                yield Button("Browse", id="btn-browse")
                yield Button("Open", id="btn-open-source")

            # Camera model row
            with Horizontal(classes="input-row"):
                yield Static("  [bold]Camera[/] ", classes="row-label")
                yield Select[str](
                    _CAMERA_OPTIONS,
                    prompt="Select camera model...",
                    id="camera-model-select",
                    allow_blank=True,
                    compact=True,
                )

            # Date row
            with Horizontal(classes="input-row"):
                yield Static("    [bold]Date[/] ", classes="row-label")
                yield Select[str](
                    [
                        ("From file (Mavica write time)", "auto"),
                        ("Today's date", "today"),
                        ("No date", "none"),
                    ],
                    value="auto",
                    id="date-select",
                    allow_blank=False,
                    compact=True,
                )
                yield Select[str](
                    _TIMEZONE_OPTIONS,
                    prompt="Timezone...",
                    id="timezone-select",
                    allow_blank=True,
                    compact=True,
                )

            # Description row
            with Horizontal(classes="input-row"):
                yield Static("    [bold]Desc[/] ", classes="row-label")
                yield Input(placeholder="Description / notes (optional)", id="desc-input")

            # Action + EXIF mode + progress on same row
            with Horizontal(classes="button-row"):
                yield Button("Tag All (F2)", variant="success", id="btn-stamp")
                yield Select[str](
                    [
                        ("Overwrite", "overwrite"),
                        ("Skip tagged", "skip"),
                        ("Merge", "merge"),
                    ],
                    value="overwrite",
                    id="exif-mode-select",
                    allow_blank=False,
                    compact=True,
                )
                yield ProgressBar(total=100, show_percentage=True, show_eta=True, id="progress")
            yield Static("", id="status")

            # Two-pane: file list on left, preview on right
            with Horizontal(id="stamp-main"):
                with Vertical(id="stamp-left"):
                    with Horizontal(classes="button-row"):
                        yield Button("All", variant="default", id="btn-select-all")
                        yield Button("None", variant="default", id="btn-select-none")
                        yield Static("  [dim]Space: toggle  Enter: details[/]")
                    yield DataTable(id="results-table")
                with Vertical(id="stamp-right"):
                    yield ImagePreview(id="preview")

            yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("", "Filename", "Size", "Current", "\u2192 New")
        table.cursor_type = "row"
        self._files: list[str] = []
        self._stamped_files: list[str] = []
        self._selected: set[int] = set()
        self._date_overrides: dict[int, str] = {}  # row index -> date string

        # Autodetect system timezone
        self._autoselect_timezone()

        if self._prefill_path:
            self.call_later(self._apply_prefill)
        else:
            self.call_later(self._apply_latest_import)

    def _find_latest_import(self) -> str | None:
        """Find the most recent import_* dir with JPEGs in mavica_out/."""
        import glob as globmod

        out_dir = "mavica_out"
        if not os.path.isdir(out_dir):
            self.notify("No mavica_out/ directory found", severity="warning")
            return None
        candidates = []
        for name in os.listdir(out_dir):
            path = os.path.join(out_dir, name)
            if os.path.isdir(path) and name.startswith("import_"):
                # Check for JPEGs
                jpegs = (
                    globmod.glob(os.path.join(path, "*.jpg"))
                    + globmod.glob(os.path.join(path, "*.JPG"))
                    + globmod.glob(os.path.join(path, "*.jpeg"))
                    + globmod.glob(os.path.join(path, "*.JPEG"))
                )
                if jpegs:
                    candidates.append((os.path.getmtime(path), path, len(jpegs)))
        if not candidates:
            self.notify("No imports with photos found in mavica_out/", severity="warning")
            return None
        candidates.sort(reverse=True)
        _, path, count = candidates[0]
        self.notify(
            f"Loaded {os.path.basename(path)} ({count} photo{'s' if count != 1 else ''})",
            severity="information",
        )
        return path

    def _autoselect_timezone(self) -> None:
        """Match the system timezone to the closest Select option."""
        try:
            from datetime import datetime

            local_offset = datetime.now(UTC).astimezone().utcoffset()
            offset_hours = local_offset.total_seconds() / 3600

            # Values are strings like "-5", "+9", "+5.5", "UTC"
            best = None
            best_diff = 999
            for _, value in _TIMEZONE_OPTIONS:
                try:
                    v = 0.0 if value == "UTC" else float(value)
                except ValueError:
                    continue
                diff = abs(v - offset_hours)
                if diff < best_diff:
                    best_diff = diff
                    best = value

            if best is not None and best_diff < 0.5:
                self.query_one("#timezone-select", Select).value = best
        except Exception:
            pass

    # ── Input events ──────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "source-path":
            path = event.value.strip()
            if path and (os.path.isdir(path) or os.path.isfile(path)):
                self._list_files(path)
        elif event.input.id == "desc-input":
            if self._files:
                self._refresh_file_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "source-path":
            path = event.value.strip()
            if path:
                self._list_files(path)

    def _list_files(self, source: str) -> None:
        """List JPEG files showing current EXIF and preview of new tags."""
        table = self.query_one("#results-table", DataTable)
        table.clear()
        self._files = []
        self._date_overrides = {}

        files = self._gather_jpegs(source)
        if not files:
            table.add_row("", "[dim]No JPEG files found[/]", "", "", "")
            return

        self._files = files
        self._selected = set(range(len(files)))  # Select all by default

        # Count non-JPEG files that were skipped
        src_dir = source if os.path.isdir(source) else os.path.dirname(source)
        skipped = 0
        if src_dir and os.path.isdir(src_dir):
            total_files = sum(
                1 for f in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, f))
            )
            skipped = total_files - len(files)

        # Auto-detect camera model
        self._autodetect_camera(files, source)

        self._refresh_file_list()

        # Count files with existing EXIF
        has_exif = sum(1 for f in files if self._file_has_exif(f))

        log = self.query_one("#log", RichLog)
        msg = f"[dim]{len(files)} JPEG(s)"
        if skipped > 0:
            msg += f"  ({skipped} non-JPEG file(s) skipped)"
        msg += "  \u2014  Enter on a row for details / edit date[/]"
        log.write(msg)

        if has_exif:
            self.notify(
                f"{has_exif} of {len(files)} file(s) already have EXIF tags",
                severity="information",
            )

        # Preview first file
        if files and files[0].lower().endswith((".jpg", ".jpeg")):
            self.query_one("#preview", ImagePreview).image_path = files[0]
        table.focus()

    def _apply_prefill(self) -> None:
        self.query_one("#source-path", Input).value = self._prefill_path

    def _apply_latest_import(self) -> None:
        latest = self._find_latest_import()
        if latest:
            self.query_one("#source-path", Input).value = latest

    @staticmethod
    def _file_has_exif(path: str) -> bool:
        """Check if a file has any camera EXIF tags."""
        try:
            from PIL import Image

            exif = Image.open(path).getexif()
            return bool(exif and (exif.get(0x010F) or exif.get(0x0110)))
        except Exception:
            return False

    def _autodetect_camera(self, jpegs: list[str], source: str) -> None:
        """Try to auto-detect camera model and pre-select it."""
        from mavica_tools.camera_detect import detect_camera

        # Include all files in the source dir for companion file detection
        all_files = list(jpegs)
        src_dir = source if os.path.isdir(source) else os.path.dirname(source)
        if src_dir and os.path.isdir(src_dir):
            for f in os.listdir(src_dir):
                full = os.path.join(src_dir, f)
                if full not in all_files:
                    all_files.append(full)

        result = detect_camera(all_files)

        if result.model:
            select = self.query_one("#camera-model-select", Select)
            select.value = result.model

        # Toast with explanation
        if result.confidence == "exact" or result.confidence == "likely":
            self.notify(result.reason, severity="information")
        elif result.confidence == "guess":
            self.notify(result.reason, severity="warning")
        else:
            self.notify(result.reason, severity="warning")

    def _get_current_exif(self, path: str) -> str:
        """Read existing EXIF summary from a file."""
        try:
            from PIL import Image

            img = Image.open(path)
            exif = img.getexif()
            if not exif:
                return "[dim]No EXIF[/]"
            parts: list[str] = []
            make = str(exif.get(0x010F, "") or "")
            model = str(exif.get(0x0110, "") or "")
            date = str(exif.get(0x0132, "") or "")
            if model:
                parts.append(model)
            elif make:
                parts.append(make)
            if date:
                parts.append(date)
            return " | ".join(parts) if parts else "[dim]EXIF (no camera)[/]"
        except Exception:
            return "[dim]No EXIF[/]"

    def _build_new_preview(self, row: int) -> str:
        """Build a preview string of what will be tagged for this file."""
        # Check EXIF mode vs file state
        exif_mode = self.query_one("#exif-mode-select", Select).value
        if exif_mode is Select.BLANK:
            exif_mode = "overwrite"
        has_exif = self._file_has_exif(self._files[row])

        if has_exif and exif_mode == "skip":
            return "[dim]skip (has EXIF)[/]"

        model = self._get_camera_model()
        date_sel = self.query_one("#date-select", Select).value
        date_val = date_sel if date_sel is not Select.BLANK else "auto"

        parts: list[str] = []
        if model:
            spec = MAVICA_SPECS.get(model)
            parts.append(spec["model"] if spec else str(model))

        if row in self._date_overrides:
            parts.append(f"[bold #ffaa00]{self._date_overrides[row]}[/]")
        elif date_val == "auto":
            from mavica_tools.utils import get_photo_date

            d = get_photo_date(self._files[row])
            parts.append(d if d else "file date")
        elif date_val == "today":
            from datetime import date as _date

            parts.append(_date.today().isoformat())

        desc = self.query_one("#desc-input", Input).value.strip()
        if desc:
            parts.append(f'"{desc[:20]}"')

        if not parts:
            return "[dim]no changes[/]"

        prefix = ""
        if has_exif and exif_mode == "merge":
            prefix = "[dim]merge:[/] "
        return prefix + " | ".join(parts)

    def _refresh_file_list(self) -> None:
        """Rebuild the file table with selection state and previews."""
        table = self.query_one("#results-table", DataTable)
        cursor = table.cursor_row
        table.clear()

        for i, f in enumerate(self._files):
            selected = i in self._selected
            name = os.path.basename(f)
            try:
                size_kb = os.path.getsize(f) / 1024
                size_str = f"{size_kb:.0f}KB"
            except OSError:
                size_str = "?"

            thumb = inline_thumbnail(f, width=2) or ""
            sel = "[green]\u25cf[/]" if selected else "[dim]\u25cb[/]"
            marker = f"{sel} {thumb}" if thumb else sel
            current = self._get_current_exif(f)

            if selected:
                new = self._build_new_preview(i)
            else:
                name = f"[dim]{name}[/]"
                size_str = f"[dim]{size_str}[/]"
                current = f"[dim]{current}[/]" if "[dim]" not in current else current
                new = "[dim]skip[/]"

            table.add_row(marker, name, size_str, current, new)

        if cursor is not None and cursor < len(self._files):
            table.move_cursor(row=cursor)

        self._update_tag_label()

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

    def _update_tag_label(self) -> None:
        n = len(self._selected)
        btn = self.query_one("#btn-stamp", Button)
        btn.label = f"Tag {n} (F2)" if n else "Tag All (F2)"

    def on_select_changed(self, event: Select.Changed) -> None:
        """Refresh preview column when camera/date/timezone changes."""
        if (
            event.select.id
            in ("camera-model-select", "date-select", "timezone-select", "exif-mode-select")
            and self._files
        ):
            self._refresh_file_list()

    def _gather_jpegs(self, source: str) -> list[str]:
        """Gather JPEG files from a path."""
        files = []
        if os.path.isdir(source):
            for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
                files.extend(globmod.glob(os.path.join(source, ext)))
        elif os.path.isfile(source):
            files.append(source)
        else:
            files.extend(globmod.glob(source))
            files = [f for f in files if f.lower().endswith((".jpg", ".jpeg"))]

        # Deduplicate
        seen: set[str] = set()
        deduped: list[str] = []
        for f in files:
            key = os.path.normcase(f)
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        return sorted(deduped)

    # ── Button handlers ───────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-open-source":
            self.action_open_source()
        elif event.button.id == "btn-stamp":
            self.action_stamp()
        elif event.button.id == "btn-select-all":
            self._toggle_all(True)
        elif event.button.id == "btn-select-none":
            self._toggle_all(False)

    def on_key(self, event) -> None:
        """Space to toggle selection on focused row."""
        table = self.query_one("#results-table", DataTable)
        if not table.has_focus or not self._files:
            return
        if event.key == "space":
            event.prevent_default()
            event.stop()
            self._toggle_row(table.cursor_row)

    # ── Actions / keybindings ─────────────────────────────────────

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#source-path", Input).value = path

        self.app.push_screen(
            FilePicker(
                extensions=(".jpg", ".jpeg"),
                title="Select JPEG files or directory",
                select_directory=True,
            ),
            on_selected,
        )

    def action_open_source(self) -> None:
        from mavica_tools.utils import open_directory

        source = self.query_one("#source-path", Input).value.strip()
        if source:
            d = source if os.path.isdir(source) else os.path.dirname(source)
            d = os.path.abspath(d) if d else ""
            if d and os.path.isdir(d):
                open_directory(d)

    def action_stamp(self) -> None:
        self._start_stamp()

    # ── Preview ───────────────────────────────────────────────────

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None:
            return
        if self._files and event.cursor_row < len(self._files):
            path = self._files[event.cursor_row]
            if path.lower().endswith((".jpg", ".jpeg")):
                self.query_one("#preview", ImagePreview).image_path = path

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a row opens date editor."""
        if self._files and event.cursor_row < len(self._files):
            self._edit_date(event.cursor_row)

    def _edit_date(self, row: int) -> None:
        """Open a detail modal for this file — shows all fields, allows date edit."""
        from textual.screen import ModalScreen

        filepath = self._files[row]
        name = os.path.basename(filepath)
        current_date = self._date_overrides.get(row, "")
        if not current_date:
            from mavica_tools.utils import get_photo_date

            current_date = get_photo_date(filepath) or ""

        # Build detail info
        current_exif = self._get_current_exif(filepath)
        self._build_new_preview(row)  # triggers side-effect
        try:
            size_str = f"{os.path.getsize(filepath):,} bytes"
        except OSError:
            size_str = "?"

        # Build EXIF fields that will be written
        model = self._get_camera_model()
        exif_lines: list[str] = []

        # Resolve date for this file
        date_sel = self.query_one("#date-select", Select).value
        date_val = date_sel if date_sel is not Select.BLANK else "auto"
        if row in self._date_overrides:
            date_preview = self._date_overrides[row]
        elif date_val == "auto":
            from mavica_tools.utils import get_photo_timestamp

            ts = get_photo_timestamp(filepath)
            if ts:
                date_preview = ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                # Fall back to file mtime
                from datetime import datetime as _dt

                mtime = os.path.getmtime(filepath)
                date_preview = _dt.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        elif date_val == "today":
            from datetime import datetime as _dt

            date_preview = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            date_preview = None

        if model:
            from mavica_tools.mavica_db import MODELS

            m = MODELS.get(model)
            if m:
                from fractions import Fraction

                fl = Fraction(m.focal_length_mm).limit_denominator(100)
                ap = Fraction(m.aperture_max).limit_denominator(100)
                exif_lines = [
                    "  Make             [bold]SONY[/]",
                    f"  Model            [bold]{m.model.upper()}[/]",
                    f"  FocalLength      [bold]{fl} mm[/]",
                    f"  FocalLengthIn35  [bold]{m.focal_length_35mm} mm[/]",
                    f"  FNumber          [bold]f/{ap}[/]",
                    f"  MaxApertureValue [bold]f/{ap}[/]",
                    f"  ISOSpeedRatings  [bold]{m.iso}[/]",
                    f"  PixelXDimension  [bold]{m.resolution[0]}[/]",
                    f"  PixelYDimension  [bold]{m.resolution[1]}[/]",
                    "  ColorSpace       [bold]sRGB[/]",
                    "  SensingMethod    [bold]One-chip color area[/]",
                    "  ExposureProgram  [bold]Auto[/]",
                    "  MeteringMode     [bold]Multi-segment[/]",
                    f"  Flash            [bold]{'Has flash' if m.flash else 'No flash'}[/]",
                ]
        if date_preview:
            exif_lines.append(f"  DateTime         [bold]{date_preview}[/]")
            exif_lines.append(f"  DateTimeOriginal [bold]{date_preview}[/]")

        desc = self.query_one("#desc-input", Input).value.strip()
        if desc:
            exif_lines.append(f"  ImageDescription [bold]{desc}[/]")

        class DetailScreen(ModalScreen[str]):
            DEFAULT_CSS = """
            DetailScreen { align: center middle; }
            #detail-outer {
                width: 60;
                height: auto;
                max-height: 80%;
                border: thick #ffaa00;
                background: #0a0a0a;
                padding: 0 2;
            }
            #detail-scroll {
                height: 1fr;
                max-height: 100%;
                padding: 1 0;
            }
            #detail-footer {
                height: auto;
                dock: bottom;
                padding: 0 0 1 0;
            }
            """
            BINDINGS: ClassVar[list] = [("escape", "cancel", "Cancel")]

            def compose(self_inner):
                with Vertical(id="detail-outer"):
                    with VerticalScroll(id="detail-scroll"):
                        yield Static(f"[bold #ffaa00]{name}[/]  [dim]{size_str}[/]\n")
                        yield Static(f"  [dim]Current:[/]  {current_exif}\n")
                        if exif_lines:
                            yield Static(
                                f"  [bold #ffaa00]EXIF tags to write ({len(exif_lines)}):[/]"
                            )
                            for line in exif_lines:
                                yield Static(line)
                            yield Static("")
                        yield Static("  [bold]Date override:[/]  [dim](blank = use default)[/]")
                        yield Input(
                            value=current_date,
                            placeholder="YYYY-MM-DD or YYYY-MM-DD HH:MM:SS",
                            id="date-edit-input",
                        )
                    with Horizontal(id="detail-footer"):
                        yield Button("Save", variant="success", id="btn-detail-save")
                        yield Button("Cancel", variant="default", id="btn-detail-cancel")

            def on_input_submitted(self_inner, event):
                self_inner.dismiss(event.value.strip())

            def on_button_pressed(self_inner, event):
                if event.button.id == "btn-detail-save":
                    val = self_inner.query_one("#date-edit-input", Input).value.strip()
                    self_inner.dismiss(val)
                elif event.button.id == "btn-detail-cancel":
                    self_inner.dismiss(None)

            def action_cancel(self_inner):
                self_inner.dismiss(None)

        def on_result(value: str | None) -> None:
            if value is None:
                return  # cancelled
            if value:
                self._date_overrides[row] = value
            elif row in self._date_overrides:
                del self._date_overrides[row]  # cleared override
            self._refresh_file_list()

        self.app.push_screen(DetailScreen(), on_result)

    # ── Stamp ─────────────────────────────────────────────────────

    def _get_camera_model(self) -> str | None:
        val = self.query_one("#camera-model-select", Select).value
        if val is Select.BLANK:
            return None
        return val or None

    def _get_timezone(self) -> str | None:
        val = self.query_one("#timezone-select", Select).value
        if val is Select.BLANK:
            return None
        return val or None

    def _start_stamp(self) -> None:
        source = self.query_one("#source-path", Input).value.strip()
        if not source and not self._files:
            self.notify("Enter a source path", severity="warning")
            return

        model = self._get_camera_model()
        date_val = self.query_one("#date-select", Select).value
        if date_val == "none" or date_val is Select.BLANK:
            date = None
        elif date_val == "today":
            from datetime import date as _date

            date = _date.today().strftime("%Y-%m-%d")
        else:
            date = "auto"
        desc = self.query_one("#desc-input", Input).value.strip() or None
        tz = self._get_timezone()
        exif_mode_val = self.query_one("#exif-mode-select", Select).value
        exif_mode = exif_mode_val if exif_mode_val is not Select.BLANK else "overwrite"

        btn = self.query_one("#btn-stamp", Button)
        btn.disabled = True
        btn.label = "Tagging\u2026"
        self.run_worker(
            self._do_stamp(source, model, date, desc, tz, exif_mode),
            exclusive=True,
        )

    async def _do_stamp(
        self,
        source: str,
        model: str | None,
        date: str | None,
        desc: str | None,
        tz: str | None,
        exif_mode: str = "overwrite",
    ) -> None:
        worker = get_current_worker()
        table = self.query_one("#results-table", DataTable)
        log = self.query_one("#log", RichLog)
        progress = self.query_one("#progress", ProgressBar)
        status = self.query_one("#status", Static)
        table.clear()

        # Gather files
        files = self._files if self._files else self._gather_jpegs(source)
        files.sort()

        if not files:
            log.write("[red]No JPEG files found.[/]")
            self._reset_button()
            return

        # Apply timezone offset to date if specified
        effective_date = date
        if tz and date and date.lower() != "auto":
            # Timezone is stored for reference but date is passed as-is
            # (stamp_jpeg handles the date string directly)
            pass

        # Only tag selected files
        to_tag = [(i, files[i]) for i in sorted(self._selected) if i < len(files)]
        if not to_tag:
            log.write("[red]No files selected.[/]")
            self._reset_button()
            return

        progress.update(total=len(to_tag), progress=0)
        log.write(f"Tagging {len(to_tag)} file(s)...")
        if model:
            spec = MAVICA_SPECS.get(model)
            model_name = spec["model"] if spec else model
            log.write(f"  Camera: [bold]{model_name}[/]")
        if tz:
            log.write(f"  Timezone: [bold]{tz}[/]")

        success = fail = skipped = 0
        self._stamped_files = []

        for progress_idx, (i, filepath) in enumerate(to_tag):
            if worker.is_cancelled:
                log.write("[yellow]Cancelled.[/]")
                self._reset_button()
                return

            name = os.path.basename(filepath)
            has_exif = self._file_has_exif(filepath)

            # Handle EXIF mode
            if has_exif and exif_mode == "skip":
                skipped += 1
                table.add_row("[dim]SKIP[/]", name, "", "[dim]already tagged[/]", "")
                progress.update(progress=progress_idx + 1)
                continue

            # For merge mode, only stamp if missing camera tags
            if has_exif and exif_mode == "merge":
                # Only write tags that are missing
                # stamp_jpeg always overwrites, so skip if camera already set
                try:
                    from PIL import Image

                    existing = Image.open(filepath).getexif()
                    if existing.get(0x0110) and model:
                        # Already has model — skip camera tags, only add missing date/desc
                        file_date = self._date_overrides.get(i, effective_date)
                        existing_date = existing.get(0x0132)
                        if existing_date and not file_date:
                            skipped += 1
                            table.add_row("[dim]SKIP[/]", name, "", "[dim]already tagged[/]", "")
                            progress.update(progress=progress_idx + 1)
                            continue
                        # Has model but missing date — stamp date only
                        ok, result_path, msg = stamp_jpeg(
                            filepath,
                            None,
                            model=None,
                            date=file_date,
                            description=desc,
                            overwrite=True,
                        )
                        if ok:
                            success += 1
                            self._stamped_files.append(filepath)
                            try:
                                sz = f"{os.path.getsize(filepath) / 1024:.0f}KB"
                            except OSError:
                                sz = "?"
                            table.add_row("[#ffaa00]MERGE[/]", name, sz, "", msg)
                        else:
                            fail += 1
                            table.add_row("[red]FAIL[/]", name, "", "", msg)
                        progress.update(progress=progress_idx + 1)
                        continue
                except Exception:
                    pass

            # Use per-file date override if set, otherwise global date
            file_date = self._date_overrides.get(i, effective_date)

            ok, result_path, msg = stamp_jpeg(
                filepath,
                None,
                model=model,
                date=file_date,
                description=desc,
                overwrite=True,
            )

            if ok:
                success += 1
                self._stamped_files.append(filepath)
                try:
                    sz = f"{os.path.getsize(filepath) / 1024:.0f}KB"
                except OSError:
                    sz = "?"
                table.add_row("[green]OK[/]", name, sz, "", msg)
            else:
                fail += 1
                table.add_row("[red]FAIL[/]", name, "", "", msg)

            progress.update(progress=progress_idx + 1)

        parts = [f"[green]{success} tagged[/]"]
        if fail:
            parts.append(f"[red]{fail} failed[/]")
        if skipped:
            parts.append(f"[dim]{skipped} skipped[/]")
        summary = ", ".join(parts)
        status.update(f"  [bold #33ff33]Done![/] {summary}")
        log.write(f"\n[bold]Results:[/] {summary}")
        if success:
            log.write(
                "[bold #33ff33]Next:[/] Use [bold]Add GPS Location[/] to geotag photos with a GPX track."
            )
        self._reset_button()

    def _reset_button(self) -> None:
        btn = self.query_one("#btn-stamp", Button)
        btn.disabled = False
        btn.label = "Tag All (F2)"
