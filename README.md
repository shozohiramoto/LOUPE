# LOUPE v0.9.7 (Development)

**Lightweight tool for CT and radiography image visualization and evaluation.**

LOUPE provides image viewing, comparison, line profiles, ROI-based measurements, and an Orthogonal View workflow for CT image stacks. It also supports ImageJ/Fiji integration where configured.

## Status

**Development / evaluation build.** This version is not a validated stable public release. Windows GUI behavior, repeat Fiji integration, and Native Section calibration should be checked on the target PC before distribution. See [v0.9.7 release notes](docs/RELEASE_NOTES_0.9.7.md).

## Requirements and start (Windows)

- Python and compatible dependencies listed in `requirements.txt`.
- Run `setup_shared_env.bat` to prepare the environment as applicable, then `run.bat` to start LOUPE. Consult the scripts before running in a managed installation.
- `build_windows_exe.bat` builds a **one-directory** Windows executable with PyInstaller. The executable is not included in this source repository upload; verified binaries can be attached separately to GitHub Releases.

## Key change in v0.9.7

Native Section permits an independently editable XY pixel-size override (µm/px). Ordinary VIEW's manually set calibration is preserved when opening Orthogonal View, with TIFF-header calibration used as a fallback. Regenerate Native Section after adjusting calibration.

## Development and testing

Run `python -m pytest tests` after installing test dependencies. The v0.9.7 development release notes describe known failures in older version-identity tests; this repository upload does not assert full test-suite success.

## Licensing and credits

No license has been granted in this source upload. Confirm intellectual-property ownership and select an appropriate license before authorizing third-party reuse. Add the appropriate institution/author and contact information after review.
