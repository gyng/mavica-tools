"""Recover Image screen — extract photos from a disk image (FAT12 + carve)."""

import os
from io import BytesIO
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

from mavica_tools.tui.widgets.defrag_map import TOTAL_SECTORS, DefragMap
from mavica_tools.tui.widgets.file_picker import FilePicker
from mavica_tools.tui.widgets.image_preview import ImagePreview

_SECTOR_SIZE = 512
_DATA_START_SECTOR = 33  # FAT12 data area starts at sector 33
_ZERO_SECTOR = b"\x00" * _SECTOR_SIZE


def _find_bad_sectors(data: bytes) -> set[int]:
    """Find bad sectors: zero-filled allocated sectors + FAT-marked 0xFF7.

    Only flags zero sectors that belong to a file's cluster chain —
    free/unused sectors are naturally zero and not bad.
    """
    bad = set()

    # Collect all sectors allocated to files via FAT
    try:
        from mavica_tools.fat12 import bad_sectors_from_fat, file_sector_map_from_data

        bad |= bad_sectors_from_fat(data)
        allocated: set[int] = set()
        for _name, sectors in file_sector_map_from_data(data):
            allocated.update(sectors)
    except Exception:
        return bad

    # Zero-filled sectors within allocated file data indicate failed reads
    for sector in allocated:
        offset = sector * _SECTOR_SIZE
        if (
            offset + _SECTOR_SIZE <= len(data)
            and data[offset : offset + _SECTOR_SIZE] == _ZERO_SECTOR
        ):
            bad.add(sector)

    return bad


def _decode_preview(filename: str, data: bytes):
    """Decode file bytes into a PIL Image for preview. Returns None on failure."""
    from PIL import Image

    if filename.upper().endswith(".411"):
        from mavica_tools.thumb411 import THUMB_HEIGHT, THUMB_WIDTH, decode_411

        pixels = decode_411(data)
        img = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT))
        img.putdata(pixels)
        return img.resize((256, 192), resample=0)

    return Image.open(BytesIO(data))


