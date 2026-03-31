"""Tests for disk health history tracking."""

import os
import tempfile

import pytest

from mavica_tools.history import (
    load_history,
    save_history,
    record_snapshot,
    get_disk_history,
    get_all_disks,
    compare_snapshots,
    DiskSnapshot,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def history_path(tmp_dir):
    return os.path.join(tmp_dir, "history.json")


class TestLoadSave:
    def test_load_nonexistent(self, history_path):
        assert load_history(history_path) == []

    def test_save_and_load(self, history_path):
        data = [{"disk_label": "test", "total_sectors": 2880}]
        save_history(data, history_path)
        loaded = load_history(history_path)
        assert loaded == data


class TestRecordSnapshot:
    def test_record_all_good(self, history_path):
        status = ["good"] * 2880
        snapshot = record_snapshot("DISK-001", status, path=history_path)
        assert snapshot.disk_label == "DISK-001"
        assert snapshot.total_sectors == 2880
        assert snapshot.good == 2880
        assert snapshot.blank == 0
        assert snapshot.readable_pct == 100.0

    def test_record_mixed(self, history_path):
        status = ["good"] * 2800 + ["blank"] * 50 + ["recovered"] * 30
        snapshot = record_snapshot("DISK-002", status, path=history_path)
        assert snapshot.good == 2800
        assert snapshot.blank == 50
        assert snapshot.recovered == 30
        assert snapshot.readable_pct == pytest.approx(98.26, abs=0.1)

    def test_record_persists(self, history_path):
        record_snapshot("DISK-A", ["good"] * 100, path=history_path)
        record_snapshot("DISK-A", ["good"] * 80 + ["blank"] * 20, path=history_path)
        history = load_history(history_path)
        assert len(history) == 2

    def test_record_with_notes(self, history_path):
        snapshot = record_snapshot("X", ["good"] * 10, notes="test note", path=history_path)
        assert snapshot.notes == "test note"


class TestGetDiskHistory:
    def test_filter_by_label(self, history_path):
        record_snapshot("DISK-A", ["good"] * 100, path=history_path)
        record_snapshot("DISK-B", ["good"] * 100, path=history_path)
        record_snapshot("DISK-A", ["good"] * 90 + ["blank"] * 10, path=history_path)

        a_history = get_disk_history("DISK-A", history_path)
        assert len(a_history) == 2
        assert all(s.disk_label == "DISK-A" for s in a_history)

    def test_empty_history(self, history_path):
        assert get_disk_history("NONE", history_path) == []


class TestGetAllDisks:
    def test_lists_unique_labels(self, history_path):
        record_snapshot("A", ["good"], path=history_path)
        record_snapshot("B", ["good"], path=history_path)
        record_snapshot("A", ["good"], path=history_path)

        disks = get_all_disks(history_path)
        assert disks == ["A", "B"]


class TestCompareSnapshots:
    def test_stable_disk(self):
        older = DiskSnapshot("D", "2024-01-01", 100, 95, 5, 0, 0, 100.0)
        newer = DiskSnapshot("D", "2024-06-01", 100, 95, 5, 0, 0, 100.0)
        diff = compare_snapshots(older, newer)
        assert diff["readable_change"] == 0
        assert diff["degrading"] is False

    def test_degrading_disk(self):
        older = DiskSnapshot("D", "2024-01-01", 100, 95, 5, 0, 0, 100.0)
        newer = DiskSnapshot("D", "2024-06-01", 100, 80, 5, 15, 0, 85.0)
        diff = compare_snapshots(older, newer)
        assert diff["readable_change"] == -15.0
        assert diff["degrading"] is True

    def test_improving_disk(self):
        older = DiskSnapshot("D", "2024-01-01", 100, 80, 5, 15, 0, 85.0)
        newer = DiskSnapshot("D", "2024-06-01", 100, 90, 8, 2, 0, 98.0)
        diff = compare_snapshots(older, newer)
        assert diff["readable_change"] == 13.0
        assert diff["degrading"] is False
