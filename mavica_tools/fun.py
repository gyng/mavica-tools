"""Fun extras — visualizations, stats, suggestions, and floppy trivia.

Adds personality to the recovery process. Because recovering 25-year-old
photos from a floppy disk should feel like archaeology, not dentistry.
"""

import math
import os
import random
from datetime import datetime


# ─── Floppy disk ASCII art ───────────────────────────────────────────────

FLOPPY_ART = r"""
  ┌─────────────────────┐
  │  ┌───────────────┐  │
  │  │               │  │
  │  │   {label:^13s}   │  │
  │  │               │  │
  │  └───────────────┘  │
  │                     │
  │    ┌───────────┐    │
  │    │           │    │
  │    │     ◉     │    │
  │    │           │    │
  │    └───────────┘    │
  └─────────────────────┘"""

FLOPPY_SMALL = r"""
  ┌──────────┐
  │ ┌──────┐ │
  │ │{label:^6s}│ │
  │ └──────┘ │
  │  ┌────┐  │
  │  │ ◉  │  │
  │  └────┘  │
  └──────────┘"""


def floppy_art(label: str = "MAVICA", small: bool = False) -> str:
    """Render ASCII art of a 3.5" floppy disk."""
    template = FLOPPY_SMALL if small else FLOPPY_ART
    return template.format(label=label[:13] if not small else label[:6])


# ─── Disk health visualization ───────────────────────────────────────────

def health_bar(percent: float, width: int = 30) -> str:
    """Render a colored health bar.

    100% = all green
    80-99% = mostly green with yellow
    50-79% = yellow warning
    <50% = red danger
    """
    filled = int(width * percent / 100)
    empty = width - filled

    if percent >= 95:
        color = "\033[32m"  # green
        emoji = "excellent"
    elif percent >= 80:
        color = "\033[33m"  # yellow
        emoji = "good"
    elif percent >= 50:
        color = "\033[33m"  # yellow
        emoji = "fair"
    else:
        color = "\033[31m"  # red
        emoji = "poor"

    bar = f"{color}{'█' * filled}{'░' * empty}\033[0m"
    return f"  [{bar}] {percent:.1f}% — {emoji}"


def health_bar_rich(percent: float, width: int = 30) -> str:
    """Rich-markup version of health_bar for TUI."""
    filled = int(width * percent / 100)
    empty = width - filled

    if percent >= 95:
        color = "green"
        label = "excellent"
    elif percent >= 80:
        color = "#ffaa00"
        label = "good"
    elif percent >= 50:
        color = "#ffaa00"
        label = "fair"
    else:
        color = "red"
        label = "poor"

    return f"  [{color}]{'█' * filled}{'░' * empty}[/] {percent:.1f}% — {label}"


# ─── Disk age and fun stats ──────────────────────────────────────────────

def disk_age_text(date_str: str) -> str:
    """Generate a fun message about how old this disk is.

    date_str: "YYYY-MM-DD" format
    """
    try:
        disk_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
        now = datetime.now()
        delta = now - disk_date
        years = delta.days / 365.25

        if years < 1:
            return f"From {date_str[:10]} — less than a year old. Fresh!"
        elif years < 5:
            return f"From {date_str[:10]} — {years:.0f} years old."
        elif years < 15:
            return f"From {date_str[:10]} — {years:.0f} years old. A teenager!"
        elif years < 25:
            return f"From {date_str[:10]} — {years:.0f} years old. These photos are old enough to drink."
        else:
            return f"From {date_str[:10]} — {years:.0f} years old! Digital archaeology."
    except (ValueError, TypeError):
        return ""


def disk_stats_text(
    total_files: int,
    total_bytes: int,
    good: int = 0,
    repaired: int = 0,
    failed: int = 0,
) -> str:
    """Generate a summary with fun context."""
    lines = []

    if total_files == 0:
        return "  Empty disk — no photos found."

    # File count
    if total_files == 1:
        lines.append(f"  1 photo recovered")
    else:
        lines.append(f"  {total_files} photos recovered")

    # Size in floppy terms
    kb = total_bytes / 1024
    pct_of_floppy = (total_bytes / 1_474_560) * 100
    lines.append(f"  {kb:.0f}KB total ({pct_of_floppy:.0f}% of a 1.44MB floppy)")

    # Avg size per photo
    if total_files > 0:
        avg_kb = kb / total_files
        lines.append(f"  ~{avg_kb:.0f}KB per photo (typical Mavica: 20-50KB)")

    # Recovery rate
    if good + repaired + failed > 0:
        rate = 100 * (good + repaired) / (good + repaired + failed)
        lines.append(f"  Recovery rate: {rate:.0f}%")

    return "\n".join(lines)


# ─── Suggestions based on results ────────────────────────────────────────

