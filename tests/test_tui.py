"""Comprehensive TUI tests for mavica-tools using Textual's headless pilot API."""

import os
import tempfile
from unittest.mock import patch

import pytest

from textual.widgets import DataTable, Input, Button, OptionList, Static, RichLog

from mavica_tools.tui.app import MavicaApp
from mavica_tools.tui.screens.home import HomeScreen
from mavica_tools.tui.screens.check import CheckScreen
from mavica_tools.tui.screens.carve import CarveScreen
from mavica_tools.tui.screens.repair import RepairScreen
from mavica_tools.tui.screens.multipass import MultipassScreen
from mavica_tools.tui.screens.swaptest import SwapTestScreen
from mavica_tools.tui.screens.import_workflow import ImportWorkflowScreen
from mavica_tools.tui.screens.recovery_workflow import RecoveryWorkflowScreen
from mavica_tools.tui.widgets.defrag_map import DefragMap


# ---------------------------------------------------------------------------
# Helper: push a named screen and wait for it to mount
# ---------------------------------------------------------------------------


async def _push_and_wait(app, pilot, screen_name):
    """Push a screen by name and wait for it to mount."""
    await app.push_screen(screen_name)
    await pilot.pause()


# ---------------------------------------------------------------------------
# 1. App launches and shows home screen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_app_launches_and_shows_home_screen():
    """The app should mount and display the HomeScreen on startup."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


# ---------------------------------------------------------------------------
# 2. Home screen has all 6 tool options visible
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_screen_has_all_tool_options():
    """The OptionList on the home screen should contain 6 entries."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        option_list = app.screen.query_one("#tool-list", OptionList)
        assert option_list.option_count == 21  # 17 tools + 4 section headers


# ---------------------------------------------------------------------------
# 3. Pressing keys 1-5 and w navigates to the correct screen
# ---------------------------------------------------------------------------


