"""Drive vs disk diagnostics from multi-pass read error patterns.

Analyzes which sectors failed on which passes to distinguish:
- Drive alignment issues (try a different drive)
- Media degradation (more passes or professional recovery)
- Dirty drive head (clean with IPA)

Floppy geometry: 80 tracks, 2 heads (sides A/B), 18 sectors per track = 2880 sectors.
"""

from dataclasses import dataclass, field

from mavica_tools.multipass import (
    HEADS,
    SECTORS_PER_TRACK,
    TRACKS,
    identify_bad_sectors,
)

SECTORS_PER_CYLINDER = SECTORS_PER_TRACK * HEADS  # 36


def sector_track(sector_idx: int) -> int:
    return sector_idx // SECTORS_PER_CYLINDER


def sector_head(sector_idx: int) -> int:
    return (sector_idx // SECTORS_PER_TRACK) % HEADS


def sector_in_track(sector_idx: int) -> int:
    return sector_idx % SECTORS_PER_TRACK


@dataclass
class DriveDiagnosis:
    """Result of analyzing multi-pass read error patterns."""

    headline: str  # One-line summary
    confidence: str  # "likely", "possible", "uncertain"
    evidence: list[str] = field(default_factory=list)  # Bullet points
    suggestions: list[str] = field(default_factory=list)  # Actionable steps
    stats: dict = field(default_factory=dict)  # Raw numbers


def analyze_passes(image_paths: list[str]) -> list[set[int]]:
    """Extract per-pass bad-sector sets from saved pass images.

    Returns a list of sets, one per pass, each containing sector indices
    that were blank (all zeros = read failure) in that pass.
    """
    return [identify_bad_sectors(path) for path in image_paths]


def diagnose_errors(
    pass_image_paths: list[str] | None = None,
    sector_status: list[str] | None = None,
    pass_bad_sectors: list[set[int]] | None = None,
) -> DriveDiagnosis:
    """Analyze error patterns and diagnose drive vs disk issues.

    Provide either pass_image_paths (will read from disk) or
    pass_bad_sectors (pre-computed). sector_status is the merged result.
    """
    # Get per-pass data
    if pass_bad_sectors is None and pass_image_paths:
        pass_bad_sectors = analyze_passes(pass_image_paths)

    # Get merged status if not provided
    if sector_status is None:
        sector_status = []

    # Collect all bad sectors (union across passes for per-pass, or from merged)
    if pass_bad_sectors:
        all_bad = set()
        for bad in pass_bad_sectors:
            all_bad |= bad
        # "Permanently bad" = bad in every pass
        permanent_bad = pass_bad_sectors[0].copy()
        for bad in pass_bad_sectors[1:]:
            permanent_bad &= bad
    else:
        all_bad = {i for i, s in enumerate(sector_status) if s in ("blank", "bad")}
        permanent_bad = all_bad  # Can't distinguish without per-pass data

    total_bad = len(all_bad)
    diagnosis = DriveDiagnosis(
        headline="",
        confidence="uncertain",
        stats={
            "total_bad": total_bad,
            "permanent_bad": len(permanent_bad),
        },
    )

    # Not enough errors to diagnose
    if total_bad == 0:
        diagnosis.headline = "Disk is healthy"
        diagnosis.confidence = "likely"
        diagnosis.evidence.append("No bad sectors detected — all tested sectors read successfully.")
        diagnosis.suggestions.append("This disk is good to go! Safe for camera use.")
        return diagnosis

    if total_bad < 10:
        diagnosis.headline = "Minor damage"
        diagnosis.confidence = "likely"
        diagnosis.evidence.append(
            f"Only {total_bad} bad sector(s) — too few to diagnose a pattern."
        )
        diagnosis.suggestions.append("Try a few more passes to recover the remaining sectors.")
        return diagnosis

    # Run all heuristics
    scores = {
        "drive_alignment": 0.0,
        "media_degradation": 0.0,
        "dirty_head": 0.0,
        "mechanical": 0.0,
    }

    # ── Heuristic 1: Head asymmetry ──
    head0_bad = {s for s in all_bad if sector_head(s) == 0}
    head1_bad = {s for s in all_bad if sector_head(s) == 1}
    h0, h1 = len(head0_bad), len(head1_bad)
    diagnosis.stats["head0_bad"] = h0
    diagnosis.stats["head1_bad"] = h1

    if h0 > 0 and h1 > 0:
        ratio = max(h0, h1) / min(h0, h1)
        worse_side = "A (head 0)" if h0 > h1 else "B (head 1)"
        if ratio >= 3:
            scores["drive_alignment"] += 2
            diagnosis.evidence.append(
                f"Side {worse_side} has {max(h0, h1)} bad sectors vs {min(h0, h1)} on the other side "
                f"({ratio:.1f}x asymmetry). This suggests a head alignment or contamination issue."
            )
        elif ratio >= 2:
            scores["drive_alignment"] += 1
            diagnosis.evidence.append(
                f"Side {worse_side} has moderately more errors ({max(h0, h1)} vs {min(h0, h1)})."
            )
    elif h0 == 0 or h1 == 0:
        if total_bad > 20:
            worse_side = "A (head 0)" if h0 > 0 else "B (head 1)"
            scores["drive_alignment"] += 3
            diagnosis.evidence.append(
                f"All {total_bad} bad sectors are on side {worse_side} — "
                f"the other side reads perfectly. Strong indicator of a head issue."
            )

    # ── Heuristic 2: Outer track clustering ──
    outer_tracks = {s for s in all_bad if sector_track(s) >= 54}
    middle_tracks = {s for s in all_bad if 27 <= sector_track(s) < 54}
    inner_tracks = {s for s in all_bad if sector_track(s) < 27}
    # Normalize by number of sectors in each zone
    outer_rate = len(outer_tracks) / (26 * SECTORS_PER_CYLINDER) if True else 0
    middle_rate = len(middle_tracks) / (27 * SECTORS_PER_CYLINDER) if True else 0
    inner_rate = len(inner_tracks) / (27 * SECTORS_PER_CYLINDER) if True else 0

    diagnosis.stats["outer_bad"] = len(outer_tracks)
    diagnosis.stats["middle_bad"] = len(middle_tracks)
    diagnosis.stats["inner_bad"] = len(inner_tracks)

    if middle_rate > 0 and outer_rate / middle_rate >= 2:
        scores["drive_alignment"] += 2
        diagnosis.evidence.append(
            f"Outer tracks (54-79) have {len(outer_tracks)} errors vs {len(middle_tracks)} "
            f"in the middle — alignment drift causes outer tracks to fail first."
        )
    elif outer_rate > 0 and inner_rate > 0 and middle_rate == 0:
        scores["media_degradation"] += 1
        diagnosis.evidence.append(
            f"Errors on both inner ({len(inner_tracks)}) and outer ({len(outer_tracks)}) tracks "
            f"but not the middle — unusual pattern, likely media damage."
        )

    # ── Heuristic 3: Whole-track failures ──
    dead_track_sides = []
    for track in range(TRACKS):
        for head in range(HEADS):
            start = track * SECTORS_PER_CYLINDER + head * SECTORS_PER_TRACK
            track_sectors = set(range(start, start + SECTORS_PER_TRACK))
            if track_sectors.issubset(permanent_bad):
                dead_track_sides.append((track, head))

    diagnosis.stats["dead_track_sides"] = len(dead_track_sides)

    if dead_track_sides:
        # Check if they're contiguous
        dead_tracks_only = sorted(set(t for t, h in dead_track_sides))
        contiguous = (
            all(
                dead_tracks_only[i] + 1 == dead_tracks_only[i + 1]
                for i in range(len(dead_tracks_only) - 1)
            )
            if len(dead_tracks_only) > 1
            else True
        )

        if len(dead_track_sides) >= 5 and contiguous:
            scores["mechanical"] += 3
            diagnosis.evidence.append(
                f"{len(dead_track_sides)} entire track-sides are dead in a contiguous range "
                f"(tracks {dead_tracks_only[0]}-{dead_tracks_only[-1]}). "
                f"The drive likely cannot seek to this area."
            )
        elif len(dead_track_sides) >= 3:
            scores["mechanical"] += 1
            scores["media_degradation"] += 1
            diagnosis.evidence.append(
                f"{len(dead_track_sides)} entire track-sides are completely unreadable. "
                f"Could be severe media damage or a drive seek issue."
            )

    # ── Heuristic 4: Pass-to-pass variability ──
    if pass_bad_sectors and len(pass_bad_sectors) >= 2:
        # Sectors that failed on some passes but not all
        intermittent = all_bad - permanent_bad
        diagnosis.stats["intermittent"] = len(intermittent)

        if len(intermittent) > 0:
            recovery_rate = len(intermittent) / len(all_bad) * 100
            diagnosis.stats["recovery_rate"] = recovery_rate

            if recovery_rate > 50:
                scores["media_degradation"] += 2
                diagnosis.evidence.append(
                    f"{len(intermittent)} of {len(all_bad)} bad sectors ({recovery_rate:.0f}%) "
                    f"were recovered on retry — the signal is weak but present. "
                    f"Classic media degradation."
                )
            elif recovery_rate > 20:
                scores["media_degradation"] += 1
                scores["dirty_head"] += 1
                diagnosis.evidence.append(
                    f"{len(intermittent)} sector(s) recovered on retry ({recovery_rate:.0f}%). "
                    f"Some intermittent errors — could be media aging or a dirty head."
                )

        if len(permanent_bad) > 0 and len(intermittent) == 0 and len(pass_bad_sectors) >= 3:
            scores["drive_alignment"] += 1
            diagnosis.evidence.append(
                f"All {len(permanent_bad)} bad sectors failed on every pass with zero recovery. "
                f"No improvement across passes suggests an alignment issue — try a different drive."
            )

    # ── Heuristic 5: Track 0 damage ──
    track0_bad = {s for s in all_bad if sector_track(s) == 0}
    diagnosis.stats["track0_bad"] = len(track0_bad)

    if track0_bad:
        scores["media_degradation"] += 2
        diagnosis.evidence.append(
            f"Track 0 (boot sector/FAT area) has {len(track0_bad)} bad sector(s). "
            f"Track 0 is the innermost and most tolerant track — damage here "
            f"indicates the disk media itself is degraded."
        )

    # ── Heuristic 6: Scatter pattern ──
    if total_bad > 20:
        # Count runs of consecutive bad sectors
        sorted_bad = sorted(all_bad)
        runs = 1
        for i in range(1, len(sorted_bad)):
            if sorted_bad[i] != sorted_bad[i - 1] + 1:
                runs += 1
        avg_run = total_bad / runs

        diagnosis.stats["error_runs"] = runs
        diagnosis.stats["avg_run_length"] = avg_run

        if avg_run < 2 and runs > 10:
            scores["dirty_head"] += 2
            diagnosis.evidence.append(
                f"Errors are randomly scattered ({runs} separate clusters, "
                f"avg {avg_run:.1f} sectors each). Consistent with a dirty read head "
                f"or general oxide shedding."
            )
        elif avg_run >= 5:
            scores["media_degradation"] += 1
            diagnosis.evidence.append(
                f"Errors are clustered in {runs} groups (avg {avg_run:.1f} consecutive sectors). "
                f"This pattern suggests physical scratches or localized media damage."
            )

    # ── Produce final diagnosis ──
    best = max(scores, key=lambda k: scores[k])
    best_score = scores[best]

    if best_score == 0:
        diagnosis.headline = "Unable to determine cause"
        diagnosis.confidence = "uncertain"
        diagnosis.suggestions.append("Try reading on a different floppy drive.")
        diagnosis.suggestions.append("Try cleaning the drive head with isopropyl alcohol.")
        diagnosis.suggestions.append("Try more read passes.")
        return diagnosis

    if best_score >= 3:
        diagnosis.confidence = "likely"
    elif best_score >= 2:
        diagnosis.confidence = "possible"
    else:
        diagnosis.confidence = "uncertain"

    if best == "drive_alignment":
        diagnosis.headline = "Try a different floppy drive"
        diagnosis.suggestions.append("The error pattern suggests drive head alignment issues.")
        diagnosis.suggestions.append(
            "Different USB floppy drives have different head alignment — "
            "a disk that fails on one drive may read fine on another."
        )
        if scores["media_degradation"] > 0:
            diagnosis.suggestions.append(
                "Some media degradation is also present — "
                "if a different drive doesn't help, the disk itself may be damaged."
            )
    elif best == "mechanical":
        diagnosis.headline = "Drive mechanical issue"
        diagnosis.suggestions.append(
            "The drive appears unable to seek to certain tracks. Try a different floppy drive."
        )
        diagnosis.suggestions.append(
            "If multiple drives fail on the same tracks, the disk media is damaged."
        )
    elif best == "dirty_head":
        diagnosis.headline = "Clean the drive head"
        diagnosis.suggestions.append("Random scattered errors suggest a dirty read head.")
        diagnosis.suggestions.append(
            "Clean the drive head with isopropyl alcohol on a cotton swab, "
            "let it dry, then try again."
        )
        diagnosis.suggestions.append(
            "If errors persist after cleaning, the disk media may be shedding oxide."
        )
    elif best == "media_degradation":
        diagnosis.headline = "Disk media is degrading"
        diagnosis.suggestions.append(
            "The magnetic signal on this disk is weakening. "
            "More read passes may recover additional sectors."
        )
        diagnosis.suggestions.append(
            "Try reading on multiple different drives — each may catch sectors the others miss."
        )
        diagnosis.suggestions.append(
            "Store this disk flat, away from heat and magnets. The data is fading."
        )

    return diagnosis


def format_diagnosis(diag: DriveDiagnosis, rich: bool = False) -> str:
    """Format a diagnosis for display.

    rich=True uses Rich markup for the TUI. rich=False uses plain text for CLI.
    """
    lines = []

    if rich:
        conf_color = {"likely": "red", "possible": "#ffaa00", "uncertain": "dim"}.get(
            diag.confidence, "dim"
        )
        lines.append(
            f"  [bold {conf_color}]{diag.headline}[/] [{conf_color}]({diag.confidence})[/]"
        )
        lines.append("")
        for e in diag.evidence:
            lines.append(f"    [dim]{e}[/]")
        lines.append("")
        for s in diag.suggestions:
            lines.append(f"    [bold]>[/] {s}")
    else:
        lines.append(f"  {diag.headline} ({diag.confidence})")
        lines.append("")
        for e in diag.evidence:
            lines.append(f"    {e}")
        lines.append("")
        for s in diag.suggestions:
            lines.append(f"    > {s}")

    return "\n".join(lines)
