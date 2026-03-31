"""Swap test screen — cross-camera test tracker."""

import os
import tempfile

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, DataTable, RichLog
from textual.containers import Horizontal
from textual.worker import get_current_worker

from mavica_tools.swaptest import load_db, save_db, DEFAULT_DB


class SwapTestScreen(Screen):
    """Interactive cross-camera swap test matrix."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #ffaa00]Cross-Camera Swap Test[/]\n", id="title-bar")
        yield Static(
            "  [dim]Test each camera+disk combo to isolate the faulty component.[/]\n"
        )
        with Horizontal():
            yield Input(
                placeholder="Cameras (comma-separated): FD7-A, FD7-B, FD88",
                id="cameras-input",
            )
        with Horizontal():
            yield Input(
                placeholder="Disks (comma-separated): Disk-1, Disk-2, Disk-3",
                id="disks-input",
            )
        with Horizontal():
            yield Button("Setup / Refresh", variant="success", id="btn-setup")
            yield Button("Load Saved", variant="default", id="btn-load")
        yield DataTable(id="matrix-table")
        with Horizontal():
            yield Input(placeholder="Camera", id="log-camera")
            yield Input(placeholder="Disk", id="log-disk")
            yield Button("OK", variant="success", id="btn-ok")
            yield Button("Partial", variant="warning", id="btn-partial")
            yield Button("Fail", variant="error", id="btn-fail")
        yield Static("", id="analysis")
        yield RichLog(id="log", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self._db = {"cameras": [], "disks": [], "tests": []}
        self._db_path = DEFAULT_DB
        # Try loading existing DB
        if os.path.exists(self._db_path):
            self._load_existing()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-setup":
            self._do_setup()
        elif event.button.id == "btn-load":
            self._load_existing()
        elif event.button.id in ("btn-ok", "btn-partial", "btn-fail"):
            result_map = {"btn-ok": "ok", "btn-partial": "partial", "btn-fail": "fail"}
            self._log_result(result_map[event.button.id])

    def _do_setup(self) -> None:
        cameras_str = self.query_one("#cameras-input", Input).value.strip()
        disks_str = self.query_one("#disks-input", Input).value.strip()

        if not cameras_str or not disks_str:
            self.notify("Enter camera names and disk labels", severity="warning")
            return

        cameras = [c.strip() for c in cameras_str.split(",") if c.strip()]
        disks = [d.strip() for d in disks_str.split(",") if d.strip()]

        self._db["cameras"] = cameras
        self._db["disks"] = disks
        save_db(self._db, self._db_path)

        log = self.query_one("#log", RichLog)
        log.write(f"Setup: {len(cameras)} camera(s), {len(disks)} disk(s)")
        log.write(f"Test plan: {len(cameras) * len(disks)} combinations\n")

        self._refresh_matrix()

    def _load_existing(self) -> None:
        if os.path.exists(self._db_path):
            self._db = load_db(self._db_path)
            log = self.query_one("#log", RichLog)
            log.write(f"Loaded {self._db_path}: {len(self._db.get('tests', []))} test(s)")

            # Fill input fields
            if self._db.get("cameras"):
                self.query_one("#cameras-input", Input).value = ", ".join(self._db["cameras"])
            if self._db.get("disks"):
                self.query_one("#disks-input", Input).value = ", ".join(self._db["disks"])

            self._refresh_matrix()
        else:
            self.notify("No saved test data found", severity="warning")

    def _log_result(self, result: str) -> None:
        camera = self.query_one("#log-camera", Input).value.strip()
        disk = self.query_one("#log-disk", Input).value.strip()

        if not camera or not disk:
            self.notify("Enter camera and disk names", severity="warning")
            return

        from datetime import datetime

        entry = {
            "camera": camera,
            "disk": disk,
            "result": result,
            "notes": "",
            "timestamp": datetime.now().isoformat(),
        }
        self._db["tests"].append(entry)
        save_db(self._db, self._db_path)

        symbol = {"ok": "[green]OK[/]", "partial": "[#ffaa00]PARTIAL[/]", "fail": "[red]FAIL[/]"}
        log = self.query_one("#log", RichLog)
        log.write(f"  Logged: {symbol.get(result, result)} {camera} + {disk}")

        self._refresh_matrix()

    def _refresh_matrix(self) -> None:
        cameras = self._db.get("cameras", [])
        disks = self._db.get("disks", [])
        tests = self._db.get("tests", [])

        if not cameras or not disks:
            return

        table = self.query_one("#matrix-table", DataTable)
        table.clear(columns=True)

        # Add columns
        table.add_column("Camera \\ Disk", key="camera")
        for disk in disks:
            table.add_column(disk, key=disk)

        # Build result matrix
        matrix = {}
        for t in tests:
            matrix[(t["camera"], t["disk"])] = t["result"]

        # Add rows
        for camera in cameras:
            row = [f"[bold]{camera}[/]"]
            for disk in disks:
                result = matrix.get((camera, disk))
                if result == "ok":
                    row.append("[green] . [/]")
                elif result == "partial":
                    row.append("[#ffaa00] ? [/]")
                elif result == "fail":
                    row.append("[red] X [/]")
                else:
                    row.append("[dim] - [/]")
            table.add_row(*row)

        # Run analysis
        self._analyze(cameras, disks, matrix)

    def _analyze(self, cameras, disks, matrix) -> None:
        analysis = self.query_one("#analysis", Static)
        lines = []

        tested = len(matrix)
        total = len(cameras) * len(disks)
        lines.append(f"  [bold]Progress:[/] {tested}/{total} tested")

        if not matrix:
            analysis.update("\n".join(lines))
            return

        all_ok = all(r == "ok" for r in matrix.values())
        if all_ok and tested == total:
            lines.append(
                "\n  [green]All combinations passed![/] "
                "The issue may be with your PC floppy drive."
            )
            analysis.update("\n".join(lines))
            return

        # Camera failures
        for camera in cameras:
            cam_results = [matrix.get((camera, d)) for d in disks if (camera, d) in matrix]
            cam_fails = sum(1 for r in cam_results if r in ("partial", "fail"))
            cam_total = len(cam_results)
            if cam_total >= 2 and cam_fails == cam_total:
                lines.append(
                    f"\n  [red bold]>>> ALL disks fail with {camera}[/] — "
                    "likely bad write head. Clean with IPA."
                )

        # Disk failures
        for disk in disks:
            disk_results = [matrix.get((c, disk)) for c in cameras if (c, disk) in matrix]
            disk_fails = sum(1 for r in disk_results if r in ("partial", "fail"))
            disk_total = len(disk_results)
            if disk_total >= 2 and disk_fails == disk_total:
                lines.append(
                    f"\n  [red bold]>>> ALL cameras fail with {disk}[/] — "
                    "this disk is likely bad. Replace it."
                )

        if tested < total:
            missing = []
            for c in cameras:
                for d in disks:
                    if (c, d) not in matrix:
                        missing.append(f"{c}+{d}")
            lines.append(f"\n  [dim]Remaining: {', '.join(missing)}[/]")

        analysis.update("\n".join(lines))
