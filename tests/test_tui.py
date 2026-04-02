"""Comprehensive TUI tests for mavica-tools using Textual's headless pilot API."""

import os
import tempfile

import pytest
from textual.widgets import Button, DataTable, Input, OptionList

from mavica_tools.tui.app import MavicaApp
from mavica_tools.tui.screens.home import HomeScreen
from mavica_tools.tui.screens.import_workflow import ImportWorkflowScreen
from mavica_tools.tui.screens.multipass import MultipassScreen
from mavica_tools.tui.screens.recover_image_screen import RecoverImageScreen
from mavica_tools.tui.screens.repair import RepairScreen
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
# 2. Home screen has all tool options visible
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_screen_has_all_tool_options():
    """The OptionList on the home screen should contain all entries."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        option_list = app.screen.query_one("#tool-list", OptionList)
        # 3 section headers + 9 enabled tools + 1 disabled (flux) = 13
        assert option_list.option_count == 13


# ---------------------------------------------------------------------------
# 3. Pressing shortcut keys navigates to the correct screen
# ---------------------------------------------------------------------------


_KEY_SCREEN_MAP = [
    ("1", ImportWorkflowScreen),
    ("7", MultipassScreen),
    ("8", RecoverImageScreen),
    ("9", RepairScreen),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("key,expected_screen_cls", _KEY_SCREEN_MAP)
async def test_key_navigates_to_correct_screen(key, expected_screen_cls):
    """Pressing a shortcut key on the home screen pushes the right screen."""
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
async def test_repair_screen_has_expected_widgets():
    """RepairScreen should contain check and repair buttons, results table."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "repair")
        assert isinstance(app.screen, RepairScreen)
        assert isinstance(app.screen.query_one("#source-path"), Input)
        assert isinstance(app.screen.query_one("#btn-check"), Button)
        assert isinstance(app.screen.query_one("#btn-repair"), Button)
        assert isinstance(app.screen.query_one("#results-table"), DataTable)


@pytest.mark.asyncio
async def test_recover_image_screen_has_expected_widgets():
    """RecoverImageScreen should contain #image-path Input, #btn-extract Button, DataTable."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "recover_image")
        assert isinstance(app.screen, RecoverImageScreen)
        assert isinstance(app.screen.query_one("#image-path"), Input)
        assert isinstance(app.screen.query_one("#btn-extract"), Button)
        assert isinstance(app.screen.query_one("#results-table"), DataTable)
        assert isinstance(app.screen.query_one("#defrag-map"), DefragMap)


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
async def test_import_workflow_has_expected_widgets():
    """ImportWorkflowScreen should have key buttons."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "import_workflow")
        assert isinstance(app.screen, ImportWorkflowScreen)
        for btn_id in ("#btn-browse-out", "#btn-import", "#btn-stop"):
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
        await pilot.press("9")
        await pilot.pause()
        assert isinstance(app.screen, RepairScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_escape_from_multiple_screens():
    """Escape should work consistently across different tool screens."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("8")
        await pilot.pause()
        assert isinstance(app.screen, RecoverImageScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


# ---------------------------------------------------------------------------
# 6. Repair screen: check + repair workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_screen_check_with_valid_path():
    """Entering a path and clicking Check should populate the results table."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("9")
        await pilot.pause()

        with tempfile.TemporaryDirectory() as tmp_dir:
            jpeg_path = os.path.join(tmp_dir, "test.jpg")
            with open(jpeg_path, "wb") as f:
                f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9")

            source_input = app.screen.query_one("#source-path", Input)
            source_input.value = jpeg_path

            app.screen.action_run_check()
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            table = app.screen.query_one("#results-table", DataTable)
            assert table.row_count >= 1


@pytest.mark.asyncio
async def test_repair_screen_empty_path_shows_notification():
    """Clicking Check without entering a path should not crash."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32), notifications=True) as pilot:
        await pilot.pause()
        await pilot.press("9")
        await pilot.pause()

        app.screen.action_run_check()
        await pilot.pause()
        assert isinstance(app.screen, RepairScreen)


@pytest.mark.asyncio
async def test_repair_screen_no_files_found():
    """Checking a path with no JPEGs should not crash."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("9")
        await pilot.pause()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_input = app.screen.query_one("#source-path", Input)
            source_input.value = tmp_dir

            app.screen.action_run_check()
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            table = app.screen.query_one("#results-table", DataTable)
            assert table.row_count == 0


# ---------------------------------------------------------------------------
# 7. Home screen OptionList selection navigates correctly
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
async def test_key_binding_navigates_to_gps():
    """Pressing '3' should navigate to GpsScreen."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("3")
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
        await pilot.press("9")
        await pilot.pause()
        assert isinstance(app.screen, RepairScreen)
        app.action_go_home()
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_repair_screen_results_table_has_correct_columns():
    """The results DataTable in RepairScreen should have the check-mode columns."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await _push_and_wait(app, pilot, "repair")
        table = app.screen.query_one("#results-table", DataTable)
        column_labels = [col.label.plain for col in table.columns.values()]
        assert column_labels == ["Status", "Filename", "Size", "Issues"]


@pytest.mark.asyncio
async def test_screen_stack_depth():
    """Navigating from home to a tool should result in a screen stack of depth 3."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        assert len(app.screen_stack) == 2
        await pilot.press("1")
        await pilot.pause()
        assert len(app.screen_stack) == 3


@pytest.mark.asyncio
async def test_multipass_screen_has_default_device_path():
    """The multipass screen device-path input should have a default value."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("7")
        await pilot.pause()
        device_input = app.screen.query_one("#device-path", Input)
        assert len(device_input.value) > 0


@pytest.mark.asyncio
async def test_recover_image_screen_has_output_dir_default():
    """The recover image screen should have a default output directory value."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("8")
        await pilot.pause()
        output_input = app.screen.query_one("#output-dir", Input)
        assert output_input.value == "mavica_out/recovered"


@pytest.mark.asyncio
async def test_repair_screen_has_output_dir_default():
    """The repair screen should have a default output directory value."""
    app = MavicaApp()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("9")
        await pilot.pause()
        output_input = app.screen.query_one("#output-dir", Input)
        assert output_input.value == "mavica_out/repaired"
