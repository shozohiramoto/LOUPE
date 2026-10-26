# LOUPE v0.9.8b Development — 2026-10-25

**Status:** Source development snapshot, not validated on Windows and not an approved public release.
This snapshot preserves the v0.9.8 ID098-08/11/17 functionality while improving the offset-edit UI and LOUPE icon.

## ID098-08a: Make offset-edit mode unmistakable

- The `Adjust Offsets` button is a checkable toggle (as in 0.9.8). While active it reads **`✓ Adjust Offsets: ON`** and uses a contrasting amber background with dark text.
- VIEW 2–4 with loaded images show an amber **OFFSET EDIT** badge and amber plot border while offsets are being adjusted. VIEW 1 is never marked as editable because it is the reference.
- **Esc** exits edit mode, retaining the offsets. `Reset Offsets` is still the explicit action to erase offsets.
- Status bar describes the active mode and its exit gesture. The original image-coordinate offsets, JSON persistence, linked wheel zoom and linked pan algorithms are not modified.
- When Linked view is disabled, edit mode automatically exits as before.
- Pixel annotation/ROI interactions remain suppressed in VIEW 2–4 during active editing, as in 0.9.8.

## LOUPE icon correction (PHASE unchanged)

- Reworked **only** `assets/loupe.png` and `assets/loupe.ico`.
- Based frame proportions, outer black bevel and glossy top-left light/dark gradient on the **user-provided screenshot of the actual PHASE 0.3.0-dev application icon**. No PHASE image is packaged or changed.
- Magnifier ring is circular (same X/Y native diameter); the tile occupies a square canvas without additional outer margins. No native PHASE source/ICO was provided, so the match derives from its screenshot and should be checked in the Windows taskbar.
- PNG is 256×256 pixels. ICO includes Windows sizes 16, 24, 32, 48, 64, 128 and 256. Build from this updated source to replace EXE embedded icon, then unpin/repin old shortcuts if Windows continues showing a cached icon.

## Retained from v0.9.8 development

- ID098-08 Relative Linked View, offset save/restore.
- ID098-11 Physical RAM indicator and process RAM tooltip.
- ID098-17 Read-only HiPic HIS frame browser and native frame TIFF export.
- ID098-18 Native Section temporary diagnostic patch; the heap-corruption cause is **not established**, Windows crash fix **not verified**.
- ID098-16 ImageJ/Fiji wording changes.

## Validation and Windows acceptance

- Local headless tests: **312 PASS, 15 SKIP** (Qt GUI unavailable), source compiles without syntax errors.
- Windows GUI, actual 41 GiB HIS, v0.9.7 Native Section crash regression, icon display/caching and EXE packaging remain to be verified.
- Smoke test offset UI: load VIEW 1–4; check Linked view; turn Adjust Offsets on; confirm amber button text, badges/borders only on VIEW 2–4; drag VIEW2; zoom; press Esc and verify offsets persist. Reset offsets explicitly and verify values clear. Repeat in 2-view/4-view layouts and after session reload.
- Smoke test icon: build `build_LOUPE_v0.9.8b_exe.bat` on Windows; compare PHASE and LOUPE taskbar icons at small Windows sizes; check About dialog icon, tooltip, file explorer and taskbar pinned shortcut.

## Public distribution gate

- No public Release until verified on Windows, ID098-18 resolved, and organizational rights plus third-party Qt/Python license obligations checked and packaged. This dev source is not a signed binary.
