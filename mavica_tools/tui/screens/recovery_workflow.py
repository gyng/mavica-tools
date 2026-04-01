"""Recovery workflow — for damaged or unreadable floppies.

Multi-pass reading, carving, checking, and repairing of corrupt images.
"""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static


class RecoveryWorkflowScreen(Screen):
    """Guided recovery for damaged disks."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Repair & Recovery[/]  [dim]For damaged floppies and corrupt photos[/]\n",
            id="title-bar",
        )
        yield Static("", id="breadcrumb")
        yield Static(
            "  Can't read your floppy? Photos look corrupt? Follow these\n"
            "  steps. Multi-pass reading often recovers sectors that fail\n"
            "  on the first attempt.\n"
        )

        yield Static("  [bold]Output Directory[/]", classes="section-title")
        with Horizontal(classes="input-row"):
            yield Input(
                value="mavica_out/recovery",
                placeholder="Where to save recovered files",
                id="base-dir",
            )

        yield Static("\n  [bold #ff3333]Step 1: Image the disk[/]")
        yield Static(
            "  [dim]Read the floppy multiple times. Bad sectors may read\n"
            "  successfully on retry — we merge the best from each pass.[/]"
        )
        with Horizontal(classes="button-row"):
            yield Button("Multi-Pass Read", variant="success", id="btn-multipass")
            yield Button("One-Click Recover", variant="warning", id="btn-recover")

        yield Static("\n  [bold #ffaa00]Step 2: Extract photos[/]")
        yield Static(
            "  [dim]Try filesystem extraction first. If that fails,\n"
            "  raw JPEG carving finds images in the raw disk data.[/]"
        )
        with Horizontal(classes="button-row"):
            yield Button("Extract with Names", variant="success", id="btn-fat12", disabled=True)
            yield Button("Carve from Raw", variant="warning", id="btn-carve", disabled=True)

        yield Static("\n  [bold #33ff33]Step 3: Check & repair[/]")
        yield Static("  [dim]Scan for corruption and attempt to salvage partial images.[/]")
        with Horizontal(classes="button-row"):
            yield Button("Check for Damage", variant="success", id="btn-check", disabled=True)
            yield Button("Repair Images", variant="warning", id="btn-repair", disabled=True)

        yield Static(
            "\n  [dim]After recovery, go back and use [bold]Import & Tag[/dim] to add metadata and export.[/]"
        )

        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self._current_step = 1
        self._previewed = False
        self._update_breadcrumb()
        self._check_existing()

    def on_screen_resume(self) -> None:
        """Called when this screen is shown again after a sub-screen is popped."""
        base = self.query_one("#base-dir", Input).value.strip() or "recovery"
        merged = os.path.join(base, "merged.img")
        if os.path.exists(merged) and not self._previewed:
            self._enable_step2()
            self._preview_files(base)
        for subdir in ("extracted", "carved_images"):
            if os.path.isdir(os.path.join(base, subdir)):
                self._enable_step3()
                break

    def _update_breadcrumb(self) -> None:
        step = self._current_step
        labels = ["Image Disk", "Extract Photos", "Check & Repair"]
        parts = []
        for i, label in enumerate(labels, 1):
            if i < step:
                parts.append(f"[green][bold]\u2713[/bold] {label}[/green]")
            elif i == step:
                parts.append(f"[bold #ffaa00]\u25cf {label}[/bold #ffaa00]")
            else:
                parts.append(f"[dim]\u25cb {label}[/dim]")
        self.query_one("#breadcrumb", Static).update("  " + "  \u2500\u25b6  ".join(parts))

    def _check_existing(self) -> None:
        base = self.query_one("#base-dir", Input).value.strip()
        if os.path.exists(os.path.join(base, "merged.img")):
            self._enable_step2()
            log = self.query_one("#log", RichLog)
            log.write(f"[dim]Found existing merged.img in {base}/[/]")
            self._preview_files(base)

        for subdir in ("extracted", "carved_images"):
            if os.path.isdir(os.path.join(base, subdir)):
                self._enable_step3()
                break

    def _preview_files(self, base: str) -> None:
        """Attempt a FAT12 file listing from merged.img and show in log."""
        merged = os.path.join(base, "merged.img")
        if not os.path.exists(merged):
            return
        self._previewed = True
        log = self.query_one("#log", RichLog)
        try:
            from mavica_tools.fat12 import list_files

            files = list_files(merged, include_deleted=True)
            if not files:
                log.write("  [dim]No files found in FAT12 filesystem.[/]")
                return
            log.write(f"\n  [bold]Files on disk[/] ({len(files)} found):")
            for f in files:
                status = "[red]DEL[/]" if f.is_deleted else "[green]OK[/]"
                offset = f"0x{f.byte_offset:06X}"
                log.write(
                    f"    {status}  {f.name:<15s}  {f.size:>6,} bytes  @ {offset}  {f.date_str}"
                )
            total = sum(f.size for f in files if not f.is_deleted)
            log.write(f"    [dim]Total: {total:,} bytes[/]\n")
        except Exception:
            log.write("  [#ffaa00]FAT12 unreadable — use Carve from Raw for this disk.[/]\n")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        base = self.query_one("#base-dir", Input).value.strip() or "recovery"
        log = self.query_one("#log", RichLog)

        if event.button.id == "btn-multipass":
            log.write(f"[bold]Step 1:[/] Reading floppy to {base}/")
            log.write("[dim]Tip: 5 passes is usually enough. More passes = better recovery.[/]")
            screen = self.app.SCREENS["multipass"]()
            screen._prefill_output_dir = base
            self.app.push_screen(screen)
            self._enable_step2()

        elif event.button.id == "btn-recover":
            log.write("[bold]Step 1+2:[/] Running full pipeline...")
            self.app.push_screen("recover")
            self._enable_step2()
            self._enable_step3()

        elif event.button.id == "btn-fat12":
            merged = os.path.join(base, "merged.img")
            if os.path.exists(merged):
                log.write(f"[bold]Step 2:[/] Extracting from {merged}")
                screen = self.app.SCREENS["fat12"]()
                screen._prefill_image = merged
                self.app.push_screen(screen)
            else:
                log.write("[#ffaa00]No merged.img found. Run Step 1 first.[/]")
                self.notify("Run Step 1 first", severity="warning")
                return
            self._enable_step3()

        elif event.button.id == "btn-carve":
            merged = os.path.join(base, "merged.img")
            if os.path.exists(merged):
                log.write(f"[bold]Step 2:[/] Carving JPEGs from {merged}")
                screen = self.app.SCREENS["carve"]()
                screen._prefill_image = merged
                self.app.push_screen(screen)
            else:
                log.write("[#ffaa00]No merged.img found. Run Step 1 first.[/]")
                self.notify("Run Step 1 first", severity="warning")
                return
            self._enable_step3()

        elif event.button.id == "btn-check":
            target = self._find_images(base)
            if target:
                log.write(f"[bold]Step 3:[/] Checking {target}/")
                screen = self.app.SCREENS["check"]()
                screen._prefill_path = target
                self.app.push_screen(screen)
            else:
                self.notify("Extract photos first (Step 2)", severity="warning")

        elif event.button.id == "btn-repair":
            target = self._find_images(base)
            if target:
                log.write(f"[bold]Step 3:[/] Repairing images in {target}/")
                screen = self.app.SCREENS["repair"]()
                screen._prefill_files = None
                self.app.push_screen(screen)
            else:
                self.notify("Extract photos first (Step 2)", severity="warning")

    def _enable_step2(self) -> None:
        self.query_one("#btn-fat12", Button).disabled = False
        self.query_one("#btn-carve", Button).disabled = False
        if self._current_step < 2:
            self._current_step = 2
            self._update_breadcrumb()

    def _enable_step3(self) -> None:
        self.query_one("#btn-check", Button).disabled = False
        self.query_one("#btn-repair", Button).disabled = False
        if self._current_step < 3:
            self._current_step = 3
            self._update_breadcrumb()

    def _find_images(self, base: str) -> str | None:
        for subdir in ("extracted", "carved_images", "repaired"):
            d = os.path.join(base, subdir)
            if os.path.isdir(d):
                return d
        return None
