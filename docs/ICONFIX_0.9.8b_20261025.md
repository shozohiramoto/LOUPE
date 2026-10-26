# LOUPE v0.9.8b icon quality hotfix — 2026-10-25

Status: **unverified on Windows**. This is a replacement development source, not a public release.

## Problem

The 0.9.8b About dialog showed a visually broken magnifier: irregular stepped
lens rim/handle and inconsistent appearance versus the actual PHASE icon.

## Changes

- `assets/loupe.png`: redrawn icon at 256×256, visually matched to the
  **actual PHASE application screenshot** (screenshot only used as a read-only
  design reference). The PHASE application and its icon are not modified.
- `assets/loupe.ico`: regenerates seven embedded Windows sizes 16, 24, 32,
  48, 64, 128, 256 px; same image coverage and 1:1 aspect ratio.
- `loupe/gui.py`: About-dialog icon uses high-DPI-aware **SmoothTransformation**
  rather than the previous **FastTransformation** to prevent jagged resampling.
- Magnifying-glass lens has exactly circular bounds (equal X/Y diameter).
- No changes to imaging, HIS, RAM monitor, relative offsets or Orthogonal code.

## Windows acceptance

1. Start new source package with `run.bat`; open About; inspect icon at
   Windows scale 100%, 125%, 150% and compare to PHASE's actual About icon.
2. Verify main window/taskbar icon at 16, 24, 32, 48px sizes.
3. Rebuild Windows EXE from source to update **embedded** `loupe.ico`.
   Cached/pinned taskbar shortcuts can retain previous icon images; test the
   newly built exe in Explorer and About dialog separately.
4. Native Section/Orthogonal Preview crash P0 (`ID098-20`) is not fixed or
   validated by this icon-only hotfix; keep this development version internal.
