# mavica-tools

Floppy disk recovery and troubleshooting toolkit for Sony Mavica cameras (FD5, FD7, FD73, FD88, FD91, etc).

## Install

```bash
pip install -e .
```

Or run tools directly:

```bash
python -m mavica_tools.check my_images/
```

## Tools

### `mavica check` — JPEG health checker

Batch-checks JPEGs for corruption: truncation, zero-byte runs (sector failures), missing markers.

```bash
mavica check /mnt/floppy/          # check all JPEGs on a mounted floppy
mavica check *.jpg -v              # verbose — show OK files too
```

### `mavica repair` — JPEG repair

Salvages readable pixels from corrupt/truncated JPEGs. Outputs PNG files.

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
mavica multipass read /dev/fd0 -n 5 -o my_disk  # 5 passes from device
mavica multipass merge pass*.img -o merged.img   # merge existing images
```

Outputs:
- Individual pass images
- Merged best-of image
- Visual sector health map
- Summary statistics

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
mavica swaptest status                     # see what's left to test
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

## TUI (Planned)

An interactive terminal UI is planned using Python Textual. See [TUI_PLAN.md](TUI_PLAN.md) for the full design.

Features: guided recovery workflow, live sector map, image preview, interactive swap test matrix.

## Requirements

- Python 3.7+
- Pillow (for check/repair)
- Linux with `dd` (for multipass device reads — merge works anywhere)

## Development

See [AGENTS.md](AGENTS.md) for architecture details, function signatures, and contribution guidelines.

```bash
pip install -e .
python -m pytest tests/ -v
```