_KEY_SCREEN_MAP = [
    ("1", ImportWorkflowScreen),
    ("r", RecoveryWorkflowScreen),
    ("m", MultipassScreen),
    ("c", CarveScreen),
    ("k", CheckScreen),
    ("p", RepairScreen),
    ("w", SwapTestScreen),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("key,expected_screen_cls", _KEY_SCREEN_MAP)
async def test_key_navigates_to_correct_screen(key, expected_screen_cls):
    """Pressing a number key or 'w' on the home screen pushes the right screen."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()
        assert isinstance(app.screen, expected_screen_cls), (
            f"Expected {expected_screen_cls.__name__} but got {type(app.screen).__name__}"
        )


# ---------------------------------------------------------------------------
# 4. Each screen can be pushed and has expected widgets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_screen_has_expected_widgets():
    """CheckScreen should contain #source-path Input, #btn-check Button, #results-table DataTable."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "check")
        assert isinstance(app.screen, CheckScreen)
        assert isinstance(app.screen.query_one("#source-path"), Input)
        assert isinstance(app.screen.query_one("#btn-check"), Button)
        assert isinstance(app.screen.query_one("#results-table"), DataTable)


@pytest.mark.asyncio
async def test_carve_screen_has_expected_widgets():
    """CarveScreen should contain #image-path Input and #btn-carve Button."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "carve")
        assert isinstance(app.screen, CarveScreen)
        assert isinstance(app.screen.query_one("#image-path"), Input)
        assert isinstance(app.screen.query_one("#btn-carve"), Button)


@pytest.mark.asyncio
async def test_repair_screen_has_expected_widgets():
    """RepairScreen should contain #source-path Input and #btn-repair Button."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "repair")
        assert isinstance(app.screen, RepairScreen)
        assert isinstance(app.screen.query_one("#source-path"), Input)
        assert isinstance(app.screen.query_one("#btn-repair"), Button)


@pytest.mark.asyncio
async def test_multipass_screen_has_expected_widgets():
    """MultipassScreen should have #device-path Input, #btn-read Button, DefragMap."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "multipass")
        assert isinstance(app.screen, MultipassScreen)
        assert isinstance(app.screen.query_one("#device-path"), Input)
        assert isinstance(app.screen.query_one("#btn-read"), Button)
        assert isinstance(app.screen.query_one("#defrag-map"), DefragMap)


@pytest.mark.asyncio
async def test_swaptest_screen_has_expected_widgets():
    """SwapTestScreen should have cameras/disks inputs, setup button, matrix table."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "swaptest")
        assert isinstance(app.screen, SwapTestScreen)
        assert isinstance(app.screen.query_one("#cameras-input"), Input)
        assert isinstance(app.screen.query_one("#disks-input"), Input)
        assert isinstance(app.screen.query_one("#btn-setup"), Button)
        assert isinstance(app.screen.query_one("#matrix-table"), DataTable)


@pytest.mark.asyncio
async def test_import_workflow_has_expected_widgets():
    """ImportWorkflowScreen should have key buttons."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "import_workflow")
        assert isinstance(app.screen, ImportWorkflowScreen)
        for btn_id in ("#btn-browse", "#btn-import", "#btn-import-all"):
            btn = app.screen.query_one(btn_id, Button)
            assert btn is not None


# ---------------------------------------------------------------------------
# 5. Pressing Escape returns to previous screen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escape_returns_to_previous_screen():
    """Pressing Escape on a tool screen should pop back to the home screen."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        # Navigate to check screen
        await pilot.press("k")
        await pilot.pause()
        assert isinstance(app.screen, CheckScreen)
        # Press Escape
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_escape_from_multiple_screens():
    """Escape should work consistently across different tool screens."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        # Navigate to carve screen via key 2
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, CarveScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


# ---------------------------------------------------------------------------
# 6. Check screen: entering a path and clicking Check runs the check workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_screen_run_check_with_valid_path():
    """Entering a path and pressing the Check button should invoke the check worker."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        # Navigate via key to ensure proper focus/layout
        await pilot.press("k")
        await pilot.pause()

        # Create a temporary JPEG file
        with tempfile.TemporaryDirectory() as tmp_dir:
            jpeg_path = os.path.join(tmp_dir, "test.jpg")
            # Minimal JPEG: SOI + some data + EOI
            with open(jpeg_path, "wb") as f:
                f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9")

            # Set the path into the input
            source_input = app.screen.query_one("#source-path", Input)
            source_input.value = jpeg_path

            # Trigger the check via the action (avoids click coordinate issues)
            app.screen.action_run_check()
            # Allow the worker to run
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            # Verify the results table has at least one row
            table = app.screen.query_one("#results-table", DataTable)
            assert table.row_count >= 1


@pytest.mark.asyncio
async def test_check_screen_empty_path_shows_notification():
    """Clicking Check without entering a path should not crash."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32), notifications=True) as pilot:
        await pilot.pause()
        await pilot.press("k")
        await pilot.pause()

        # Trigger check with empty path via action
        app.screen.action_run_check()
        await pilot.pause()
        # Should not crash; the screen should still be CheckScreen
        assert isinstance(app.screen, CheckScreen)


@pytest.mark.asyncio
async def test_check_screen_no_files_found():
    """Checking a path with no JPEGs should log a message without crashing."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("k")
        await pilot.pause()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_input = app.screen.query_one("#source-path", Input)
            source_input.value = tmp_dir

            app.screen.action_run_check()
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            # Table should still be empty
            table = app.screen.query_one("#results-table", DataTable)
            assert table.row_count == 0


# ---------------------------------------------------------------------------
# 7. Swaptest screen: setup with cameras/disks populates the matrix table
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_swaptest_setup_populates_matrix():
    """Entering cameras and disks, then clicking Setup, should populate the matrix table."""
    app = MavicaApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test_swap.json")

            # Navigate to swaptest via key
            await pilot.press("w")
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, SwapTestScreen)
            # Override the db_path on the screen instance to use temp dir
            screen._db_path = db_path

            # Set camera and disk inputs
            cameras_input = app.screen.query_one("#cameras-input", Input)
            disks_input = app.screen.query_one("#disks-input", Input)
            cameras_input.value = "FD7-A, FD7-B"
            disks_input.value = "Disk-1, Disk-2, Disk-3"

            # Trigger setup via the screen's method directly
            screen._do_setup()
            await pilot.pause()

            # The matrix table should now have columns and rows
            table = app.screen.query_one("#matrix-table", DataTable)
            assert table.row_count == 2  # 2 cameras
            # Columns: "Camera \ Disk" + 3 disk columns = 4
            assert len(table.columns) == 4


