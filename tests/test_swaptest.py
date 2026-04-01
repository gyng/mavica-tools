"""Tests for the cross-camera swap test tracker."""

import os
import tempfile

import pytest

from mavica_tools.swaptest import cmd_log, cmd_report, cmd_setup, cmd_status, load_db, save_db


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def db_path(tmp_dir):
    return os.path.join(tmp_dir, "test_db.json")


class FakeArgs:
    """Minimal args object to simulate argparse."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TestLoadSaveDb:
    def test_load_nonexistent_creates_default(self, db_path):
        db = load_db(db_path)
        assert db["cameras"] == []
        assert db["disks"] == []
        assert db["tests"] == []
        assert "created" in db

    def test_save_and_reload(self, db_path):
        db = {"cameras": ["FD7"], "disks": ["Disk-1"], "tests": [], "created": "2024-01-01"}
        save_db(db, db_path)

        loaded = load_db(db_path)
        assert loaded["cameras"] == ["FD7"]
        assert loaded["disks"] == ["Disk-1"]

    def test_roundtrip_preserves_tests(self, db_path):
        db = load_db(db_path)
        db["cameras"] = ["A", "B"]
        db["disks"] = ["D1"]
        db["tests"].append(
            {"camera": "A", "disk": "D1", "result": "ok", "notes": "", "timestamp": "t"}
        )
        save_db(db, db_path)

        loaded = load_db(db_path)
        assert len(loaded["tests"]) == 1
        assert loaded["tests"][0]["result"] == "ok"


class TestCmdSetup:
    def test_setup_with_args(self, db_path):
        db = load_db(db_path)
        args = FakeArgs(cameras="FD7-A, FD7-B, FD88", disks="Disk-1, Disk-2, Disk-3")
        cmd_setup(db, args)

        assert db["cameras"] == ["FD7-A", "FD7-B", "FD88"]
        assert db["disks"] == ["Disk-1", "Disk-2", "Disk-3"]

    def test_setup_strips_whitespace(self, db_path):
        db = load_db(db_path)
        args = FakeArgs(cameras="  A ,  B  ", disks=" D1 , D2 ")
        cmd_setup(db, args)

        assert db["cameras"] == ["A", "B"]
        assert db["disks"] == ["D1", "D2"]


class TestCmdLog:
    def test_log_with_args(self, db_path):
        db = load_db(db_path)
        db["cameras"] = ["FD7-A", "FD7-B"]
        db["disks"] = ["Disk-1", "Disk-2"]

        args = FakeArgs(camera="FD7-A", disk="Disk-1", result="ok", notes="clean read")
        cmd_log(db, args)

        assert len(db["tests"]) == 1
        assert db["tests"][0]["camera"] == "FD7-A"
        assert db["tests"][0]["disk"] == "Disk-1"
        assert db["tests"][0]["result"] == "ok"
        assert db["tests"][0]["notes"] == "clean read"

    def test_log_multiple_entries(self, db_path):
        db = load_db(db_path)
        db["cameras"] = ["A", "B"]
        db["disks"] = ["D1"]

        cmd_log(db, FakeArgs(camera="A", disk="D1", result="ok", notes=""))
        cmd_log(db, FakeArgs(camera="B", disk="D1", result="fail", notes="all corrupt"))

        assert len(db["tests"]) == 2
        assert db["tests"][0]["result"] == "ok"
        assert db["tests"][1]["result"] == "fail"

    def test_log_no_cameras_warns(self, db_path, capsys):
        db = load_db(db_path)
        args = FakeArgs(camera="X", disk="Y", result="ok", notes="")
        cmd_log(db, args)
        output = capsys.readouterr().out
        assert "setup" in output.lower()


class TestCmdReport:
    def _make_full_db(self, cameras, disks, results_map):
        """Helper to create a db with test results.

        results_map: dict of (camera, disk) -> "ok"/"partial"/"fail"
        """
        db = {"cameras": cameras, "disks": disks, "tests": [], "created": "t"}
        for (c, d), result in results_map.items():
            db["tests"].append(
                {
                    "camera": c,
                    "disk": d,
                    "result": result,
                    "notes": "",
                    "timestamp": "t",
                }
            )
        return db

    def test_all_ok_suggests_pc_drive(self, capsys):
        db = self._make_full_db(
            ["FD7-A", "FD7-B"],
            ["D1", "D2"],
            {
                ("FD7-A", "D1"): "ok",
                ("FD7-A", "D2"): "ok",
                ("FD7-B", "D1"): "ok",
                ("FD7-B", "D2"): "ok",
            },
        )
        cmd_report(db, FakeArgs())
        output = capsys.readouterr().out
        assert "PC floppy drive" in output

    def test_camera_failure_detected(self, capsys):
        db = self._make_full_db(
            ["FD7-A", "FD7-B"],
            ["D1", "D2"],
            {
                ("FD7-A", "D1"): "fail",
                ("FD7-A", "D2"): "fail",
                ("FD7-B", "D1"): "ok",
                ("FD7-B", "D2"): "ok",
            },
        )
        cmd_report(db, FakeArgs())
        output = capsys.readouterr().out
        assert "FD7-A" in output
        assert "bad write head" in output

    def test_disk_failure_detected(self, capsys):
        db = self._make_full_db(
            ["FD7-A", "FD7-B"],
            ["D1", "D2"],
            {
                ("FD7-A", "D1"): "ok",
                ("FD7-A", "D2"): "fail",
                ("FD7-B", "D1"): "ok",
                ("FD7-B", "D2"): "fail",
            },
        )
        cmd_report(db, FakeArgs())
        output = capsys.readouterr().out
        assert "D2" in output
        assert "bad" in output.lower()

    def test_no_tests_warns(self, capsys):
        db = {"cameras": ["A"], "disks": ["D1"], "tests": []}
        cmd_report(db, FakeArgs())
        output = capsys.readouterr().out
        assert "No test results" in output

    def test_missing_combos_shown(self, capsys):
        db = self._make_full_db(
            ["A", "B"],
            ["D1", "D2"],
            {("A", "D1"): "ok"},  # only 1 of 4 tested
        )
        cmd_report(db, FakeArgs())
        output = capsys.readouterr().out
        assert "Missing" in output

    def test_isolated_failure_detected(self, capsys):
        db = self._make_full_db(
            ["A", "B"],
            ["D1", "D2"],
            {("A", "D1"): "ok", ("A", "D2"): "ok", ("B", "D1"): "fail", ("B", "D2"): "ok"},
        )
        cmd_report(db, FakeArgs())
        output = capsys.readouterr().out
        assert "Isolated" in output or "B" in output


class TestCmdStatus:
    def test_status_shows_remaining(self, capsys):
        db = {
            "cameras": ["A", "B"],
            "disks": ["D1", "D2"],
            "tests": [{"camera": "A", "disk": "D1", "result": "ok"}],
        }
        cmd_status(db, FakeArgs())
        output = capsys.readouterr().out
        assert "1/4" in output
        assert "A + D2" in output
        assert "B + D1" in output
        assert "B + D2" in output

    def test_status_all_done(self, capsys):
        db = {
            "cameras": ["A"],
            "disks": ["D1"],
            "tests": [{"camera": "A", "disk": "D1", "result": "ok"}],
        }
        cmd_status(db, FakeArgs())
        output = capsys.readouterr().out
        assert "1/1" in output
