# LOUPE v0.9.8d (Development)

**Lightweight tool for CT and radiography image visualization and evaluation.**

LOUPE provides image viewing, comparison, line profiles, ROI-based measurements, and an Orthogonal View workflow for CT image stacks. It also supports ImageJ/Fiji integration where configured.

## Status

**Development / evaluation build.** This version is not a validated stable public release. Windows GUI behavior, repeat Fiji integration, and Native Section calibration should be checked on the target PC before distribution. See [v0.9.8d development notes](docs/RELEASE_NOTES_0.9.8d-dev.md).

## Requirements and start (Windows)

- Python and compatible dependencies listed in `requirements.txt`.
- Run `setup_shared_env.bat` to prepare the environment as applicable, then `run.bat` to start LOUPE. Consult the scripts before running in a managed installation.
- `build_windows_exe.bat` builds a **one-directory** Windows executable with PyInstaller. The executable is not included in this source repository upload; verified binaries can be attached separately to GitHub Releases.

## Key changes in v0.9.8d development

- Uses the approved bold-stroke magnifying-glass artwork for both PNG and Windows ICO.
- About, window and packaged EXE assets use the same icon; PHASE is untouched.
- All v0.9.8c features and provisional crash safeguards are retained.

## Previous changes in v0.9.8c development

- Offset-edit mode now shows ON/OFF explicitly (amber checked button, VIEW 2–4 badges and plot borders, Esc-to-exit while preserving offsets).
- LOUPE icon was restyled to match the actual PHASE screenshot's proportions and glossy black-to-gray frame. PHASE was not modified.
- Preserves all v0.9.8 development functionality (Relative Linked View, RAM indicator, HIS reader) and provisional Native Section diagnostics.


Linked zoom with independently corrected VIEW offsets (ID098-08), status-bar RAM indicator (ID098-11) and read-only HiPic HIS projection browsing with per-frame native TIFF export (ID098-17). The HIS angle/Dark/I0 association has **not** been validated. The EXE and Windows Qt GUI require hands-on testing.

## Previous Native Section calibration improvement in v0.9.7

Native Section permits an independently editable XY pixel-size override (µm/px). Ordinary VIEW's manually set calibration is preserved when opening Orthogonal View, with TIFF-header calibration used as a fallback. Regenerate Native Section after adjusting calibration.

## Development and testing

Run `python -m pytest tests` after installing test dependencies. The source is tested independently; the exact results for v0.9.8d are provided with this archive. Windows functionality remains unverified.

## Licensing and credits

No license has been granted in this source upload. Confirm intellectual-property ownership and select an appropriate license before authorizing third-party reuse. Add the appropriate institution/author and contact information after review.
