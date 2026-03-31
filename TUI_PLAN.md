# TUI Implementation Plan

## Decision: Python TUI with Textual

### Why Textual over Rust (ratatui)?

| Factor | Textual (Python) | ratatui (Rust) |
|--------|-------------------|----------------|
| Integration | Direct function calls | Subprocess/FFI wrapping |
| Pillow dependency | Already there | Still needs Python runtime for repair |
| Distribution | `pip install mavica-tools[tui]` | Rust binary + Python interpreter |
| Image preview | Pillow resize + half-blocks | Would need image crate + custom renderer |
| Development speed | Fast iteration, CSS styling | Longer, but cleaner binary |
| Single binary | No | Yes, but still needs Python for repair |

**Bottom line**: Repair requires Pillow's truncated-JPEG decoding. No Rust crate does this. Even a Rust TUI needs Python at runtime, so you'd maintain two codebases for no distribution benefit.

**Future option**: A full Rust rewrite (including a truncation-tolerant JPEG decoder) is a separate, larger project. The Textual TUI can be built now and works with the existing tools immediately.

## Architecture

```
mavica_tools/
  tui/
    __init__.py
    app.py              # Main Textual App, screen routing, CSS theme
    screens/
      __init__.py
      home.py           # Landing screen with tool menu
      multipass.py      # Multi-pass imaging with live sector map
      carve.py          # JPEG carving with results table
      check.py          # Batch health check with color-coded results
      repair.py         # Repair with before/after image preview
      swaptest.py       # Interactive test matrix
      workflow.py       # Guided step-by-step recovery
    widgets/
      __init__.py
      sector_map.py     # Visual sector health grid (colored characters)
      image_preview.py  # Terminal image via half-block Unicode chars
      file_picker.py    # Directory/file browser modal
      progress_panel.py # Real-time operation progress
```

## Screen Designs

### Home Screen

```
+------------------------------------------------------------------+
|  mavica-tools              Floppy Recovery Toolkit          [?]   |
+------------------------------------------------------------------+
|                                                                    |
|   [1] Multipass Read    Multi-pass floppy imager                  |
|   [2] Carve JPEGs       Extract images from disk images           |
|   [3] Check Files       Batch JPEG corruption check               |
|   [4] Repair Images     Salvage pixels from corrupt JPEGs         |
|   [5] Swap Test         Cross-camera test tracker                 |
|   [---]                                                           |
|   [W] Guided Workflow   Step-by-step recovery (recommended)       |
|                                                                    |
|   Recent activity:                                                |
|   - Last multipass: my_disk/ (2880 sectors, 98.2% good)          |
|   - 3 images recovered, 1 needs repair                           |
|                                                                    |
+------------------------------------------------------------------+
|  q Quit  ? Help  1-5 Tools  w Workflow                           |
+------------------------------------------------------------------+
```

- `OptionList` for tool selection (keyboard + mouse)
- Recent activity from a small state file

### Multipass Screen

```
+------------------------------------------------------------------+
|  Multipass Read                                          [Home]   |
+------------------------------------------------------------------+
| Device: /dev/fd0          Passes: 5           Output: my_disk/   |
|                                                                    |
| Pass 3 of 5  [=========>          ] 45%   Sector 1296/2880       |
| Errors this pass: 2                                               |
|                                                                    |
| Sector Map:                                                       |
| T00H0 [..................]  T00H1 [..................]             |
| T01H0 [..................]  T01H1 [..................]             |
| T02H0 [..................]  T02H1 [.....rr...........]             |
| T03H0 [..................]  T03H1 [........XX........]             |
|                                                                    |
| Legend:  . good   r recovered   X blank   ! conflict              |
| Summary: 2876 good  2 recovered  2 blank  0 conflict             |
|                                                                    |
| Log:                                                              |
| [12:03:41] Pass 1 complete - 4 errors                            |
| [12:04:12] Pass 2 complete - 2 errors (2 sectors recovered)      |
+------------------------------------------------------------------+
|  Esc Back  s Start  p Pause  e Eject                             |
+------------------------------------------------------------------+
```

