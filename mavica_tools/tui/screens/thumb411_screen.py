"""Thumbnail .411 viewer/converter screen."""

import glob as globmod
import os
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Select, Static
from textual.worker import get_current_worker

from mavica_tools.thumb411 import convert_411, decode_411_to_image
from mavica_tools.tui.widgets.file_picker import FilePicker
from mavica_tools.tui.widgets.image_preview import ImagePreview


class Thumb411Screen(Screen):
    """View and convert Mavica .411 thumbnail files."""

    DEFAULT_CSS = """
    #thumb-main {
        height: 1fr;
    }
    #thumb-left {
        width: 1fr;
        min-width: 30;
    }
    #thumb-right {
        width: 40;
        min-width: 30;
        align: center top;
    }
    #thumb-right ImagePreview {
        height: 1fr;
        min-height: 5;
        content-align: center top;
        margin-bottom: 1;
    }
    Thumb411Screen #output-format {
        width: 18;
        height: auto;
    }
    Thumb411Screen #results-table {
        height: 1fr;
        max-height: 100%;
        margin: 0;
    }
    Thumb411Screen #log {
        height: 2;
        max-height: 2;
        margin: 0;
        border: none;
    }
    """

    BINDINGS: ClassVar[list] = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
        Binding("f2", "convert", "Convert", show=True),
        Binding("i", "open_input", "Open In", show=True),
        Binding("o", "open_output", "Open Out", show=True),
    ]

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical

        yield Header()
        yield Static(
            "[bold #ffaa00].411 Thumbnail Viewer[/]  [dim]Decode Mavica camera thumbnails[/]",
            id="title-bar",
        )

        # Source row
        with Horizontal(classes="input-row"):
            yield Static("  [bold]In[/] ", classes="row-label")
            yield Input(
                value="mavica_out/photos", placeholder=".411 file or directory...", id="source-path"
            )
            yield Button("Browse", id="btn-browse")
            yield Button("Open", id="btn-open-source")

        # Output row
        with Horizontal(classes="input-row"):
            yield Static(" [bold]Out[/] ", classes="row-label")
            yield Input(
                value="mavica_out/thumbnails", placeholder="Output directory", id="output-dir"
            )
            yield Button("Browse", id="btn-browse-out")
            yield Button("Open", id="btn-open-folder")
            yield Select[str](
                [("PNG", "png"), ("JPEG", "jpg"), ("GIF", "gif"), ("BMP", "bmp")],
                value="png",
                id="output-format",
                allow_blank=False,
                compact=True,
            )
            yield Button("Convert", variant="success", id="btn-convert")

        # Two-column layout: file list on left, preview on right
        with Horizontal(id="thumb-main"):
            with Vertical(id="thumb-left"):
                with Horizontal(classes="button-row"):
                    yield Button("All", variant="default", id="btn-select-all")
                    yield Button("None", variant="default", id="btn-select-none")
                    yield Static("  [dim]Space/Enter to toggle[/]")
                yield DataTable(id="results-table")
            with Vertical(id="thumb-right"):
                yield ImagePreview(id="preview-original")

        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Sel", "Filename", "Size", "Status")
        table.cursor_type = "row"
        self._results = []
        self._selected = set()
        table.add_row("", "[dim]Browse for a directory with .411 files[/]", "", "")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "source-path":
            path = event.value.strip()
            # Only list when the path is a valid directory or file — avoid
            # errors from partial paths typed mid-keystroke
            if path and (os.path.isdir(path) or os.path.isfile(path)):
                self._list_files(path)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "source-path":
            self._list_files(event.value.strip())

    def action_convert(self) -> None:
        self._start_convert()

    def action_open_input(self) -> None:
        from mavica_tools.utils import open_directory

        source = self.query_one("#source-path", Input).value.strip()
        if source:
            d = source if os.path.isdir(source) else os.path.dirname(source)
            d = os.path.abspath(d) if d else ""
            if d and os.path.isdir(d):
                open_directory(d)

    def action_open_output(self) -> None:
        from mavica_tools.utils import open_directory

        output_dir = os.path.abspath(self.query_one("#output-dir", Input).value.strip())
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            open_directory(output_dir)

    def on_key(self, event) -> None:
        """Handle space/enter for toggle when table is focused."""
        table = self.query_one("#results-table", DataTable)
        if not table.has_focus or not self._results:
            return
        if event.key in ("space",):
            event.prevent_default()
            event.stop()
            self._toggle_row(table.cursor_row)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Refresh preview when format changes."""
        if event.select.id == "output-format":
            self._refresh_current_preview()

    def _refresh_current_preview(self) -> None:
        """Re-render preview for the currently highlighted file."""
        table = self.query_one("#results-table", DataTable)
        idx = table.cursor_row
        if self._results and idx is not None and idx < len(self._results):
            src, _ = self._results[idx]
            self._show_411_preview(src)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from mavica_tools.utils import open_directory

        if event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-browse-out":
            self._browse_output()
        elif event.button.id == "btn-convert":
            self._start_convert()
        elif event.button.id == "btn-select-all":
            self._toggle_all(True)
        elif event.button.id == "btn-select-none":
            self._toggle_all(False)
        elif event.button.id == "btn-open-source":
            source = self.query_one("#source-path", Input).value.strip()
            if source:
                d = source if os.path.isdir(source) else os.path.dirname(source)
                d = os.path.abspath(d) if d else ""
                if d and os.path.isdir(d):
                    open_directory(d)
                else:
                    self.notify("Source directory not found", severity="warning")
        elif event.button.id == "btn-open-folder":
            output_dir = os.path.abspath(self.query_one("#output-dir", Input).value.strip())
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                open_directory(output_dir)

    def _list_files(self, source: str) -> None:
        """List candidate .411 files in the results table (before conversion)."""
        table = self.query_one("#results-table", DataTable)
        table.clear()
        self._results = []
        self._selected = set()

        self._update_convert_label()
        if not source:
            table.add_row("", "[dim]Browse for a directory with .411 files[/]", "", "")
            return

        files = self._gather_files(source)
        if not files:
            table.add_row("", "[dim]No .411 files found in this location[/]", "", "")
            return

        for i, filepath in enumerate(files):
            name = os.path.basename(filepath)
            try:
                size = os.path.getsize(filepath)
                size_str = f"{size:,} B"
            except OSError:
                size_str = "?"
            self._selected.add(i)  # Select all by default
            table.add_row("[green]\u25cf[/]", name, size_str, "[dim]--[/]")
            self._results.append((filepath, None))

        log = self.query_one("#log", RichLog)
        n = len(files)
        log.write(f"Found {n} .411 {'file' if n == 1 else 'files'}.")

        # Auto-preview the first file and focus the table
        self._show_411_preview(files[0])
        self._update_convert_label()
        table.focus()

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#source-path", Input).value = path

        self.app.push_screen(
            FilePicker(
                extensions=(".411",),
                title="Select .411 files or directory",
                select_directory=True,
            ),
            on_selected,
        )

    def _browse_output(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#output-dir", Input).value = path

        self.app.push_screen(
            FilePicker(
                title="Select output directory",
                select_directory=True,
                allow_new_folder=True,
            ),
            on_selected,
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None:
            return
        if self._results and event.cursor_row < len(self._results):
            src, _out = self._results[event.cursor_row]
            self._show_411_preview(src)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Toggle selection on Enter."""
        self._toggle_row(event.cursor_row)

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Toggle selection on cell click."""
        self._toggle_row(event.coordinate.row)

    def _toggle_row(self, idx: int) -> None:
        if idx >= len(self._results):
            return
        if idx in self._selected:
            self._selected.discard(idx)
        else:
            self._selected.add(idx)
        self._refresh_table_selection()

    def _refresh_table_selection(self) -> None:
        """Update the checkbox column to reflect current selection."""
        table = self.query_one("#results-table", DataTable)
        rows_data = []
        for i, (filepath, out) in enumerate(self._results):
            name = os.path.basename(filepath)
            try:
                size = os.path.getsize(filepath)
                size_str = f"{size:,} B"
            except OSError:
                size_str = "?"
            selected = i in self._selected
            sel = "[green]\u25cf[/]" if selected else "[dim]\u25cb[/]"
            name_styled = f"[bold]{name}[/]" if selected else f"[dim]{name}[/]"
            size_styled = size_str if selected else f"[dim]{size_str}[/]"
            status = f"[green]{os.path.basename(out)}[/]" if out else "[dim]--[/]"
            rows_data.append((sel, name_styled, size_styled, status))

        cursor = table.cursor_row
        table.clear()
        for row in rows_data:
            table.add_row(*row)
        # Restore cursor position
        if cursor < len(rows_data):
            table.move_cursor(row=cursor)
        self._update_convert_label()

    def _update_convert_label(self) -> None:
        n = len(self._selected)
        self.query_one("#btn-convert", Button).label = (
            f"Convert {n} {'file' if n == 1 else 'files'}" if n else "Convert"
        )

    def _toggle_all(self, select: bool) -> None:
        if select:
            self._selected = set(range(len(self._results)))
        else:
            self._selected = set()
        self._refresh_table_selection()
        count = len(self._selected)
        self.query_one("#log", RichLog).write(
            f"{'Selected' if select else 'Deselected'} all — {count} {'file' if count == 1 else 'files'}"
        )

    def _show_411_preview(self, path: str) -> None:
        """Decode a .411 file and show it directly in the preview pane."""
        try:
            img = decode_411_to_image(path)
            # Nearest neighbor for upscaling — preserves the blocky pixel art look of 64x48 thumbnails
            upscaled = img.resize((256, 192), resample=0)
            source_name = os.path.basename(path)
            fmt = self.query_one("#output-format", Select).value or "png"
            output_dir = self.query_one("#output-dir", Input).value.strip() or "thumbnails"
            base = os.path.splitext(source_name)[0]
            out_path = os.path.join(output_dir, f"{base}.{fmt}")
            label = f"{source_name}\n\u2192 {out_path}"
            self.query_one("#preview-original", ImagePreview).set_pil_image(upscaled, label)
        except Exception:
            self.query_one("#preview-original", ImagePreview).image_path = ""

    def _preview_source(self) -> None:
        """Preview the source .411 without converting."""
        source = self.query_one("#source-path", Input).value.strip()
        if not source:
            self.notify("Enter a source path", severity="warning")
            return
        files = self._gather_files(source)
        if not files:
            self.query_one("#log", RichLog).write("[red]No .411 files found.[/]")
            return
        self._show_411_preview(files[0])

    def _gather_files(self, source: str) -> list[str]:
        """Gather .411 files from a path."""
        files = []
        if os.path.isdir(source):
            files.extend(globmod.glob(os.path.join(source, "*.411")))
            files.extend(globmod.glob(os.path.join(source, "*.411")))
        elif os.path.isfile(source) and source.lower().endswith(".411"):
            files.append(source)
        else:
            files.extend(globmod.glob(source))
            files = [f for f in files if f.lower().endswith(".411")]

        # Deduplicate
        seen = set()
        deduped = []
        for f in files:
            key = os.path.normcase(f)
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        return sorted(deduped)

    def _start_convert(self) -> None:
        source = self.query_one("#source-path", Input).value.strip()
        if not source:
            self.notify("Enter a source path", severity="warning")
            return
        btn = self.query_one("#btn-convert", Button)
        btn.disabled = True
        btn.label = "Converting..."
        self.run_worker(self._convert_files(source), exclusive=True)

    async def _convert_files(self, source: str) -> None:
        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        output_dir = self.query_one("#output-dir", Input).value.strip() or "thumbnails"
        fmt = self.query_one("#output-format", Select).value or "png"

        # Only convert selected files
        to_convert = [
            (i, self._results[i][0]) for i in sorted(self._selected) if i < len(self._results)
        ]
        if not to_convert:
            log.write("[red]No files selected.[/]")
            self._reset_button()
            return

        os.makedirs(output_dir, exist_ok=True)
        n = len(to_convert)
        log.write(f"Converting {n} .411 {'file' if n == 1 else 'files'} to {fmt.upper()}...")

        success = fail = 0

        for _progress_idx, (i, filepath) in enumerate(to_convert):
            if worker.is_cancelled:
                log.write("[yellow]Cancelled.[/]")
                self._reset_button()
                return

            name = os.path.basename(filepath)
            base, _ = os.path.splitext(name)
            out_path = os.path.join(output_dir, f"{base}.{fmt}")

            try:
                convert_411(filepath, out_path, fmt)
                self._results[i] = (filepath, out_path)
                success += 1
            except Exception:
                self._results[i] = (filepath, None)
                fail += 1

        self._refresh_table_selection()
        log.write(f"\n[bold]Results:[/] [green]{success} converted[/], [red]{fail} failed[/]")
        if success:
            log.write(f"Output: {output_dir}/")
            log.write("[dim]Select a row to preview original vs converted.[/]")
            self.query_one("#btn-open-folder", Button).disabled = False

        self._reset_button()

    def _reset_button(self) -> None:
        btn = self.query_one("#btn-convert", Button)
        btn.disabled = False
        self._update_convert_label()
