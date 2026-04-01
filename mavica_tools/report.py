"""Recovery report export — HTML summary of a recovery session.

Generates a self-contained HTML report with:
  - Sector health map (colored grid)
  - File list with status
  - Repair results
  - Recovery statistics
"""

import argparse
import base64
import glob as globmod
import os
from datetime import datetime
from html import escape


def _sector_map_html(sector_status: list[str]) -> str:
    """Generate an HTML sector map grid."""
    colors = {
        "good": "#33ff33",
        "recovered": "#33aaff",
        "blank": "#ff3333",
        "conflict": "#ff33ff",
    }
    chars = {
        "good": ".",
        "recovered": "r",
        "blank": "X",
        "conflict": "!",
    }

    sectors_per_track = 18

    lines = []
    lines.append('<div class="sector-map">')
    lines.append('<div class="sector-legend">')
    for status, color in colors.items():
        char = chars[status]
        lines.append(f'<span style="color:{color}">{char}</span> {status} &nbsp; ')
    lines.append("</div>")
    lines.append('<pre class="sector-grid">')

    for i in range(0, len(sector_status), sectors_per_track):
        track = i // (sectors_per_track * 2)
        head = (i // sectors_per_track) % 2
        chunk = sector_status[i : i + sectors_per_track]
        line = f"T{track:02d}H{head} ["
        for s in chunk:
            color = colors.get(s, "#666")
            char = chars.get(s, "?")
            line += f'<span style="color:{color}">{char}</span>'
        line += "]"
        lines.append(line)

    lines.append("</pre></div>")
    return "\n".join(lines)


def _file_table_html(files: list[dict]) -> str:
    """Generate an HTML table of files."""
    rows = []
    for f in files:
        status = f.get("status", "ok")
        color = {"ok": "#33ff33", "repaired": "#ffaa00", "failed": "#ff3333"}.get(status, "#666")
        name = escape(f.get("name", ""))
        details = escape(f.get("details", ""))
        size = f.get("size", 0)
        rows.append(
            f"<tr>"
            f'<td style="color:{color}">{status.upper()}</td>'
            f"<td>{name}</td>"
            f'<td class="num">{size:,}</td>'
            f"<td>{details}</td>"
            f"</tr>"
        )

    return (
        '<table class="file-table">'
        "<tr><th>Status</th><th>Filename</th><th>Size</th><th>Details</th></tr>"
        + "\n".join(rows)
        + "</table>"
    )


def _thumbnail_html(image_path: str, max_width: int = 200) -> str:
    """Generate inline base64 thumbnail for an image."""
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(image_path)
        img.thumbnail((max_width, max_width))
        buf = BytesIO()
        img.save(buf, "JPEG", quality=60)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return (
            f'<img src="data:image/jpeg;base64,{b64}" alt="{escape(os.path.basename(image_path))}">'
        )
    except Exception:
        return '<span class="dim">No preview</span>'


def generate_report(
    output_path: str,
    sector_status: list[str] = None,
    files: list[dict] = None,
    image_dir: str = None,
    disk_label: str = "",
    camera_model: str = "",
    notes: str = "",
) -> str:
    """Generate an HTML recovery report.

    Args:
        output_path: Where to save the HTML file
        sector_status: List of sector statuses from multipass merge
        files: List of dicts with name, size, status, details
        image_dir: Directory containing recovered images (for thumbnails)
        disk_label: Label for the disk being recovered
        camera_model: Camera model string
        notes: Additional notes

    Returns the output path.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = f"Recovery Report — {disk_label}" if disk_label else "Recovery Report"

    # Compute stats
    total_files = len(files) if files else 0
    good_files = sum(1 for f in (files or []) if f.get("status") == "ok")
    repaired_files = sum(1 for f in (files or []) if f.get("status") == "repaired")
    failed_files = sum(1 for f in (files or []) if f.get("status") == "failed")

    sector_html = ""
    sector_stats = ""
    if sector_status:
        sector_html = _sector_map_html(sector_status)
        total = len(sector_status)
        good = sector_status.count("good")
        recovered = sector_status.count("recovered")
        blank = sector_status.count("blank")
        readable_pct = 100 * (good + recovered) / total if total else 0
        sector_stats = (
            f'<div class="stats">'
            f'<span class="stat good">{good} good</span> '
            f'<span class="stat recovered">{recovered} recovered</span> '
            f'<span class="stat bad">{blank} blank</span> '
            f'<span class="stat">{readable_pct:.1f}% readable</span>'
            f"</div>"
        )

    file_html = ""
    if files:
        file_html = _file_table_html(files)

    # Thumbnails
    thumbnails_html = ""
    if image_dir and os.path.isdir(image_dir):
        jpgs = sorted(
            globmod.glob(os.path.join(image_dir, "*.jpg"))
            + globmod.glob(os.path.join(image_dir, "*.JPG"))
        )
        if jpgs:
            thumbs = []
            for jpg in jpgs[:50]:  # Limit to 50 thumbnails
                thumbs.append(
                    f'<div class="thumb">'
                    f"{_thumbnail_html(jpg)}"
                    f'<div class="thumb-name">{escape(os.path.basename(jpg))}</div>'
                    f"</div>"
                )
            thumbnails_html = (
                '<h2>Recovered Images</h2><div class="thumb-grid">' + "\n".join(thumbs) + "</div>"
            )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>
body {{
    font-family: 'Courier New', monospace;
    background: #0a0a0a;
    color: #cccccc;
    margin: 0;
    padding: 20px;
    max-width: 1000px;
    margin: 0 auto;
}}
h1 {{
    color: #33ff33;
    border-bottom: 2px solid #33ff33;
    padding-bottom: 10px;
}}
h2 {{
    color: #ffaa00;
    margin-top: 30px;
}}
.meta {{
    color: #666;
    margin-bottom: 20px;
}}
.stats {{
    margin: 10px 0;
    font-size: 1.1em;
}}
.stat {{
    margin-right: 20px;
}}
.stat.good {{ color: #33ff33; }}
.stat.recovered {{ color: #33aaff; }}
.stat.bad {{ color: #ff3333; }}
.sector-map {{
    margin: 10px 0;
    padding: 10px;
    background: #111;
    border: 1px solid #333;
    border-radius: 4px;
    overflow-x: auto;
}}
.sector-legend {{
    margin-bottom: 8px;
    font-size: 0.9em;
}}
.sector-grid {{
    font-size: 12px;
    line-height: 1.4;
}}
.file-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0;
}}
.file-table th {{
    background: #1a1a1a;
    color: #ffaa00;
    text-align: left;
    padding: 8px;
    border-bottom: 2px solid #333;
}}
.file-table td {{
    padding: 6px 8px;
    border-bottom: 1px solid #222;
}}
.file-table .num {{
    text-align: right;
}}
.thumb-grid {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin: 10px 0;
}}
.thumb {{
    text-align: center;
}}
.thumb img {{
    max-width: 200px;
    border: 1px solid #333;
    border-radius: 4px;
}}
.thumb-name {{
    font-size: 0.8em;
    color: #666;
    margin-top: 4px;
}}
.dim {{ color: #666; }}
.summary-box {{
    background: #111;
    border: 1px solid #333;
    border-radius: 4px;
    padding: 15px;
    margin: 10px 0;
}}
</style>
</head>
<body>
<h1>{escape(title)}</h1>
<div class="meta">
    Generated: {now}<br>
    {f"Camera: {escape(camera_model)}<br>" if camera_model else ""}
    {f"Notes: {escape(notes)}<br>" if notes else ""}
</div>

<div class="summary-box">
    <strong>Summary:</strong>
    {total_files} file(s) recovered —
    <span style="color:#33ff33">{good_files} good</span>,
    <span style="color:#ffaa00">{repaired_files} repaired</span>,
    <span style="color:#ff3333">{failed_files} failed</span>
</div>

{f"<h2>Sector Health</h2>{sector_stats}{sector_html}" if sector_html else ""}
{f"<h2>File List</h2>{file_html}" if file_html else ""}
{thumbnails_html}

<div class="meta" style="margin-top:40px; border-top:1px solid #333; padding-top:10px;">
    Generated by mavica-tools
</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def generate_from_recovery_dir(recovery_dir: str, output_path: str = None, **kwargs) -> str:
    """Generate a report from a recovery directory structure.

    Looks for merged.img, extracted/, repaired/ subdirectories.
    """
    if output_path is None:
        output_path = os.path.join(recovery_dir, "report.html")

    sector_status = None
    merged_path = os.path.join(recovery_dir, "merged.img")
    if os.path.exists(merged_path):
        from mavica_tools.multipass import merge_passes

        _, sector_status = merge_passes([merged_path])

    # Find image directory
    image_dir = None
    files = []
    for subdir in ("extracted", "carved_images"):
        d = os.path.join(recovery_dir, subdir)
        if os.path.isdir(d):
            image_dir = d
            for jpg in sorted(
                globmod.glob(os.path.join(d, "*.jpg")) + globmod.glob(os.path.join(d, "*.JPG"))
            ):
                name = os.path.basename(jpg)
                size = os.path.getsize(jpg)
                files.append(
                    {
                        "name": name,
                        "size": size,
                        "status": "ok",
                        "details": "",
                    }
                )
            break

    # Check repaired dir
    repaired_dir = os.path.join(recovery_dir, "repaired")
    if os.path.isdir(repaired_dir):
        for png in sorted(globmod.glob(os.path.join(repaired_dir, "*.png"))):
            name = os.path.basename(png)
            size = os.path.getsize(png)
            files.append(
                {
                    "name": name,
                    "size": size,
                    "status": "repaired",
                    "details": "Repaired from corrupt original",
                }
            )

    return generate_report(
        output_path,
        sector_status=sector_status,
        files=files,
        image_dir=image_dir,
        **kwargs,
    )


def main():
    parser = argparse.ArgumentParser(description="Generate HTML recovery report")
    parser.add_argument(
        "recovery_dir",
        help="Recovery directory (containing merged.img, extracted/, etc.)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output HTML file (default: recovery_dir/report.html)",
    )
    parser.add_argument("--label", default="", help="Disk label")
    parser.add_argument("--camera", default="", help="Camera model")
    parser.add_argument("--notes", default="", help="Additional notes")

    args = parser.parse_args()

    path = generate_from_recovery_dir(
        args.recovery_dir,
        output_path=args.output,
        disk_label=args.label,
        camera_model=args.camera,
        notes=args.notes,
    )
    print(f"Report generated: {path}")


if __name__ == "__main__":
    main()
