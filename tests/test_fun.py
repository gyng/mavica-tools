"""Tests for fun extras — visualizations, stats, trivia."""

from mavica_tools.fun import (
    TRIVIA,
    disk_stats_text,
    floppy_art,
    health_bar,
    health_bar_rich,
    random_trivia,
    recovery_suggestions,
    sector_sparkline,
    sector_sparkline_rich,
)


class TestFloppyArt:
    def test_default_label(self):
        art = floppy_art()
        assert "MAVICA" in art
        assert "◉" in art

    def test_custom_label(self):
        art = floppy_art("TDK-001")
        assert "TDK-001" in art

    def test_small_variant(self):
        art = floppy_art("TEST", small=True)
        assert "TEST" in art
        assert len(art) < len(floppy_art("TEST"))


class TestHealthBar:
    def test_excellent(self):
        result = health_bar(100)
        assert "excellent" in result

    def test_good(self):
        result = health_bar(85)
        assert "good" in result

    def test_fair(self):
        result = health_bar(60)
        assert "fair" in result

    def test_poor(self):
        result = health_bar(30)
        assert "poor" in result

    def test_rich_variant(self):
        result = health_bar_rich(95)
        assert "excellent" in result
        assert "[green]" in result


class TestDiskStats:
    def test_empty(self):
        result = disk_stats_text(0, 0)
        assert "Empty" in result

    def test_with_files(self):
        result = disk_stats_text(10, 300_000)
        assert "10 photos" in result
        assert "KB" in result
        assert "floppy" in result

    def test_single_file(self):
        result = disk_stats_text(1, 50_000)
        assert "1 photo" in result

    def test_with_recovery_stats(self):
        result = disk_stats_text(10, 300_000, good=8, repaired=1, failed=1)
        assert "Recovery rate" in result


class TestRecoverySuggestions:
    def test_perfect_disk(self):
        status = ["good"] * 2880
        suggestions = recovery_suggestions(sector_status=status)
        assert any("perfectly" in s for s in suggestions)

    def test_minor_damage(self):
        status = ["good"] * 2850 + ["blank"] * 30
        suggestions = recovery_suggestions(sector_status=status)
        assert any("clean" in s.lower() for s in suggestions)

    def test_severe_damage(self):
        status = ["good"] * 500 + ["blank"] * 2380
        suggestions = recovery_suggestions(sector_status=status)
        assert any("professional" in s.lower() or "severe" in s.lower() for s in suggestions)

    def test_all_files_ok(self):
        suggestions = recovery_suggestions(good_files=10, bad_files=0, total_files=10)
        assert any("successfully" in s for s in suggestions)

    def test_some_bad_files(self):
        suggestions = recovery_suggestions(good_files=5, bad_files=3, total_files=8)
        assert any("repair" in s.lower() for s in suggestions)


class TestTrivia:
    def test_random_returns_string(self):
        result = random_trivia()
        assert isinstance(result, str)
        assert len(result) > 10

    def test_result_is_from_list(self):
        result = random_trivia()
        assert result in TRIVIA


class TestSparkline:
    def test_all_good(self):
        status = ["good"] * 2880
        result = sector_sparkline(status, width=30)
        assert "#" in result

    def test_mixed(self):
        status = ["good"] * 2000 + ["blank"] * 880
        result = sector_sparkline(status, width=30)
        assert "#" in result
        assert "-" in result

    def test_empty(self):
        assert sector_sparkline([]) == ""

    def test_rich_variant(self):
        status = ["good"] * 100 + ["recovered"] * 50
        result = sector_sparkline_rich(status, width=20)
        assert "[green]" in result
