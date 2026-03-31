# mavica-tools

Floppy disk recovery and troubleshooting toolkit for Sony Mavica cameras (FD5, FD7, FD73, FD88, FD91, etc).

Works on **Windows**, **macOS**, and **Linux**.

## Install

```bash
# Using uv (recommended)
uv sync

# Or with pip
pip install -e .
```

## Interactive TUI

Launch the full terminal UI with guided workflow, image preview, and live sector maps:

```bash
mavica tui
```

The TUI includes:
- **Guided Workflow** — step-by-step recovery walkthrough
- **Multipass Read** — multi-pass floppy imager with visual sector map
- **JPEG Carver** — extract images from raw disk images with preview
- **Health Check** — batch corruption scanner with color-coded results
- **Repair** — before/after image preview for recovered files
- **Swap Test** — interactive camera/disk test matrix

## CLI Tools

All tools also work standalone from the command line.

### `mavica check` — JPEG health checker

```bash
mavica check /mnt/floppy/          # check all JPEGs on a mounted floppy
mavica check *.jpg -v              # verbose — show OK files too
```

### `mavica repair` — JPEG repair

```bash
mavica repair corrupt_image.jpg                 # repair one file
mavica repair /mnt/floppy/ -o repaired/         # repair all, output to dir
```

Repair strategies (tried in order):
1. Load with truncation tolerance (Pillow)
2. Detect zero-byte runs (sector failures) and truncate before them
3. Progressive tail trimming

### `mavica multipass` — Multi-pass floppy imager

Reads a floppy multiple times and merges the best sectors. Floppy reads are non-deterministic — a sector that fails on pass 1 may succeed on pass 3.

```bash
# Linux/macOS
mavica multipass read /dev/fd0 -n 5 -o my_disk

# Windows (run as Administrator)
mavica multipass read \\.\A: -n 5 -o my_disk

# Merge existing images (any platform)
mavica multipass merge pass*.img -o merged.img
```

### `mavica carve` — JPEG carver

Extracts JPEG images directly from raw disk images, bypassing the filesystem entirely. Works even when FAT is damaged.

```bash
mavica carve my_disk/merged.img -o recovered/
```

### `mavica swaptest` — Cross-camera test tracker

Systematically test multiple cameras and disks to isolate which component is faulty.

```bash
mavica swaptest setup --cameras "FD7-A,FD7-B,FD88" --disks "Disk-1,Disk-2,Disk-3"
mavica swaptest log --camera FD7-A --disk Disk-1 --result ok
mavica swaptest log --camera FD7-A --disk Disk-2 --result fail
mavica swaptest report                     # analyze and find the culprit
```

The report identifies patterns:
- All disks fail with one camera → bad write head
- All cameras fail with one disk → bad disk
- Single combo fails → head alignment mismatch

## Typical Recovery Workflow

```bash
# 1. Image the floppy (multiple passes for best recovery)
mavica multipass read /dev/fd0 -n 5 -o my_disk

# 2. Carve JPEGs from the raw image
mavica carve my_disk/merged.img -o recovered/

# 3. Check which images are OK and which need repair
mavica check recovered/

# 4. Attempt to repair corrupt ones
mavica repair recovered/ -o repaired/
```

Or just run `mavica tui` and use the guided workflow.

## Platform Notes

| Feature | Windows | macOS | Linux |
|---------|---------|-------|-------|
| TUI | Yes | Yes | Yes |
| Check/Repair/Carve | Yes | Yes | Yes |
| Multipass merge | Yes | Yes | Yes |
| Multipass device read | `\\.\A:` (as Admin) | `/dev/diskN` | `/dev/fd0` |
| Swap test | Yes | Yes | Yes |

## Development

```bash
uv sync
uv run --extra dev pytest -v
```

See [AGENTS.md](AGENTS.md) for architecture details and [TUI_PLAN.md](TUI_PLAN.md) for TUI design.

## Requirements

- Python 3.10+
- Pillow (image decoding)
- Textual (terminal UI)
