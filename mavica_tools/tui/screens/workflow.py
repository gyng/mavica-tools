"""Guided workflow screen — full recovery journey."""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog
from textual.containers import Horizontal


STEPS = [
    ("1. Read Floppy", "Create a multi-pass disk image for best recovery."),
    ("2. Extract", "Recover files — tries original names first, falls back to carving."),
    ("3. Check", "Scan extracted images for corruption."),
    ("4. Repair", "Salvage pixels from any corrupt images."),
    ("5. Add Info", "Stamp camera model, date, and lens data into EXIF."),
    ("6. Add GPS", "Match photos to a GPS track (optional, if you have GPX data)."),
    ("7. Export", "Organize, create contact sheets, add watermarks."),
    ("8. Report", "Generate an HTML summary of the recovery."),
]


class WorkflowScreen(Screen):
    """Guided step-by-step recovery workflow."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Guided Recovery Workflow[/]  "
            "[dim]Follow these steps in order[/]\n",
            id="title-bar",
        )

        yield Static(
            "  [bold]Step 1[/] > 2 > 3 > 4 > 5 > 6 > 7 > 8\n\n"
            "  Complete each step in order. Paths auto-fill between steps.\n"
            "  Steps 6 (GPS) and 8 (Report) are optional.\n"
        )

        yield Static("  [bold]Output Directory[/]", classes="section-title")
        with Horizontal(classes="input-row"):
            yield Input(value="recovery", placeholder="Base directory for this session", id="base-dir")

        yield Static("\n  [bold #33ff33]--- Recovery ---[/]")
        with Horizontal(classes="button-row"):
            yield Button("1. Read Floppy", variant="success", id="btn-step1")
            yield Button("2. Extract", variant="success", id="btn-step2")
            yield Button("3. Check", variant="default", id="btn-step3", disabled=True)
            yield Button("4. Repair", variant="default", id="btn-step4", disabled=True)

        yield Static("\n  [bold #33ff33]--- Post-Processing ---[/]")
        with Horizontal(classes="button-row"):
            yield Button("5. Add Info", variant="default", id="btn-step5", disabled=True)
            yield Button("6. Add GPS", variant="default", id="btn-step6", disabled=True)
            yield Button("7. Export", variant="default", id="btn-step7", disabled=True)
            yield Button("8. Report", variant="default", id="btn-step8", disabled=True)

        yield Static("", id="workflow-status")
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self._check_existing_state()

    def _check_existing_state(self) -> None:
        base = self.query_one("#base-dir", Input).value.strip()
        log = self.query_one("#log", RichLog)

        merged = os.path.join(base, "merged.img")
        extracted = os.path.join(base, "extracted")
        carved = os.path.join(base, "carved_images")

        if os.path.exists(merged):
            log.write(f"[dim]Found: {merged}[/]")
        if os.path.isdir(extracted) or os.path.isdir(carved):
            img_dir = extracted if os.path.isdir(extracted) else carved
            log.write(f"[dim]Found: {img_dir}/[/]")
            self._enable_from_step(3)

    def _enable_from_step(self, step: int) -> None:
        """Enable all steps from the given step number onwards."""
        for i in range(step, 9):
            try:
                btn = self.query_one(f"#btn-step{i}", Button)
                btn.disabled = False
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        base = self.query_one("#base-dir", Input).value.strip() or "recovery"
        log = self.query_one("#log", RichLog)

        if event.button.id == "btn-step1":
            log.write("[bold]Step 1:[/] Opening Read Floppy...")
            log.write(f"  Output: [bold]{base}/[/]")
            log.write("[dim]Tip: After reading, come back here for step 2.[/]")
            self.app.push_screen("multipass")
            self._enable_from_step(2)

        elif event.button.id == "btn-step2":
            log.write("[bold]Step 2:[/] Opening Batch Recover (extract + check + repair)...")
            self.app.push_screen("recover")
            self._enable_from_step(3)

        elif event.button.id == "btn-step3":
            target = self._find_images_dir(base)
            if target:
                log.write(f"[bold]Step 3:[/] Checking {target}/")
                screen = self.app.SCREENS["check"]()
                screen._prefill_path = target
                self.app.push_screen(screen)
            else:
                self.notify("Run step 2 first to extract images", severity="warning")
            self._enable_from_step(4)

        elif event.button.id == "btn-step4":
            log.write("[bold]Step 4:[/] Opening Repair...")
            self.app.push_screen("repair")
            self._enable_from_step(5)

        elif event.button.id == "btn-step5":
            log.write("[bold]Step 5:[/] Opening Add Photo Info...")
            log.write("[dim]Tip: Enter your camera model (e.g., fd7) to add accurate lens data.[/]")
            self.app.push_screen("stamp")
            self._enable_from_step(6)

        elif event.button.id == "btn-step6":
            log.write("[bold]Step 6:[/] Opening GPS Merge...")
            log.write("[dim]Tip: You need a GPX file from a GPS logger or phone.[/]")
            self.app.push_screen("gps")
            self._enable_from_step(7)

        elif event.button.id == "btn-step7":
            log.write("[bold]Step 7:[/] Opening Export...")
            log.write("[dim]Tip: Try a contact sheet — great for sharing a whole disk's worth of photos.[/]")
            self.app.push_screen("export")
            self._enable_from_step(8)

        elif event.button.id == "btn-step8":
            log.write("[bold]Step 8:[/] Generating recovery report...")
            self.app.push_screen("report") if "report" in self.app.SCREENS else None

    def _find_images_dir(self, base: str) -> str | None:
        for subdir in ("extracted", "carved_images", "repaired"):
            d = os.path.join(base, subdir)
            if os.path.isdir(d):
                return d
        return None
