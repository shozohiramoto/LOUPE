# LOUPE v0.9.7 Development — Native Section calibration correction

- Native Section adds **Override XY pixel size** with editable µm/px, independent of source TIFF header.
- User-defined XY calibration from ordinary VIEW is preserved when opening Orthogonal View; the TIFF header is only a fallback when the VIEW is uncalibrated.
- A differing parent calibration initializes and enables Native Section XY override. A user may turn it off to use verified header values.
- The override is passed to `scan_series(..., pixel_size_um=...)`, and native extraction uses the selected spacing for physical dimensions and output TIFF/JSON provenance.
- Existing **Custom verified Z spacing** is retained. With no custom Z value the extraction defaults to isotropic Z spacing equal to selected XY spacing.
- Generate Native Section again after changing calibration. No source TIFF is modified.

## Validation
- Python compile check: PASS.
- Targeted tests: 5 passed, 2 GUI tests skipped (PySide6 not installed).
- Complete test suite not clean because older tests hard-code v0.9.6 as expected identity; Windows GUI/manual verification still required.
