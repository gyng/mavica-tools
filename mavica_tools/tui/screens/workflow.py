"""Guided workflow screen — step-by-step recovery."""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, RichLog
from textual.containers import Horizontal


STEPS = [
    ("Image the Floppy", "Run a multi-pass read to capture data from the disk."),
    ("Carve JPEGs", "Extract JPEG images from the raw disk image."),
    ("Check Files", "Scan extracted images for corruption."),
    ("Repair", "Attempt to salvage corrupt images."),
]


class WorkflowScreen(Screen):
    """Guided step-by-step recovery workflow."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #ffaa00]Guided Recovery Workflow[/]\n", id="title-bar")

        # Step indicators
        step_text = "  ".join(
            f"[bold #ffaa00][{i+1}][/] {name}" for i, (name, _) in enumerate(STEPS)
        )
        yield Static(f"  {step_text}\n", id="step-bar")

        yield Static("", id="step-description")
        yield Static(
            "  This workflow guides you through the full recovery process.\n"
            "  Each step feeds into the next automatically.\n",
        )

        with Horizontal():
            yield Button("1. Multipass Read", variant="success", id="btn-step1")
            yield Button("2. Carve JPEGs", variant="default", id="btn-step2")
            yield Button("3. Check Files", variant="default", id="btn-step3")
            yield Button("4. Repair", variant="default", id="btn-step4")

        yield Static("\n  [bold]Working Directory[/]", classes="section-title")
        with Horizontal():
            yield Input(
                placeholder="Base output directory for this recovery session",
                value="recovery",
                id="base-dir",
            )

        yield Static("", id="workflow-status")
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self._update_step_description(0)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        base_dir = self.query_one("#base-dir", Input).value.strip() or "recovery"
        log = self.query_one("#log", RichLog)

        if event.button.id == "btn-step1":
            log.write("[bold]Step 1:[/] Opening Multipass Read...")
            log.write(f"  Tip: Output will go to [bold]{base_dir}/[/]")
            self.app.push_screen("multipass")

        elif event.button.id == "btn-step2":
            merged_path = os.path.join(base_dir, "merged.img")
            if os.path.exists(merged_path):
                log.write(f"[bold]Step 2:[/] Found {merged_path}")
            else:
                log.write(
                    f"[#ffaa00]Step 2:[/] No merged.img found in {base_dir}/. "
                    "Run step 1 first, or enter the path manually on the Carve screen."
                )
            self.app.push_screen("carve")

        elif event.button.id == "btn-step3":
            carved_dir = os.path.join(base_dir, "carved_images")
            if os.path.isdir(carved_dir):
                log.write(f"[bold]Step 3:[/] Checking files in {carved_dir}/")
            else:
                log.write(
                    f"[#ffaa00]Step 3:[/] No carved_images/ found. "
                    "Run step 2 first, or enter the path manually."
                )
            self.app.push_screen("check")

        elif event.button.id == "btn-step4":
            log.write("[bold]Step 4:[/] Opening Repair...")
            self.app.push_screen("repair")

    def _update_step_description(self, step_idx: int) -> None:
        if 0 <= step_idx < len(STEPS):
            name, desc = STEPS[step_idx]
            self.query_one("#step-description", Static).update(
                f"  [bold]{name}[/]: {desc}\n"
            )