@pytest.mark.asyncio
async def test_swaptest_empty_inputs_shows_notification():
    """Clicking Setup without entering cameras/disks should not crash."""
    app = MavicaApp()
    async with app.run_test(size=(120, 40), notifications=True) as pilot:
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()

        # Trigger setup with empty inputs
        app.screen._do_setup()
        await pilot.pause()
        # Should not crash
        assert isinstance(app.screen, SwapTestScreen)


# ---------------------------------------------------------------------------
# 8. Home screen OptionList selection navigates correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_key_binding_navigates_to_import():
    """Pressing '1' should navigate to ImportWorkflowScreen."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
        assert isinstance(app.screen, ImportWorkflowScreen)


@pytest.mark.asyncio
async def test_key_binding_navigates_to_export():
    """Pressing 'e' should navigate to ExportScreen."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        from mavica_tools.tui.screens.export_screen import ExportScreen
        assert isinstance(app.screen, ExportScreen)


@pytest.mark.asyncio
async def test_key_binding_navigates_to_gps():
    """Pressing 'g' should navigate to GpsScreen."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        from mavica_tools.tui.screens.gps_screen import GpsScreen
        assert isinstance(app.screen, GpsScreen)


# ---------------------------------------------------------------------------
# Additional integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_key_binding_returns_home():
    """Pressing 'h' should return to home screen from any tool screen."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        # Navigate to check screen
        await pilot.press("k")
        await pilot.pause()
        assert isinstance(app.screen, CheckScreen)
        # Press 'h' to go home — need to ensure focus is not on an Input
        # Move focus away from input first by pressing tab until we leave inputs
        # Actually, use the app action directly
        app.action_go_home()
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_check_screen_results_table_has_correct_columns():
    """The results DataTable in CheckScreen should have the expected columns."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "check")
        table = app.screen.query_one("#results-table", DataTable)
        column_labels = [col.label.plain for col in table.columns.values()]
        assert column_labels == ["Status", "Filename", "Size", "Dims", "Issues"]


@pytest.mark.asyncio
async def test_recovery_workflow_step_buttons():
    """Clicking step buttons in recovery workflow should navigate correctly."""
    app = MavicaApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, RecoveryWorkflowScreen)

        # Click Multi-Pass Read -> should push MultipassScreen
        await pilot.click("#btn-multipass")
        await pilot.pause()
        assert isinstance(app.screen, MultipassScreen)

        # Go back
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, RecoveryWorkflowScreen)

        # One-Click Recover -> RecoverScreen
        await pilot.click("#btn-recover")
        await pilot.pause()
        from mavica_tools.tui.screens.recover_screen import RecoverScreen
        assert isinstance(app.screen, RecoverScreen)


@pytest.mark.asyncio
async def test_screen_stack_depth():
    """Navigating from home to a tool should result in a screen stack of depth 3."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        # Stack: [default, home]
        assert len(app.screen_stack) == 2
        await pilot.press("1")
        await pilot.pause()
        # Stack: [default, home, multipass]
        assert len(app.screen_stack) == 3


@pytest.mark.asyncio
async def test_multipass_screen_has_default_device_path():
    """The multipass screen device-path input should have a default value."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        device_input = app.screen.query_one("#device-path", Input)
        assert len(device_input.value) > 0


@pytest.mark.asyncio
async def test_carve_screen_has_output_dir_default():
    """The carve screen should have a default output directory value."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        output_input = app.screen.query_one("#output-dir", Input)
        assert output_input.value == "carved_images"


@pytest.mark.asyncio
async def test_repair_screen_has_output_dir_default():
    """The repair screen should have a default output directory value."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        output_input = app.screen.query_one("#output-dir", Input)
        assert output_input.value == "repaired"
