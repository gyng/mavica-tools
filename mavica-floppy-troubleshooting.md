# Mavica Floppy Disk Troubleshooting Guide

Covers: FD7, FD88, and other floppy-based Mavicas.

## Quick Diagnostic: Is It the Drive, the Camera, or the Disk?

You have 2x FD7 + 1x FD88 — this is ideal for isolating the problem. Here's a systematic approach:

### Step 1: Test the Disk Across All Three Cameras

Take the floppy with corrupt images and try viewing them on all three cameras:

| Result | Likely cause |
|--------|-------------|
| Images load on all cameras but fail on PC | Floppy drive on PC, or disk surface damage in areas the PC reads differently |
| Images fail on one camera only | That camera's floppy drive has a read issue |
| Images fail on all cameras | Disk is bad or files are genuinely corrupt |

You mentioned images mostly load on the camera — this is a strong clue. The Mavica reads sequentially and is more tolerant of minor errors than a PC floppy drive.

### Step 2: Write Test — Isolate the Camera's Write Head

1. Put a **known-good freshly formatted floppy** in the suspect FD7
2. Take 5–10 test photos
3. Read that floppy on your PC
4. Repeat with the **other FD7** using a different known-good floppy
5. Compare results

If only one FD7 produces corrupt files → that camera's write head is dirty or misaligned.

### Step 3: Cross-Read Test — Isolate the PC Floppy Drive

1. Take the floppy written by the suspect FD7 and read it in a **second PC floppy drive** or USB floppy drive
2. If it reads fine on another drive → your PC drive is the problem
3. If it fails on both → the camera wrote bad data

### Step 4: Format Test

Format a floppy **in the Mavica** (not on the PC), take photos, then read on PC. Mavica-formatted disks sometimes work better because the camera writes at its own preferred track geometry.

---

## Common Causes (Ranked by Likelihood)

### 1. Dirty Read/Write Heads (Most Common)
The #1 cause of Mavica floppy issues. These cameras are 20+ years old.

**Fix:**
- Get a **3.5" floppy head cleaning disk** (wet type with isopropyl alcohol)
- Insert into the Mavica and let it "read" for 10–15 seconds
- Alternatively, open the floppy door and gently clean the head with a cotton swab dipped in 99% isopropyl alcohol
- Clean your PC floppy drive the same way

### 2. Worn or Weak Disk Media
Old floppies lose magnetic charge over time. The Mavica writes at a lower density than the disk's theoretical max, so marginal disks may write OK but read back poorly.

**Fix:**
- Use **new-old-stock (NOS) HD (1.44MB) floppies** — they're still available
- Avoid reusing disks that have been written hundreds of times
- Store disks away from magnets, heat, and humidity

### 3. PC Floppy Drive Issues
USB floppy drives are notoriously inconsistent. Internal PC floppy drives (if you have one) are generally more reliable.

**Fix:**
- Try a different USB floppy drive — quality varies wildly between brands
- If possible, use an internal 3.5" drive connected to a motherboard floppy header
- The **TEAC FD-05HGS** and **Sony MPF920** are considered reliable USB/internal drives

### 4. Head Alignment Drift
The Mavica's drive and your PC drive may have slightly different head alignment. Marginal writes from one can fail reads on the other.

**Fix:**
- Not easily fixable without specialized tools
- Workaround: try multiple PC floppy drives — one may align better with your Mavica's write head

---

## Recovering Corrupt/Unreadable Images

### Method 1: Raw Disk Imaging (Best First Step)

Create a raw image of the floppy before attempting anything else. This preserves whatever data is recoverable.

**Linux:**
```bash
# Create a raw disk image (replace /dev/fd0 with your floppy device)
dd if=/dev/fd0 of=mavica_disk.img bs=512 conv=noerror,sync status=progress

# If you get read errors, try multiple passes — magnetic media can read
# differently on successive attempts due to head settling
for i in $(seq 1 5); do
  dd if=/dev/fd0 of=mavica_disk_pass${i}.img bs=512 conv=noerror,sync 2>pass${i}.log
done
```