- **Sector Map Widget**: 2880 colored characters (green=good, yellow=recovered, red=blank, magenta=conflict), organized by track/head
- `dd` runs in a Textual `Worker` thread
- Between passes: modal dialog "Eject disk, re-insert, press Enter"
- Also supports "Merge" mode for existing `.img` files

### Carve Screen

```
+------------------------------------------------------------------+
|  JPEG Carver                                             [Home]   |
+------------------------------------------------------------------+
| Image: my_disk/merged.img (1,474,560 bytes)     Output: carved/  |
| [Browse...]                                      [Start Carve]   |
|                                                                    |
| Found 4 JPEG(s):                                                  |
| +----+-------------------+----------+---------+--------+          |
| | #  | Filename          | Size     | Offset  | Status |          |
| +----+-------------------+----------+---------+--------+          |
| | 1  | mavica_001.jpg    | 47,231   | 0x0200  | OK     |          |
| | 2  | mavica_002.jpg    | 52,108   | 0xBA00  | OK     |          |
| | 3  | mavica_003.jpg    | 38,445   | 0x1A200 | TRUNC  |          |
| | 4  | mavica_004.jpg    | 61,002   | 0x28E00 | OK     |          |
| +----+-------------------+----------+---------+--------+          |
|                                                                    |
| Preview:  [selected image thumbnail]                              |
|                                                                    |
| -> Check all    -> Repair truncated                               |
+------------------------------------------------------------------+
```

- `DataTable` with selectable rows
- Selecting a row shows image preview
- Action buttons chain into Check or Repair screens

### Check Screen

```
+------------------------------------------------------------------+
|  JPEG Health Check                                       [Home]   |
+------------------------------------------------------------------+
| Source: recovered/                                [Browse] [Run]  |
|                                                                    |
| +------+-------------------+--------+-------+-------------------+ |
| | Stat | Filename          | Size   | Dims  | Issues            | |
| +------+-------------------+--------+-------+-------------------+ |
| | OK   | mavica_001.jpg    | 47KB   | 640x  |                   | |
| | WARN | mavica_003.jpg    | 38KB   | 640x  | Missing EOI       | |
| | BAD  | mavica_005.jpg    | 0KB    |       | Empty file        | |
| +------+-------------------+--------+-------+-------------------+ |
|                                                                    |
| Summary: 3 OK  2 Warning  1 Bad                                  |
| [Repair warnings/bad files ->]                                    |
+------------------------------------------------------------------+
```

- Color-coded status: green OK, yellow WARN, red BAD
- Runs `check_jpeg_structure()` per file in a worker

### Repair Screen

```
+------------------------------------------------------------------+
|  JPEG Repair                                             [Home]   |
+------------------------------------------------------------------+
| +------+-------------------+-----------+-------------------------+ |
| | Stat | Filename          | Strategy  | Details                 | |
| +------+-------------------+-----------+-------------------------+ |
| | DONE | mavica_003.jpg    | Truncate  | 640x480, 87% recovered | |
| | FAIL | mavica_005.jpg    | -         | Too corrupt             | |
| +------+-------------------+-----------+-------------------------+ |
|                                                                    |
| +---------------------------+---------------------------+          |
| |     Original (corrupt)    |     Repaired              |          |
| |    [image preview]        |    [image preview]         |          |
| +---------------------------+---------------------------+          |
+------------------------------------------------------------------+
```

- Side-by-side before/after image preview
- Shows which repair strategy succeeded

### Swap Test Screen

