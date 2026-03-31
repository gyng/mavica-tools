"""Guided workflow screen — step-by-step recovery."""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog
from textual.containers import Horizontal


STEPS = [
    ("1. Image the Floppy", "Multi-pass read to capture every readable sector."),
    ("2. Extract JPEGs", "Try FAT12 first (preserves names), fall back to carving."),
    ("3. Check Files", "Scan extracted images for corruption."),
    ("4. Repair", "Salvage pixels from corrupt images."),
    ("5. Stamp Metadata", "Add camera model and date to recovered JPEGs."),
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

        # Step indicators
        step_text = "  >  ".join(
            f"[bold #ffaa00]{name.split('.')[0]}[/]" for name, _ in STEPS
        )
        yield Static(f"  {step_text}\n")

        yield Static(
            "  Each step feeds into the next. Complete them in order\n"
            "  for best results. Paths auto-fill between steps.\n"
        )

        yield Static("  [bold]Output Directory[/]", classes="section-title")
        with Horizontal(classes="input-row"):
            yield Input(value="recovery", placeholder="Base directory for this session", id="base-dir")

        with Horizontal(classes="button-row"):
            yield Button("1. Read Floppy", variant="success", id="btn-step1")
            yield Button("2. Extract", variant="success", id="btn-step2")
            yield Button("3. Check", variant="default", id="btn-step3", disabled=True)
            yield Button("4. Repair", variant="default", id="btn-step4", disabled=True)
            yield Button("5. Stamp", variant="default", id="btn-step5", disabled=True)

        yield Static("", id="workflow-status")
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self._check_existing_state()

    def _check_existing_state(self) -> None:
        """Enable step buttons based on what files already exist."""
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
            self.query_one("#btn-step3", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        base = self.query_one("#base-dir", Input).value.strip() or "recovery"
        log = self.query_one("#log", RichLog)

        if event.button.id == "btn-step1":
            log.write("[bold]Step 1:[/] Opening Multipass Read...")
            log.write(f"  Output directory: [bold]{base}/[/]")
            self.app.push_screen("multipass")

        elif event.button.id == "btn-step2":
            log.write("[bold]Step 2:[/] Opening Batch Recover...")
            log.write(f"  Will look for images in [bold]{base}/[/]")
            # Push recover screen which does FAT12 + carve + check
            self.app.push_screen("recover")

        elif event.button.id == "btn-step3":
            extracted = os.path.join(base, "extracted")
            carved = os.path.join(base, "carved_images")
            target = extracted if os.path.isdir(extracted) else carved
            if os.path.isdir(target):
                log.write(f"[bold]Step 3:[/] Checking files in {target}/")
                screen = self.app.SCREENS["check"]()
                screen._prefill_path = target
                self.app.push_screen(screen)
            else:
                log.write("[#ffaa00]Step 3:[/] No extracted files found. Run step 2 first.")
                self.notify("Run step 2 first to extract images", severity="warning")

        elif event.button.id == "btn-step4":
            log.write("[bold]Step 4:[/] Opening Repair...")
            self.app.push_screen("repair")

        elif event.button.id == "btn-step5":
            log.write("[bold]Step 5:[/] Opening Stamp Metadata...")
            self.app.push_screen("stamp")

        # Enable subsequent steps
        if event.button.id == "btn-step1":
            self.query_one("#btn-step2", Button).disabled = False
        elif event.button.id == "btn-step2":
            self.query_one("#btn-step3", Button).disabled = False
        elif event.button.id == "btn-step3":
            self.query_one("#btn-step4", Button).disabled = False
            self.query_one("#btn-step5", Button).disabled = False
