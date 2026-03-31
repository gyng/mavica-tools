"""Batch recovery screen — full pipeline in one step."""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog, ProgressBar
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.tui.widgets.file_picker import FilePicker


class RecoverScreen(Screen):
    """Full recovery pipeline: merge -> extract -> check -> repair."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Batch Recovery[/]  "
            "[dim]Full pipeline: merge > extract > check > repair[/]\n",
            id="title-bar",
        )
        yield Static("", id="breadcrumb")
        yield Static(
            "  Point this at a directory containing disk image passes\n"
            "  (pass_01.img, pass_02.img, ...) or select individual .img files.\n"
        )
        yield Static("  [bold]Source Dir[/]")
        with Horizontal(classes="input-row"):
            yield Input(placeholder="Directory with .img files...", id="source-dir")
            yield Button("Browse", id="btn-browse")
        yield Static("  [bold]Output Dir[/]")
        with Horizontal(classes="input-row"):
            yield Input(value="mavica_out/recovery", placeholder="Output directory", id="output-dir")
        yield Static(
            "  [dim][bold]FAT12 first[/] — recovers original Mavica filenames (MVC-001.JPG).\n"
            "  [bold]Carve only[/] — scans raw data for JPEGs. Use if FAT12 fails or disk is very damaged.[/]\n"
        )
        with Horizontal(classes="button-row"):
            yield Button("Recover (FAT12 first)", variant="success", id="btn-recover")
            yield Button("Recover (carve only)", variant="warning", id="btn-recover-carve")
        yield ProgressBar(total=4, show_percentage=True, show_eta=True, id="progress")
        yield Static("", id="step-status")
        with Horizontal(classes="button-row"):
            yield Button("Next: Add Photo Info", variant="default", id="btn-next-stamp", disabled=True)
            yield Button("Next: Export & Share", variant="default", id="btn-next-export", disabled=True)
            yield Button("Open Folder", variant="default", id="btn-open-folder", disabled=True)
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self._update_breadcrumb(0)

    def _update_breadcrumb(self, current: int) -> None:
        labels = ["Merge", "Extract", "Check", "Repair"]
        parts = []
        for i, label in enumerate(labels):
            if i < current:
                parts.append(f"[green][bold]\u2713[/bold] {label}[/green]")
            elif i == current:
                parts.append(f"[bold #ffaa00]\u25cf {label}[/bold #ffaa00]")
            else:
                parts.append(f"[dim]\u25cb {label}[/dim]")
        self.query_one("#breadcrumb", Static).update(
            "  " + "  \u2500\u25b6  ".join(parts)
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-recover":
            self._start_recover(use_fat=True)
        elif event.button.id == "btn-recover-carve":
            self._start_recover(use_fat=False)
        elif event.button.id == "btn-next-stamp":
            self.app.push_screen("stamp")
        elif event.button.id == "btn-next-export":
            self.app.push_screen("export")
        elif event.button.id == "btn-open-folder":
            output = self.query_one("#output-dir", Input).value.strip()
            if output and os.path.isdir(output):
                from mavica_tools.utils import open_directory
                open_directory(output)

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#source-dir", Input).value = path
        self.app.push_screen(
            FilePicker(
                extensions=(".img",),
                title="Select directory with disk images",
                select_directory=True,
            ),
            on_selected,
        )

    def _start_recover(self, use_fat: bool) -> None:
        source = self.query_one("#source-dir", Input).value.strip()
        output = self.query_one("#output-dir", Input).value.strip()
        if not source:
            self.notify("Enter a source directory", severity="warning")
            return

        for btn_id in ("#btn-recover", "#btn-recover-carve"):
            self.query_one(btn_id, Button).disabled = True
        self.run_worker(self._run_pipeline(source, output, use_fat), exclusive=True)

    async def _run_pipeline(self, source: str, output: str, use_fat: bool) -> None:
        import glob as globmod
        from mavica_tools.recover import recover_from_images

        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        progress = self.query_one("#progress", ProgressBar)
        status = self.query_one("#step-status", Static)

        # Find image files
        img_files = sorted(globmod.glob(os.path.join(source, "pass_*.img")))
        if not img_files:
            img_files = sorted(globmod.glob(os.path.join(source, "*.img")))
            img_files = [f for f in img_files if "merged" not in os.path.basename(f)]

        if not img_files:
            log.write("[red]No disk images found.[/] Need .img files in that directory.")
            log.write("[bold #33ff33]Tip:[/] Use [bold]Multi-Pass Read[/] (key [bold]m[/]) to create disk images from your floppy first.")
            self._reset_buttons()
            return

        log.write(f"Found {len(img_files)} image file(s)\n")
        progress.update(total=4, progress=0)

        self._update_breadcrumb(0)
        status.update("  [1/4] Merging passes...")
        log.write("[bold][1/4] Merging...[/]")

        try:
            summary = recover_from_images(img_files, output, use_fat=use_fat)
        except Exception as e:
            log.write(f"[red]Error: {e}[/]")
            self._reset_buttons()
            return

        self._update_breadcrumb(4)
        progress.update(progress=4)

        # Show results
        log.write(f"\n{'='*50}")
        log.write(f"[bold]Recovery complete:[/] {output}/")
        log.write(f"  Total:    {summary['total_files']}")
        log.write(f"  [green]Good:     {summary['good']}[/]")
        log.write(f"  [#ffaa00]Repaired: {summary['repaired']}[/]")
        log.write(f"  [red]Failed:   {summary['failed']}[/]")
        log.write(f"  Method:   {summary['extraction_method']}")

        if summary['total_files'] > 0:
            status.update(
                f"  Done — {summary['total_files']} files, "
                f"{summary['good']} good, {summary['repaired']} repaired\n\n"
                f"  [bold #33ff33]What next?[/] Add camera/date info, or export for sharing."
            )
            self.query_one("#btn-next-stamp", Button).disabled = False
            self.query_one("#btn-next-export", Button).disabled = False
            self.query_one("#btn-open-folder", Button).disabled = False
        else:
            status.update("  No files recovered.")

        self._reset_buttons()

    def _reset_buttons(self) -> None:
        for btn_id in ("#btn-recover", "#btn-recover-carve"):
            self.query_one(btn_id, Button).disabled = False
