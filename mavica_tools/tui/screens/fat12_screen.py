"""FAT12 browser screen — view and extract files with original names."""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, DataTable, RichLog
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.tui.widgets.file_picker import FilePicker
from mavica_tools.tui.widgets.image_preview import ImagePreview


class Fat12Screen(Screen):
    """Browse and extract files from Mavica FAT12 disk images."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
    ]

    _prefill_image: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]FAT12 Browser[/]  "
            "[dim]View files with original Mavica names[/]\n",
            id="title-bar",
        )
        with Horizontal(classes="input-row"):
            yield Input(placeholder="Path to disk image (.img)...", id="image-path")
            yield Button("Browse", id="btn-browse")
        with Horizontal(classes="button-row"):
            yield Button("List Files", variant="success", id="btn-list")
            yield Button("Extract All", variant="warning", id="btn-extract", disabled=True)
            yield Button("Include Deleted", variant="default", id="btn-deleted")
        yield DataTable(id="results-table")
        yield ImagePreview(id="preview")
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Status", "Filename", "Size", "Date", "Time")
        table.cursor_type = "row"
        self._include_deleted = False
        self._files_data = []

        if self._prefill_image:
            self.query_one("#image-path", Input).value = self._prefill_image
            self._prefill_image = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-list":
            self._list_files()
        elif event.button.id == "btn-extract":
            self._extract_files()
        elif event.button.id == "btn-deleted":
            self._include_deleted = not self._include_deleted
            btn = self.query_one("#btn-deleted", Button)
            btn.label = "Deleted: ON" if self._include_deleted else "Include Deleted"
            if self._files_data:
                self._list_files()  # Refresh

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#image-path", Input).value = path
        self.app.push_screen(
            FilePicker(extensions=(".img", ".bin", ".raw"), title="Select disk image"),
            on_selected,
        )

    def _list_files(self) -> None:
        path = self.query_one("#image-path", Input).value.strip()
        if not path:
            self.notify("Enter a disk image path", severity="warning")
            return
        if not os.path.isfile(path):
            self.notify("File not found", severity="error")
            return
        self.run_worker(self._do_list(path), exclusive=True)

    async def _do_list(self, path: str) -> None:
        from mavica_tools.fat12 import list_files

        table = self.query_one("#results-table", DataTable)
        log = self.query_one("#log", RichLog)
        table.clear()

        try:
            files = list_files(path, include_deleted=self._include_deleted)
        except Exception as e:
            log.write(f"[red]FAT12 parse error: {e}[/]")
            log.write("[dim]The filesystem may be damaged. Try 'Carve JPEGs' instead.[/]")
            return

        self._files_data = files

        if not files:
            log.write("[dim]No files found on disk.[/]")
            return

        for f in files:
            status = "[red]DEL[/]" if f.is_deleted else "[green]OK[/]"
            table.add_row(status, f.name, f"{f.size:,}", f.date_str, f.time_str)

        total = sum(f.size for f in files if not f.is_deleted)
        log.write(f"{len(files)} file(s), {total:,} bytes total")
        self.query_one("#btn-extract", Button).disabled = False

    def _extract_files(self) -> None:
        path = self.query_one("#image-path", Input).value.strip()
        if not path:
            return
        self.run_worker(self._do_extract(path), exclusive=True)

    async def _do_extract(self, path: str) -> None:
        from mavica_tools.fat12 import extract_with_names

        log = self.query_one("#log", RichLog)
        output_dir = "extracted"

        try:
            results = extract_with_names(path, output_dir, include_deleted=self._include_deleted)
            for name, out_path, size, deleted in results:
                prefix = "[red]DEL[/] " if deleted else ""
                log.write(f"  {prefix}{name} -> {out_path} ({size:,} bytes)")
            log.write(f"\n[green]{len(results)} file(s) extracted to {output_dir}/[/]")
        except Exception as e:
            log.write(f"[red]Extraction error: {e}[/]")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Preview extracted images if available."""
        if self._files_data and event.cursor_row < len(self._files_data):
            f = self._files_data[event.cursor_row]
            # Check if the file was extracted
            possible_path = os.path.join("extracted", f.name)
            if os.path.exists(possible_path):
                self.query_one("#preview", ImagePreview).image_path = possible_path
