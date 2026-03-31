"""Troubleshooting wizard — interactive diagnostic for floppy issues.

Walks the user through a decision tree to identify whether the problem
is the camera, the disk, or the PC floppy drive.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, RichLog
from textual.containers import Horizontal, Vertical


# Decision tree nodes
# Each node: (question, [(answer_text, next_node_or_result), ...])
TREE = {
    "start": {
        "question": (
            "Do your Mavica photos show on the camera's LCD\n"
            "  but fail to transfer to your PC?"
        ),
        "answers": [
            ("Yes — shows on camera, fails on PC", "pc_vs_camera"),
            ("No — photos look bad on the camera too", "camera_issue"),
            ("Not sure — I can't check on camera", "pc_drive_test"),
        ],
    },
    "pc_vs_camera": {
        "question": (
            "Have you tried reading the floppy in a\n"
            "  different PC floppy drive (USB or internal)?"
        ),
        "answers": [
            ("Yes — works on the other drive", "result_pc_drive"),
            ("Yes — fails on both drives", "head_or_disk"),
            ("No — I only have one drive", "try_multipass"),
        ],
    },
    "head_or_disk": {
        "question": (
            "Do you have another floppy disk you can test?\n"
            "  Try a known-good disk with photos from the same camera."
        ),
        "answers": [
            ("Other disks read fine", "result_bad_disk"),
            ("Other disks also fail", "result_dirty_head"),
            ("I only have one disk", "try_multipass"),
        ],
    },
    "camera_issue": {
        "question": (
            "Do photos from your OTHER Mavica camera\n"
            "  (on the same disk) also look bad?"
        ),
        "answers": [
            ("Yes — both cameras produce bad images", "result_bad_disk"),
            ("No — only one camera's photos are bad", "result_dirty_head"),
            ("I only have one camera", "result_dirty_head"),
        ],
    },
    "pc_drive_test": {
        "question": (
            "Can your PC read other floppy disks\n"
            "  (non-Mavica, like DOS formatted disks)?"
        ),
        "answers": [
            ("Yes — other disks read fine", "head_or_disk"),
            ("No — PC can't read any floppy", "result_pc_drive"),
            ("I don't have other disks to test", "try_multipass"),
        ],
    },
    "try_multipass": {
        "question": (
            "Let's try a multi-pass read to recover what we can.\n"
            "  This reads the disk multiple times and merges the best sectors.\n"
            "  It often recovers data that a single read misses."
        ),
        "answers": [
            ("Open Multi-Pass Read tool", "action_multipass"),
            ("Open Swap Test tool (I have multiple cameras)", "action_swaptest"),
            ("Just tell me what to clean", "result_clean_everything"),
        ],
    },
    # Results
    "result_pc_drive": {
        "result": (
            "[bold #ffaa00]Likely cause: Your PC floppy drive[/]\n\n"
            "  The Mavica writes fine, but your PC drive can't read it.\n\n"
            "  [bold]Try:[/]\n"
            "  1. Clean the PC drive's read head (IPA + cotton swab)\n"
            "  2. Try a different USB floppy drive\n"
            "  3. Try an internal floppy drive if available\n"
            "  4. Use the Multi-Pass Read tool — multiple reads may recover data\n\n"
            "  [dim]The TEAC FD-05HGS and Sony MPF920 are reliable USB drives.[/]"
        ),
    },
    "result_bad_disk": {
        "result": (
            "[bold #ffaa00]Likely cause: Bad floppy disk[/]\n\n"
            "  The disk media is degraded or damaged.\n\n"
            "  [bold]Try:[/]\n"
            "  1. Multi-Pass Read — read it 5-10 times to recover max sectors\n"
            "  2. Use JPEG Carve to extract what's readable\n"
            "  3. Use Repair to salvage partial images\n"
            "  4. Replace this disk — use new-old-stock (NOS) HD floppies\n\n"
            "  [dim]Store disks away from magnets, heat, and humidity.[/]"
        ),
    },
    "result_dirty_head": {
        "result": (
            "[bold #ffaa00]Likely cause: Dirty write head on your Mavica[/]\n\n"
            "  The camera's write head is dirty or misaligned.\n\n"
            "  [bold]Clean it:[/]\n"
            "  1. Get a 3.5\" floppy head cleaning disk (wet type)\n"
            "  2. Apply 99%% isopropyl alcohol (not 70%%!)\n"
            "  3. Insert into the Mavica and let it 'read' for 10-15 seconds\n"
            "  4. Alternatively, gently clean the head with a cotton swab + IPA\n\n"
            "  [bold]After cleaning:[/]\n"
            "  Format a fresh floppy IN THE CAMERA, take test photos,\n"
            "  then read on PC to verify.\n\n"
            "  [dim]Clean every 10-15 disks for preventive maintenance.[/]"
        ),
    },
    "result_clean_everything": {
        "result": (
            "[bold #ffaa00]When in doubt, clean everything[/]\n\n"
            "  [bold]Camera head:[/]\n"
            "  - Use a wet-type 3.5\" cleaning disk with 99%% IPA\n"
            "  - Or cotton swab + IPA directly on the head\n\n"
            "  [bold]PC floppy drive:[/]\n"
            "  - Same cleaning disk method\n"
            "  - Or open the drive and swab the head\n\n"
            "  [bold]Then test:[/]\n"
            "  1. Format a fresh floppy in the Mavica\n"
            "  2. Take 5 test photos\n"
            "  3. Read on PC\n"
            "  4. If still failing, try the Swap Test tool with\n"
            "     multiple cameras and disks to isolate the problem\n\n"
            "  [dim]Use 99%% IPA only — 70%% has too much water.[/]"
        ),
    },
}


class TroubleshootScreen(Screen):
    """Interactive troubleshooting wizard."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Troubleshooting Wizard[/]  "
            "[dim]Find out what's wrong with your floppy setup[/]\n",
            id="title-bar",
        )
        yield Static("", id="question-text")
        yield Vertical(id="answer-buttons")
        yield Static("", id="result-text")
        with Horizontal(classes="button-row"):
            yield Button("Start Over", variant="default", id="btn-restart")
            yield Button("Re-test After Cleaning", variant="warning", id="btn-retest", disabled=True)
            yield Button("Open Swap Test", variant="default", id="btn-swaptest", disabled=True)
            yield Button("Open Multi-Pass Read", variant="success", id="btn-multipass", disabled=True)
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self._history = []
        self._show_node("start")

    def _show_node(self, node_id: str) -> None:
        self._current_node = node_id
        node = TREE.get(node_id)

        question_widget = self.query_one("#question-text", Static)
        result_widget = self.query_one("#result-text", Static)
        buttons_container = self.query_one("#answer-buttons", Vertical)

        # Clear previous answer buttons
        for child in list(buttons_container.children):
            child.remove()

        if "result" in node:
            # Show result
            question_widget.update("")
            result_widget.update(f"\n{node['result']}")
            self.query_one("#btn-retest", Button).disabled = False
            self.query_one("#btn-swaptest", Button).disabled = False
            self.query_one("#btn-multipass", Button).disabled = False
        elif "question" in node:
            # Show question with answer buttons
            result_widget.update("")
            question_widget.update(
                f"\n  [bold]{node['question']}[/]\n"
            )
            for i, (text, _target) in enumerate(node["answers"]):
                btn = Button(text, variant="default", id=f"btn-answer-{i}")
                buttons_container.mount(btn)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-restart":
            self._history = []
            self._show_node("start")
            self.query_one("#btn-retest", Button).disabled = True
            self.query_one("#btn-swaptest", Button).disabled = True
            self.query_one("#btn-multipass", Button).disabled = True
        elif event.button.id == "btn-retest":
            # Go back to beginning but with a note
            log = self.query_one("#log", RichLog)
            log.write("\n[bold #33ff33]Re-testing after cleaning...[/]")
            self._show_node("start")
            self.query_one("#btn-retest", Button).disabled = True
        elif event.button.id == "btn-swaptest":
            self.app.push_screen("swaptest")
        elif event.button.id == "btn-multipass":
            self.app.push_screen("multipass")
        elif event.button.id and event.button.id.startswith("btn-answer-"):
            idx = int(event.button.id.split("-")[-1])
            node = TREE[self._current_node]
            _text, target = node["answers"][idx]
            self._history.append(self._current_node)

            # Handle action targets
            if target == "action_multipass":
                self.app.push_screen("multipass")
            elif target == "action_swaptest":
                self.app.push_screen("swaptest")
            else:
                self._show_node(target)

            log = self.query_one("#log", RichLog)
            log.write(f"[dim]> {_text}[/]")