**Windows:**
- Use [RawWrite](http://www.chrysocome.net/rawwrite) or [WinImage](http://www.winimage.com/)
- Or use [HxC Floppy Emulator software](https://hxc2001.com/) to create raw images

### Method 2: Recover JPEG Files from Raw Image

Mavica stores standard JPEG files on a FAT12 filesystem. Even if the FAT is damaged, the JPEGs can be carved out:

```bash
# Install photorec (part of testdisk package)
sudo apt install testdisk

# Run photorec on the disk image
photorec mavica_disk.img
# Select the disk image, choose "No partition table", and let it scan for JPEGs
```

Alternatively, manual carving:

```bash
# JPEGs start with FF D8 FF and end with FF D9
# Use binwalk to find embedded JPEGs
binwalk mavica_disk.img

# Or use foremost
foremost -t jpg -i mavica_disk.img -o recovered_images/
```

### Method 3: Multiple Read Attempts

Floppy reads are not deterministic — the head may land slightly differently each time:

```bash
#!/bin/bash
# Try reading the floppy multiple times and keep the best result
# Some sectors may read successfully on attempt 3 that failed on attempt 1

DEVICE="/dev/fd0"
OUTPUT_DIR="recovery_attempts"
mkdir -p "$OUTPUT_DIR"

for attempt in $(seq 1 10); do
    echo "=== Attempt $attempt ==="
    dd if="$DEVICE" of="$OUTPUT_DIR/attempt_${attempt}.img" \
       bs=512 conv=noerror,sync 2>"$OUTPUT_DIR/attempt_${attempt}.log"
    sync
    # Eject and re-insert can help (or just wait a moment)
    eject "$DEVICE" 2>/dev/null
    sleep 2
done

echo "Compare file sizes and checksums:"
ls -la "$OUTPUT_DIR"/*.img
md5sum "$OUTPUT_DIR"/*.img
```

### Method 4: Repair Partial JPEGs

If you recover a JPEG that's partially corrupt (displays partially then goes gray/garbled):

```bash
# Use jpeginfo to check integrity
jpeginfo -c recovered_image.jpg

# Use jpegtran to salvage what's readable
jpegtran -copy all -perfect recovered_image.jpg > fixed_image.jpg 2>/dev/null

# ImageMagick can sometimes render partial JPEGs that other tools reject
convert recovered_image.jpg repaired_image.png
```

Python approach for partial JPEG recovery:
```python
from PIL import Image
import io

# PIL/Pillow is tolerant of truncated JPEGs
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

img = Image.open("recovered_image.jpg")
img.save("repaired_image.png")  # Save as PNG to avoid re-encoding
```

---

## Floppy Drive Maintenance Tips

### Cleaning Schedule
- Clean heads every **10–15 disks** or whenever you see read errors
- Use 99% isopropyl alcohol (not 70% — the water content can cause issues)

### Floppy Disk Tips
- **Format in the Mavica**, not on the PC, for best compatibility
- New disks should be formatted before first use in the camera
- HD disks (1.44MB) are correct for all Mavica models
- The FD7 stores ~40 images in standard quality per disk
- The FD88 stores the same (it shoots 640x480 like the FD7 in standard mode)

### Storage
- Keep disks in cases, upright, away from speakers/magnets
- Temperature extremes degrade magnetic media
- If a disk has been sitting for years, try reading it multiple times before giving up

### Speed Up Testing Across Cameras
Since you have 3 Mavicas, here's a quick swap test procedure:

1. Label 3 floppies: A, B, C
2. Format all 3 in one camera
3. Take 5 photos on each, one per camera
4. Read all 3 on PC
5. Swap: read disk A in camera 2 and 3, etc.
6. Any pattern of failures points to the culprit (camera or disk)

Total time: ~15 minutes. This definitively isolates the problem.

---

## FD7 vs FD88 Differences

| Feature | FD7 | FD88 |
|---------|-----|------|
| Resolution | 640×480 | 640×480 |
| Zoom | Fixed lens | 8x digital zoom |
| Floppy format | 1.44MB HD | 1.44MB HD |
| File format | JPEG (standard) | JPEG (standard) |
| Drive mechanism | Same Sony OEM | Same Sony OEM |

Both use the same floppy drive mechanism, so cleaning/troubleshooting steps are identical.

---

## Quick Reference: Diagnostic Flowchart

```
Images corrupt on PC but show on camera?
├── YES
│   ├── Try another PC floppy drive
│   │   ├── Works → PC drive is bad
│   │   └── Still fails → Camera write head is marginal
│   │       └── Clean camera head, retest
│   └── Try disk in other Mavica cameras
│       ├── Shows fine → Original camera reads its own marginal writes
│       └── Also glitchy → Disk media is degraded
└── NO (corrupt everywhere)
    └── Disk is bad → attempt raw image recovery (see above)
```