class RecoverImageScreen(Screen):
    """Extract photos from a disk image — FAT12 names or raw JPEG carving."""

    DEFAULT_CSS = """
    RecoverImageScreen VerticalScroll {
        height: 1fr;
    }
    #recover-main {
        height: auto;
        min-height: 10;
    }
    #recover-left {
        width: 1fr;
        min-width: 30;
    }
    #recover-right {
        width: 40;
        min-width: 30;
        align: center top;
    }
    #recover-right ImagePreview {
        height: auto;
        min-height: 5;
        content-align: center top;
        margin-bottom: 1;
    }
    RecoverImageScreen #method {
        width: 18;
        height: auto;
    }
    RecoverImageScreen #results-table {
        height: auto;
        margin: 0;
    }
    RecoverImageScreen #log {
        height: 2;
        max-height: 2;
        margin: 0;
        border: none;
    }
    RecoverImageScreen #defrag-map {
        width: 100%;
    }
    """

    BINDINGS: ClassVar[list] = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("b", "browse", "Browse", show=True),
        Binding("f2", "extract", "Extract", show=True),
        Binding("i", "open_input", "Open In", show=True),
        Binding("o", "open_output", "Open Out", show=True),
    ]

    _prefill_image: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static(
                "[bold #ffaa00]Recover Image[/]  [dim]Extract photos from a disk image[/]",
                id="title-bar",
            )

            # Source row
            with Horizontal(classes="input-row"):
                yield Static("  [bold]In[/] ", classes="row-label")
                yield Input(
                    placeholder="Path to disk image (.img, .bin, .raw)...",
                    id="image-path",
                )
                yield Button("Browse", id="btn-browse")
                yield Button("Open", id="btn-open-source")

            # Output row
            with Horizontal(classes="input-row"):
                yield Static(" [bold]Out[/] ", classes="row-label")
                yield Input(
                    value="mavica_out/recovered",
                    placeholder="Output directory",
                    id="output-dir",
                )
                yield Button("Browse", id="btn-browse-out")
                yield Button("Open", id="btn-open-folder")
                yield Select[str](
                    [("Auto", "auto"), ("FAT12", "fat12"), ("Carve", "carve")],
                    value="auto",
                    id="method",
                    allow_blank=False,
                    compact=True,
                )
                yield Button("Extract", variant="success", id="btn-extract")

            yield ProgressBar(total=100, show_percentage=True, show_eta=True, id="progress")

            # Two-pane: file list on left, preview on right
            with Horizontal(id="recover-main"):
                with Vertical(id="recover-left"):
                    with Horizontal(classes="button-row"):
                        yield Button("All", variant="default", id="btn-select-all")
                        yield Button("None", variant="default", id="btn-select-none")
                        yield Button("Include Deleted", variant="default", id="btn-deleted")
                        yield Static("  [dim]Space to toggle[/]")
                    yield DataTable(id="results-table")
                with Vertical(id="recover-right"):
                    yield ImagePreview(id="preview")

            yield DefragMap(id="defrag-map")

            # Post-extraction actions
            with Horizontal(classes="button-row"):
                yield Button(
                    "Check & Repair", variant="warning", id="btn-check-repair", disabled=True
                )
                yield Button("Stamp Photos", variant="default", id="btn-stamp", disabled=True)
                yield Button("Open Folder", variant="default", id="btn-open-result", disabled=True)

            yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Sel", "Status", "Filename", "Size", "Offset", "Date")
        table.cursor_type = "row"

        self._files: list = []  # FileEntry objects from FAT12 parse
        self._fat: list[int] = []
        self._data: bytes = b""
        self._selected: set[int] = set()
        self._include_deleted = False
        self._extracted_paths: list[str] = []
        self._bad_sectors: set[int] = set()
        self._file_damaged: dict[str, int] = {}  # filename -> bad sector count

        if self._prefill_image:
            self.query_one("#image-path", Input).value = self._prefill_image
            self._prefill_image = None

    # ── Input handling ────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "image-path":
            path = event.value.strip()
            if path and os.path.isfile(path):
                self._load_image(path)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "image-path":
            path = event.value.strip()
            if path:
                self._load_image(path)

    # ── Button handlers ───────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-browse-out":
            self._browse_output()
        elif event.button.id == "btn-open-source":
            self.action_open_input()
        elif event.button.id == "btn-open-folder":
            self.action_open_output()
        elif event.button.id == "btn-extract":
            self._start_extract()
        elif event.button.id == "btn-select-all":
            self._toggle_all(True)
        elif event.button.id == "btn-select-none":
            self._toggle_all(False)
        elif event.button.id == "btn-deleted":
            self._toggle_deleted()
        elif event.button.id == "btn-check-repair":
            self._go_to_repair()
        elif event.button.id == "btn-stamp":
            self._go_to_stamp()
        elif event.button.id == "btn-open-result":
            output = self.query_one("#output-dir", Input).value.strip()
            if output and os.path.isdir(output):
                from mavica_tools.utils import open_directory

                open_directory(output)

    # ── Actions / keybindings ─────────────────────────────────────

    def action_browse(self) -> None:
        def on_selected(path: str) -> None:
            if path:
                self.query_one("#image-path", Input).value = path

        self.app.push_screen(
            FilePicker(
                extensions=(".img", ".bin", ".raw"),
                title="Select disk image",
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

    def action_open_input(self) -> None:
        from mavica_tools.utils import open_directory

        source = self.query_one("#image-path", Input).value.strip()
        if source:
            d = os.path.dirname(os.path.abspath(source))
            if os.path.isdir(d):
                open_directory(d)

    def action_open_output(self) -> None:
        from mavica_tools.utils import open_directory

        output_dir = os.path.abspath(self.query_one("#output-dir", Input).value.strip())
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            open_directory(output_dir)

    def action_extract(self) -> None:
        self._start_extract()

    # ── Load image and list files ─────────────────────────────────

    def _load_image(self, path: str) -> None:
        """Parse the disk image, populate table and defrag map."""
        table = self.query_one("#results-table", DataTable)
        log = self.query_one("#log", RichLog)
        defrag = self.query_one("#defrag-map", DefragMap)

        table.clear()
        self._files = []
        self._fat = []
        self._data = b""
        self._selected = set()
        self._extracted_paths = []

        try:
            from mavica_tools.fat12 import (
                file_sector_map_from_data,
                parse_disk_image,
            )

            files, fat, data = parse_disk_image(path)
            self._files = files
            self._fat = fat
            self._data = data

            # Populate defrag map — disk image is already fully read,
            # so mark all sectors as good, then overlay bad sectors + files
            boundaries = file_sector_map_from_data(data)
            defrag.reset(clear_files=True)
            defrag.update_range(0, TOTAL_SECTORS, "good")
            if boundaries:
                defrag.set_file_boundaries(boundaries)

            bad = _find_bad_sectors(data)
            self._bad_sectors = bad
            if bad:
                for sector in bad:
                    defrag.update_sector(sector, "bad")
                log.write(f"[red]{len(bad)} bad sector(s)[/]")

            # Build per-file bad sector lookup from boundaries
            self._file_damaged = {}
            if bad and boundaries:
                for name, sectors in boundaries:
                    n_bad = sum(1 for s in sectors if s in bad)
                    if n_bad:
                        self._file_damaged[name] = n_bad

            # Filter deleted if needed
            display_files = (
                files if self._include_deleted else [f for f in files if not f.is_deleted]
            )

            if not display_files:
                table.add_row("", "", "[dim]No files found on disk[/]", "", "", "")
                log.write("[dim]No files found. Try Carve method for damaged disks.[/]")
                self._update_extract_label()
                return

            for i, f in enumerate(display_files):
                self._selected.add(i)
                sel = "[green]\u25cf[/]"
                if f.is_deleted:
                    status = "[red]DEL[/]"
                elif f.name in self._file_damaged:
                    status = f"[red]BAD:{self._file_damaged[f.name]}[/]"
                else:
                    status = "[green]OK[/]"
                table.add_row(
                    sel,
                    status,
                    f.name,
                    f"{f.size:,}",
                    f"0x{f.byte_offset:06X}",
                    f.date_str,
                )

            log.write(f"Found {len(display_files)} file(s) via FAT12.")
            self._update_extract_label()

            # Auto-preview first file and focus table
            if display_files:
                self._show_preview(0)
            table.focus()

        except Exception as e:
            defrag.reset(clear_files=True)
            log.write(f"[#ffaa00]FAT12 unreadable:[/] {e}")
            log.write("[dim]Use [bold]Carve[/] method to extract JPEGs from raw data.[/]")

            # Try to show JPEG count and bad sectors even with damaged FAT
            try:
                with open(path, "rb") as f:
                    data = f.read()
                self._data = data

                # Mark all sectors good first (image is fully read from file)
                defrag.update_range(0, TOTAL_SECTORS, "good")

                # Show bad sectors (zero-filled + FAT-marked)
                bad = _find_bad_sectors(data)
                if bad:
                    for sector in bad:
                        defrag.update_sector(sector, "bad")
                    log.write(f"[red]{len(bad)} bad sector(s)[/]")

                from mavica_tools.carve import find_jpegs

                jpegs = find_jpegs(data)
                if jpegs:
                    log.write(f"[green]Carve scan found {len(jpegs)} JPEG(s).[/]")
                    self.query_one("#method", Select).value = "carve"
            except Exception:
                pass

            self._update_extract_label()

    # ── Preview ───────────────────────────────────────────────────

    def _show_preview(self, display_idx: int) -> None:
        """Show in-memory preview for a file at the given display index."""
        preview = self.query_one("#preview", ImagePreview)

        # Get the actual file entry
        display_files = self._get_display_files()
        if display_idx >= len(display_files):
            return

        f = display_files[display_idx]

        # If already extracted, show from disk
        if self._extracted_paths and display_idx < len(self._extracted_paths):
            path = self._extracted_paths[display_idx]
            if path and os.path.isfile(path):
                if path.upper().endswith(".411"):
                    try:
                        with open(path, "rb") as fh:
                            img = _decode_preview(os.path.basename(path), fh.read())
                        if img:
                            preview.set_pil_image(img, os.path.basename(path))
                            return
                    except Exception:
                        pass
                else:
                    preview.image_path = path
                    return

        # In-memory preview from disk image
        if self._data and self._fat:
            try:
                from mavica_tools.fat12 import extract_file

                file_bytes = extract_file(self._data, self._fat, f)
                img = _decode_preview(f.name, file_bytes)
                if img:
                    preview.set_pil_image(img, f.name)
                else:
                    preview.image_path = ""
            except Exception:
                preview.image_path = ""
        else:
            preview.image_path = ""

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is not None and self._files:
            self._show_preview(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Toggle selection on Enter."""
        self._toggle_row(event.cursor_row)

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        self._toggle_row(event.coordinate.row)

    # ── Selection ─────────────────────────────────────────────────

    def on_key(self, event) -> None:
        table = self.query_one("#results-table", DataTable)
        if not table.has_focus or not self._get_display_files():
            return
        if event.key in ("space",):
            event.prevent_default()
            event.stop()
            self._toggle_row(table.cursor_row)

    def _toggle_row(self, idx: int) -> None:
        if idx >= len(self._get_display_files()):
            return
        if idx in self._selected:
            self._selected.discard(idx)
        else:
            self._selected.add(idx)
        self._refresh_table()

    def _toggle_all(self, select: bool) -> None:
        display_files = self._get_display_files()
        if select:
            self._selected = set(range(len(display_files)))
        else:
            self._selected = set()
        self._refresh_table()

    def _toggle_deleted(self) -> None:
        self._include_deleted = not self._include_deleted
        btn = self.query_one("#btn-deleted", Button)
        btn.label = "Deleted: ON" if self._include_deleted else "Include Deleted"
        # Re-list if we have data
        path = self.query_one("#image-path", Input).value.strip()
        if path and os.path.isfile(path):
            self._load_image(path)

    def _get_display_files(self) -> list:
        if self._include_deleted:
            return self._files
        return [f for f in self._files if not f.is_deleted]

    def _refresh_table(self) -> None:
        """Rebuild table to reflect selection state."""
        table = self.query_one("#results-table", DataTable)
        display_files = self._get_display_files()

        rows_data = []
        for i, f in enumerate(display_files):
            selected = i in self._selected
            sel = "[green]\u25cf[/]" if selected else "[dim]\u25cb[/]"
            if f.is_deleted:
                status = "[red]DEL[/]"
            elif f.name in self._file_damaged:
                status = f"[red]BAD:{self._file_damaged[f.name]}[/]"
            else:
                status = "[green]OK[/]"
            name = f"[bold]{f.name}[/]" if selected else f"[dim]{f.name}[/]"
            size = f"{f.size:,}" if selected else f"[dim]{f.size:,}[/]"
            offset = f"0x{f.byte_offset:06X}" if selected else f"[dim]0x{f.byte_offset:06X}[/]"
            date = f.date_str if selected else f"[dim]{f.date_str}[/]"
            rows_data.append((sel, status, name, size, offset, date))

        cursor = table.cursor_row
        table.clear()
        for row in rows_data:
            table.add_row(*row)
        if cursor < len(rows_data):
            table.move_cursor(row=cursor)

        self._update_extract_label()

    def _update_extract_label(self) -> None:
        n = len(self._selected)
        self.query_one("#btn-extract", Button).label = (
            f"Extract {n} {'file' if n == 1 else 'files'}" if n else "Extract"
        )

    # ── Extraction ────────────────────────────────────────────────

    def _start_extract(self) -> None:
        image_path = self.query_one("#image-path", Input).value.strip()
        if not image_path:
            self.notify("Enter a disk image path", severity="warning")
            return
        if not os.path.isfile(image_path):
            self.notify(f"File not found: {image_path}", severity="error")
            return

        btn = self.query_one("#btn-extract", Button)
        btn.disabled = True
        btn.label = "Extracting..."
        self.run_worker(
            self._do_extract(image_path),
            exclusive=True,
        )

    async def _do_extract(self, image_path: str) -> None:
        worker = get_current_worker()
        log = self.query_one("#log", RichLog)
        progress = self.query_one("#progress", ProgressBar)
        output_dir = self.query_one("#output-dir", Input).value.strip() or "mavica_out/recovered"
        method = self.query_one("#method", Select).value or "auto"

        os.makedirs(output_dir, exist_ok=True)
        self._extracted_paths = []
        extracted_count = 0

        if method in ("auto", "fat12"):
            try:
                extracted_count = await self._extract_fat12(
                    image_path,
                    output_dir,
                    log,
                    progress,
                    worker,
                )
            except Exception as e:
                if method == "fat12":
                    log.write(f"[red]FAT12 extraction failed: {e}[/]")
                    log.write("[dim]Try Auto or Carve method for damaged disks.[/]")
                    self._reset_extract_button()
                    return
                else:
                    log.write(f"[#ffaa00]FAT12 failed ({e}), falling back to carve...[/]")
                    extracted_count = await self._extract_carve(
                        image_path,
                        output_dir,
                        log,
                        progress,
                        worker,
                    )

        elif method == "carve":
            extracted_count = await self._extract_carve(
                image_path,
                output_dir,
                log,
                progress,
                worker,
            )

        if extracted_count > 0:
            log.write(f"\n[bold #33ff33]{extracted_count} file(s) extracted to {output_dir}/[/]")
            log.write("[dim]Select a row to preview. Use Check/Stamp for next steps.[/]")
            self.query_one("#btn-check-repair", Button).disabled = False
            self.query_one("#btn-stamp", Button).disabled = False
            self.query_one("#btn-open-result", Button).disabled = False
        else:
            log.write("[red]No files extracted.[/]")

        self._reset_extract_button()

    async def _extract_fat12(
        self,
        image_path: str,
        output_dir: str,
        log: RichLog,
        progress: ProgressBar,
        worker,
    ) -> int:
        """Extract files via FAT12 filesystem. Returns count of extracted files."""
        from mavica_tools.fat12 import extract_with_names

        display_files = self._get_display_files()
        selected_names = {display_files[i].name for i in self._selected if i < len(display_files)}

        results = extract_with_names(
            image_path,
            output_dir,
            include_deleted=self._include_deleted,
        )

        progress.update(total=len(results), progress=0)
        self._extracted_paths = []

        for i, (orig_name, out_path, _size, _deleted) in enumerate(results):
            if worker.is_cancelled:
                log.write("[yellow]Cancelled.[/]")
                return i

            self._extracted_paths.append(out_path if orig_name in selected_names else "")
            progress.update(progress=i + 1)

        # Refresh table with extraction status
        self._refresh_table()
        return len(results)

    async def _extract_carve(
        self,
        image_path: str,
        output_dir: str,
        log: RichLog,
        progress: ProgressBar,
        worker,
    ) -> int:
        """Extract files via JPEG carving. Returns count of extracted files."""
        from mavica_tools.carve import find_jpegs

        log.write("Scanning for JPEG markers...")

        with open(image_path, "rb") as f:
            data = f.read()

        jpegs = find_jpegs(data)
        if not jpegs:
            log.write("[red]No JPEG images found in raw data.[/]")
            return 0

        progress.update(total=len(jpegs), progress=0)

        # Rebuild table for carved results
        table = self.query_one("#results-table", DataTable)
        table.clear()
        self._files = []
        self._selected = set()
        self._extracted_paths = []

        for i, (offset, length, truncated) in enumerate(jpegs):
            if worker.is_cancelled:
                log.write("[yellow]Cancelled.[/]")
                return i

            suffix = "_TRUNCATED" if truncated else ""
            filename = f"mavica_{i + 1:03d}{suffix}.jpg"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "wb") as f:
                f.write(data[offset : offset + length])

            status = "[red]TRUNC[/]" if truncated else "[green]OK[/]"
            table.add_row(
                "[green]\u25cf[/]",
                status,
                filename,
                f"{length:,}",
                f"0x{offset:06X}",
                "",
            )
            self._selected.add(i)
            self._extracted_paths.append(filepath)
            progress.update(progress=i + 1)

        return len(jpegs)

    def _reset_extract_button(self) -> None:
        btn = self.query_one("#btn-extract", Button)
        btn.disabled = False
        self._update_extract_label()

    # ── Navigation to next screens ────────────────────────────────

    def _go_to_repair(self) -> None:
        import glob as globmod

        output_dir = self.query_one("#output-dir", Input).value.strip()
        if output_dir and os.path.isdir(output_dir):
            files = []
            for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
                files.extend(globmod.glob(os.path.join(output_dir, ext)))
            screen = self.app.SCREENS["repair"]()
            if files:
                screen._prefill_files = sorted(files)
            self.app.push_screen(screen)

    def _go_to_stamp(self) -> None:
        output_dir = self.query_one("#output-dir", Input).value.strip()
        if output_dir and os.path.isdir(output_dir):
            screen = self.app.SCREENS["stamp"]()
            screen._prefill_path = output_dir
            self.app.push_screen(screen)
