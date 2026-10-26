# LOUPE v0.9.8 Development — ID098-08 / 11 / 17 included

**Source preview only. Not yet a Windows-validated build or an approved general release.**
Keep the last known working v0.9.7 separate. Do not replace the stable GitHub Release.

## New functions in this snapshot

### ID098-08 — Relative Linked View

- Tick `Linked view (zoom / pan)`.
- Click `Adjust Offset` and LEFT-drag inside VIEW 2–4. Those panels move individually, while VIEW 1 stays fixed. The adjustment offsets are in **native source-image pixels**.
- Mouse wheel still zooms the panels together. Drag VIEW 1 to move all; switch `Adjust Offset` off to resume linked pan from any VIEW while keeping alignment.
- `Reset Offsets` resets positions. `Save Session…` / `Open Session…` persists the four offsets as `view_offsets_px` in the existing comparison JSON.
- ROI markers are retained; their mouse interaction is suppressed in VIEW 2–4 while adjusting offsets to avoid unintentional ROI dragging. This is **manual image alignment**, not physical multiscale registration (ID098-13).

### ID098-11 — RAM status indicator

- A compact `RAM n% used/total` label and bar appear in the bottom status bar, refreshed every 2 seconds.
- Hover over the label/bar to see total, used, available **PC physical RAM** and LOUPE **process working set** separately.
- The monitor is informational only; it does not evict caches, automatically allocate resources or claim a memory safety guarantee.
- Windows RAM is queried through native system APIs without adding mandatory packages.

### ID098-17 — Read-only HiPic a.his browser

- `Open Image` now supports `.his` files in addition to `.tif`, `.tiff`, `.img`.
- LOUPE validates each 64-byte HIS frame header and frame byte range before opening an image. The implemented decoder is restricted to the **8-/16-bit grayscale single-channel HiPic IM-header variant**; incompatible or truncated variants fail with a message.
- Projection frames are read **on demand**, one image at a time. Never expand the whole HIS file. The existing slice slider, navigation and independent contrast/ROI tools work on individual HIS frames; a bounded cache may retain adjacent frames.
- `Export ▾` → `Current HIS Frame (native TIFF)…` exports the currently displayed native (unmodified) frame; format remains the source's unsigned 8- or 16-bit precision. No 8-bit contrast transformation is applied.
- **Not yet implemented:** verification of `output.log` angle / Dark / I0 associations; automated exposure-type classification; EXE GUI test against the original 41 GB BL09W dataset; direct HIS stack transfer to Fiji. `Orthogonal View` is intentionally reserved for reconstructed CT TIFF/IMG stacks, not projection series.
- Select an explicit `.his` file. Folder autodiscovery continues to favor TIFF/IMG series and does not implicitly open HIS.

## Other changes already in this branch

- ID098-18: Native Section mmap cleanup and additional diagnostics. The cause of the observed Windows `0xC0000374` heap corruption remains unproven.
- Updated LOUPE pixel-art magnifying-glass PNG/ICO. **PHASE v0.2.0 is unchanged.**
- ID098-16: ImageJ/Fiji wording cleanup; Fiji-specific technical diagnostics retain precise wording.
- Java RMI helper packaged in EXE build recipe; development version identity updated.

## Tests and release gates

- **310 passed, 15 skipped** in the supplied non-GUI Python test environment on 2026-10-25. Tests cover HIS geometry/indexing, exact raw uint16 pixel values, corrupt/truncated files, relative view translation mathematics, RAM formatting, and legacy TIFF/ROI/reconstruction modules.
- Skipped GUI tests require PySide6/pyqtgraph, which are unavailable in the test environment. Consequently **Qt interactive controls, Windows EXE, and actual BL09W a.his GUI navigation are unverified**.
- Essential Windows smoke check: load CT TIFF to VIEW 1+2, enable linked view, adjust VIEW 2, wheel zoom and pan VIEW 1, save/reopen comparison; check on 4-view layout, then open `a.his`, move to a random frame, export to 16-bit TIFF and compare native pixel values in ImageJ/Fiji; check memory indicator; test Native Section separately.
- Required before general public distribution: resolve ID098-18 Native Section crash, complete Windows GUI regression, obtain institutional authorization and full third-party/Qt LGPL license compliance. This repository does **not** yet include an authorized `LICENSE` or `THIRD_PARTY_NOTICES` package.
