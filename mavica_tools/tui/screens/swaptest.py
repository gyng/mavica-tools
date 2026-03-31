"""Swap test screen — cross-camera test tracker."""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, Button, DataTable, RichLog
from textual.containers import Horizontal

from mavica_tools.swaptest import load_db, save_db, DEFAULT_DB


class SwapTestScreen(Screen):
    """Interactive cross-camera swap test matrix."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #ffaa00]Cross-Camera Swap Test[/]  "
            "[dim]Isolate faulty camera, disk, or drive[/]\n",
            id="title-bar",
        )
        yield Static(
            "  [dim]Test each camera+disk combo to find the culprit.[/]\n"
        )
        yield Static("  [bold]Cameras[/]")
        with Horizontal(classes="input-row"):
            yield Input(
                placeholder="Cameras (comma-separated): FD7-A, FD7-B, FD88",
                id="cameras-input",
            )
        yield Static("  [bold]Disks[/]")
        with Horizontal(classes="input-row"):
            yield Input(
                placeholder="Disks (comma-separated): Disk-1, Disk-2, Disk-3",
                id="disks-input",
            )
        with Horizontal(classes="button-row"):
            yield Button("Setup / Refresh", variant="success", id="btn-setup")
            yield Button("Load Saved", variant="default", id="btn-load")
        yield DataTable(id="matrix-table")
        yield Static("\n  [bold]Log a result:[/]", classes="section-title")
        with Horizontal(classes="input-row"):
            yield Input(placeholder="Camera name", id="log-camera")
            yield Input(placeholder="Disk label", id="log-disk")
        yield Static(
            "  [dim]OK = all photos transferred  |  Partial = some corrupt  |  Fail = can't read disk[/]"
        )
        with Horizontal(classes="button-row"):
            yield Button("OK", variant="success", id="btn-ok")
            yield Button("Partial", variant="warning", id="btn-partial")
            yield Button("Fail", variant="error", id="btn-fail")
        yield Static("", id="analysis")
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self._db = {"cameras": [], "disks": [], "tests": []}
        self._db_path = DEFAULT_DB
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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Pre-fill the camera input when a matrix row is selected."""
        cameras = self._db.get("cameras", [])
        if event.cursor_row < len(cameras):
            self.query_one("#log-camera", Input).value = cameras[event.cursor_row]

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
            log.write(f"Loaded: {len(self._db.get('tests', []))} test(s)")
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
            self.notify("Enter both camera and disk names", severity="warning")
            return

        from datetime import datetime
        self._db["tests"].append({
            "camera": camera, "disk": disk, "result": result,
            "notes": "", "timestamp": datetime.now().isoformat(),
        })
        save_db(self._db, self._db_path)

        symbol = {"ok": "[green]OK[/]", "partial": "[#ffaa00]PARTIAL[/]", "fail": "[red]FAIL[/]"}
        log = self.query_one("#log", RichLog)
        log.write(f"  Logged: {symbol.get(result, result)} {camera} + {disk}")

        # Clear inputs for next entry
        self.query_one("#log-camera", Input).value = ""
        self.query_one("#log-disk", Input).value = ""
        self._refresh_matrix()

    def _refresh_matrix(self) -> None:
        cameras = self._db.get("cameras", [])
        disks = self._db.get("disks", [])
        tests = self._db.get("tests", [])
        if not cameras or not disks:
            return

        table = self.query_one("#matrix-table", DataTable)
        table.clear(columns=True)
        table.add_column("Camera \\ Disk", key="camera")
        table.cursor_type = "row"
        for disk in disks:
            table.add_column(disk, key=disk)

        matrix = {}
        for t in tests:
            matrix[(t["camera"], t["disk"])] = t["result"]

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

        self._analyze(cameras, disks, matrix)

    def _analyze(self, cameras, disks, matrix) -> None:
        analysis = self.query_one("#analysis", Static)
        lines = []
        tested = len(matrix)
        total = len(cameras) * len(disks)
        lines.append(f"\n  [bold]Progress:[/] {tested}/{total} tested")

        if not matrix:
            analysis.update("\n".join(lines))
            return

        all_ok = all(r == "ok" for r in matrix.values())
        if all_ok and tested == total:
            lines.append(
                "\n  [green bold]All combinations passed![/] "
                "The issue may be with your PC floppy drive.\n"
                "  Try a different USB floppy drive or an internal drive."
            )
            analysis.update("\n".join(lines))
            return

        for camera in cameras:
            cam_results = [matrix.get((camera, d)) for d in disks if (camera, d) in matrix]
            cam_fails = sum(1 for r in cam_results if r in ("partial", "fail"))
            cam_total = len(cam_results)
            if cam_total >= 2 and cam_fails == cam_total:
                lines.append(
                    f"\n  [red bold]>>> ALL disks fail with {camera}[/]\n"
                    "      Likely bad write head. Clean with 99% IPA."
                )
            elif cam_fails > 0:
                lines.append(f"  {camera}: {cam_fails}/{cam_total} failures")

        for disk in disks:
            disk_results = [matrix.get((c, disk)) for c in cameras if (c, disk) in matrix]
            disk_fails = sum(1 for r in disk_results if r in ("partial", "fail"))
            disk_total = len(disk_results)
            if disk_total >= 2 and disk_fails == disk_total:
                lines.append(
                    f"\n  [red bold]>>> ALL cameras fail with {disk}[/]\n"
                    "      This disk is likely bad. Replace it."
                )
            elif disk_fails > 0:
                lines.append(f"  {disk}: {disk_fails}/{disk_total} failures")

        if tested < total:
            missing = [f"{c}+{d}" for c in cameras for d in disks if (c, d) not in matrix]
            lines.append(f"\n  [dim]Remaining: {', '.join(missing)}[/]")

        analysis.update("\n".join(lines))