```
+------------------------------------------------------------------+
|  Cross-Camera Swap Test                                  [Home]   |
+------------------------------------------------------------------+
| Cameras: FD7-A, FD7-B, FD88        [Edit Setup]                  |
| Disks:   Disk-1, Disk-2, Disk-3                                  |
|                                                                    |
|              Disk-1    Disk-2    Disk-3                            |
|   FD7-A       .         X         .                               |
|   FD7-B       .         X         .                               |
|   FD88        .         .         .                               |
|                                                                    |
| Progress: 7/9 tested  (click empty cell to log result)            |
|                                                                    |
| Analysis:                                                         |
|   >>> ALL cameras fail with Disk-2 - this disk is likely bad.     |
+------------------------------------------------------------------+
```

- Clickable `DataTable` matrix
- Click empty cell -> modal with OK/Partial/Fail buttons
- Analysis updates reactively after each entry

### Guided Workflow Screen

Walks through the 4-step recovery process:

1. **Image the floppy** (multipass) -> produces `merged.img`
2. **Carve JPEGs** (auto-fills path from step 1)
3. **Check files** (auto-fills from step 2)
4. **Repair** (auto-fills from step 3, only if needed)

Progress bar at top shows current step. Each step has context help text.

## Key Widgets

### Sector Map (`widgets/sector_map.py`)

- Renders 2880 sectors as colored characters in a grid
- 18 chars per line (one track side), 160 lines total (80 tracks x 2 heads)
- Colors: green `.` = good, yellow `r` = recovered, red `X` = blank, magenta `!` = conflict
- Accepts `list[str]` of status values, re-renders reactively
- Scrollable for full disk view

### Image Preview (`widgets/image_preview.py`)

- Uses Unicode half-block characters (U+2580) with fg/bg colors
- 2 vertical pixels per character cell
- Load image with Pillow, resize to fit widget bounds, convert pixel pairs to styled characters
- ~80x48 effective resolution in a standard terminal (enough to identify Mavica photos)
- Optional Sixel/Kitty protocol support for terminals that support it
- Async loading via Textual Worker

### File Picker (`widgets/file_picker.py`)

- Modal wrapping Textual's `DirectoryTree`
- Filter by extension (`.img`, `.jpg`, `.jpeg`)
- Returns selected path to calling screen

## Required Refactors to Existing Code

### multipass.py

Add optional `progress_callback` parameter to `multipass_image()` and `read_pass()`:

```python
def multipass_image(device, output_dir, passes=5, eject_between=True, progress_callback=None):
    # Instead of print(), call progress_callback(event_type, data) if provided
    # Default behavior (print) preserved when callback is None
```

### swaptest.py

Decouple `input()` calls from data operations:

- `cmd_setup()` already works with `args.cameras`/`args.disks` — just skip the `input()` branch when args are provided (already done)
- `cmd_log()` same — already has the non-interactive path
- `cmd_report()` — extract analysis logic into a pure function that returns structured findings instead of printing

### No changes needed

- `carve.py` — `find_jpegs()` and `carve_jpegs()` already return structured data
- `check.py` — `check_jpeg_structure()` already returns a dict
- `repair.py` — `repair_jpeg()` already returns `(bool, path, message)`

## Packaging

```python
# setup.py
setup(
    ...
    extras_require={
        "tui": ["textual>=0.50", "rich-pixels>=3.0"],
    },
    entry_points={
        "console_scripts": [
            "mavica=mavica_tools.cli:main",
        ],
    },
)
```

Install: `pip install mavica-tools[tui]`
Launch: `mavica tui` or `mavica` with no args

## Implementation Order

1. App shell + home screen + CSS theme + navigation
2. Check screen (simplest — pure function calls, DataTable output)
3. File picker widget
4. Carve screen + image preview widget
5. Repair screen with before/after preview
6. Multipass screen + sector map widget + progress callback refactor
7. Swap test screen + interactive matrix
8. Guided workflow screen (chains all screens together)
9. Packaging, `mavica tui` command, error handling polish

## Theming

Amber/green retro terminal aesthetic:
- Dark background (#0a0a0a)
- Green primary text (#33ff33)
- Amber accents for highlights (#ffaa00)
- Red for errors/bad sectors (#ff3333)
- Consistent with the vintage Mavica camera era
