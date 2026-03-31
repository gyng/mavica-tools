"""Export screen — organize, rename, watermark, contact sheets."""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog, ProgressBar, Checkbox
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.tui.widgets.file_picker import FilePicker
from mavica_tools.tui.widgets.image_preview import ImagePreview


class ExportScreen(Screen):
    """Export recovered images with organization and effects."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
    ]

    _prefill_path: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Photo Export[/]  "
            "[dim]Organize, rename, watermark, contact sheets[/]\n",
            id="title-bar",
        )
        yield Static("  [bold]Source[/]")
        with Horizontal(classes="input-row"):
            yield Input(placeholder="Source directory...", id="source-path")
            yield Button("Browse", id="btn-browse")
        yield Static("  [bold]Output Dir[/]  /  [bold]Organize[/]")
        with Horizontal(classes="input-row"):
            yield Input(value="mavica_out/exported", placeholder="Output directory", id="output-dir")
            yield Input(value="flat", placeholder="Organize: flat/date/year", id="organize")
        yield Static("  [bold]Watermark[/]  /  [bold]Resize[/]")
        with Horizontal(classes="input-row"):
            yield Input(placeholder="Watermark text (e.g., Shot on Mavica FD7)", id="watermark")
            yield Input(placeholder="Resize (e.g., 1280x960)", id="resize")
        with Horizontal(classes="button-row"):
            yield Button("Export", variant="success", id="btn-export")
            yield Button("Contact Sheet", variant="warning", id="btn-contact")
            yield Button("Export + All Effects", variant="default", id="btn-full")
        yield ProgressBar(total=100, show_percentage=True, show_eta=True, id="progress")
        yield ImagePreview(id="preview")
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        if self._prefill_path:
            self.query_one("#source-path", Input).value = self._prefill_path

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-export":
            self._run_export(contact_sheet=False, border=False)
        elif event.button.id == "btn-contact":
            self._run_export(contact_sheet=True, border=False)
        elif event.button.id == "btn-full":
            self._run_export(contact_sheet=True, border=True)

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#source-path", Input).value = path
        self.app.push_screen(
            FilePicker(title="Select image directory", select_directory=True),
            on_selected,
        )

    def _run_export(self, contact_sheet: bool, border: bool) -> None:
        source = self.query_one("#source-path", Input).value.strip()
        if not source:
            self.notify("Enter a source directory", severity="warning")
            return
        self.run_worker(self._do_export(source, contact_sheet, border), exclusive=True)

    async def _do_export(self, source: str, contact_sheet: bool, border: bool) -> None:
        from mavica_tools.export import export_images

        log = self.query_one("#log", RichLog)
        progress = self.query_one("#progress", ProgressBar)

        output = self.query_one("#output-dir", Input).value.strip() or "export"
        organize = self.query_one("#organize", Input).value.strip() or "flat"
        watermark = self.query_one("#watermark", Input).value.strip() or None
        resize_str = self.query_one("#resize", Input).value.strip()

        resize = None
        if resize_str and "x" in resize_str.lower():
            parts = resize_str.lower().split("x")
            resize = (int(parts[0]), int(parts[1]))

        log.write(f"Exporting from {source}...")
        progress.update(total=100, progress=10)

        summary = export_images(
            source, output,
            organize=organize,
            watermark=watermark,
            resize=resize,
            border=border,
            contact_sheet=contact_sheet,
        )

        progress.update(progress=100)
        output = self.query_one("#output-dir", Input).value.strip() or "export"
        log.write(f"[bold #33ff33]Done![/] {summary['exported']}/{summary['total']} images exported to [bold]{output}/[/]")
        if summary["errors"]:
            log.write(f"[red]{summary['errors']} error(s)[/]")
        if summary["contact_sheet_path"]:
            log.write(f"Contact sheet: {summary['contact_sheet_path']}")
            self.query_one("#preview", ImagePreview).image_path = summary["contact_sheet_path"]