def recovery_suggestions(
    sector_status: list[str] | None = None,
    good_files: int = 0,
    bad_files: int = 0,
    total_files: int = 0,
) -> list[str]:
    """Generate contextual suggestions based on recovery results."""
    suggestions = []

    if sector_status:
        total = len(sector_status)
        blank = sector_status.count("blank")
        readable_pct = 100 * (total - blank) / total if total else 0

        if readable_pct == 100:
            suggestions.append("Disk read perfectly! No issues detected.")
        elif readable_pct >= 95:
            suggestions.append(f"{blank} bad sector(s) — try cleaning the drive head and re-reading.")
        elif readable_pct >= 80:
            suggestions.append("Significant sector damage. Try:")
            suggestions.append("  - More read passes (10+) to recover marginal sectors")
            suggestions.append("  - A different USB floppy drive (alignment varies)")
            suggestions.append("  - Cleaning both the camera and PC drive heads")
        elif readable_pct >= 50:
            suggestions.append("Heavy damage. Recovery is possible but expect some loss:")
            suggestions.append("  - Run 20+ passes for maximum sector recovery")
            suggestions.append("  - Try every USB floppy drive you can find")
            suggestions.append("  - Store this disk carefully — it's degrading")
        else:
            suggestions.append("Severe damage. Most sectors are unreadable:")
            suggestions.append("  - Try a professional data recovery service")
            suggestions.append("  - The disk media may be physically damaged")
            suggestions.append("  - Keep the disk — technology may improve")

    if bad_files > 0 and total_files > 0:
        if bad_files == total_files:
            suggestions.append("All photos are damaged. The disk surface may have a scratch.")
        elif bad_files > total_files / 2:
            suggestions.append(f"{bad_files}/{total_files} photos damaged — check if they cluster in one area of the disk.")
        else:
            suggestions.append(f"{bad_files} photo(s) need repair — Pillow can often salvage partial images.")

    if good_files > 0 and bad_files == 0:
        suggestions.append("All photos recovered successfully!")
        suggestions.append("  Next: 'mavica stamp' to add camera info, then 'mavica export' to organize.")

    return suggestions


# ─── Mavica trivia ───────────────────────────────────────────────────────

TRIVIA = [
    "The Mavica FD7 was Sony's first consumer floppy-disk camera (1997).",
    "Mavica stands for 'Magnetic Video Camera' — coined by Sony in 1981.",
    "A 1.44MB floppy holds about 15-40 Mavica photos depending on quality.",
    "The FD91 had a 14x optical zoom — unusual for a floppy camera.",
    "Mavica floppies use standard FAT12 — the same filesystem as DOS.",
    "The FD73 used a Carl Zeiss Vario-Sonnar lens — premium optics on a floppy camera.",
    "At 640x480, Mavica photos have the same resolution as standard-definition TV.",
    "The last floppy Mavica (FD200) was released in 2002 with a 2MP sensor.",
    "Mavica cameras were popular with real estate agents and insurance adjusters.",
    "A Mavica floppy read at ~50KB/s — about 30 seconds for a full disk.",
    "The 3.5\" floppy disk was invented by Sony in 1980.",
    "Floppy disks store data magnetically — keep them away from speakers.",
    "99% isopropyl alcohol is the recommended head cleaner — never use 70%.",
    "The Mavica line sold over 3 million units worldwide.",
    "USB floppy drives vary wildly in read quality — try multiple drives.",
]


def random_trivia() -> str:
    """Return a random Mavica fun fact."""
    return random.choice(TRIVIA)


def trivia_for_context(context: str = "") -> str:
    """Return a contextually relevant trivia fact."""
    context_lower = context.lower()

    if "clean" in context_lower or "head" in context_lower:
        return "99% isopropyl alcohol is the recommended head cleaner — never use 70%."
    elif "zoom" in context_lower:
        return "The FD91 had a 14x optical zoom — unusual for a floppy camera."
    elif "zeiss" in context_lower or "lens" in context_lower:
        return "The FD73 used a Carl Zeiss Vario-Sonnar lens — premium optics on a floppy camera."
    elif "fd7" in context_lower or "first" in context_lower:
        return "The Mavica FD7 was Sony's first consumer floppy-disk camera (1997)."
    elif "fat12" in context_lower or "filesystem" in context_lower:
        return "Mavica floppies use standard FAT12 — the same filesystem as DOS."
    elif "slow" in context_lower or "speed" in context_lower:
        return "A Mavica floppy reads at ~50KB/s — about 30 seconds for a full disk."

    return random_trivia()


# ─── Sector map sparkline ────────────────────────────────────────────────

def sector_sparkline(sector_status: list[str], width: int = 60) -> str:
    """Compact single-line sector health visualization.

    Groups sectors into buckets and shows the worst status per bucket.
    """
    if not sector_status:
        return ""

    bucket_size = max(1, len(sector_status) // width)
    chars = {
        "good": ("▓", "\033[32m"),      # green
        "recovered": ("▒", "\033[36m"), # cyan
        "blank": ("░", "\033[31m"),     # red
        "conflict": ("▒", "\033[35m"), # magenta
    }

    priority = {"blank": 3, "conflict": 2, "recovered": 1, "good": 0}

    line = []
    for i in range(0, len(sector_status), bucket_size):
        bucket = sector_status[i : i + bucket_size]
        worst = max(bucket, key=lambda s: priority.get(s, 0))
        char, color = chars.get(worst, ("?", ""))
        line.append(f"{color}{char}\033[0m")

    return "  " + "".join(line)


def sector_sparkline_rich(sector_status: list[str], width: int = 60) -> str:
    """Rich-markup sparkline for TUI."""
    if not sector_status:
        return ""

    bucket_size = max(1, len(sector_status) // width)
    chars = {
        "good": ("▓", "green"),
        "recovered": ("▒", "#33aaff"),
        "blank": ("░", "red"),
        "conflict": ("▒", "magenta"),
    }
    priority = {"blank": 3, "conflict": 2, "recovered": 1, "good": 0}

    parts = []
    for i in range(0, len(sector_status), bucket_size):
        bucket = sector_status[i : i + bucket_size]
        worst = max(bucket, key=lambda s: priority.get(s, 0))
        char, color = chars.get(worst, ("?", "white"))
        parts.append(f"[{color}]{char}[/]")

    return "  " + "".join(parts)
