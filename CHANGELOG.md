## v0.9.7 [Development] — Native Section calibration correction (2026-10-20)

- Editable Native Section XY calibration override (µm/px), independent of TIFF header.
- Preserve VIEW calibration into Orthogonal View; retain verified Z spacing settings.
- Windows GUI and complete test suite not yet verified.

## v0.9.6 [Development] — Staff preview build, ID050 final wording (2026-10-19)

- User-facing full menu title and long actions use the consistent name **ImageJ/Fiji** (correct brand capitalization). Actions are **Configure ImageJ/Fiji…**, **ImageJ/Fiji Connection Check…**, **Open Current Image in ImageJ/Fiji…**, **Open Stack in ImageJ/Fiji…**.
- Short-width buttons remain **Open in ImageJ**. Fiji-specific receiver/IPC technical messages continue to use **Fiji** when accurate.
- The Open Stack menu no longer displays `normal RAM` but retains range selection and existing available-RAM checks; the action exposes a status tip.
- Inherits v0.9.6 ID047 + ID051–054 (Native Section and Preview output UI). **Still Development:** actual Windows GUI high-DPI and repeated Fiji transfers have not been tested here.

## 0.9.6 [Development] — 2026-10-19 (ID047, ID051–054)

- ID047: Compact 4-VIEW Pixel Size unit dropdown no longer clips `µm`; Scale bar occupies the next line.
- ID051: Orthogonal Native Section PNG/PDF reports include plane, fixed-axis cut coordinates, original CT slice file/ordinal range, direction, calibration provenance, generation conditions and physical orientation warning.
- ID052: Orthogonal quantitative workspace is provisionally named **Native Section** to avoid detector **High-reso** confusion.
- ID053: Native Section retains Report PNG/PDF, Export TIFF+JSON and Open in ImageJ/FIJI commands.
- ID054 (revised design requested after Windows screenshots): the Orthogonal Preview **top-right** output position is retained, but its two separate PNG/PDF buttons become the same **Report ▾** drop-down as ordinary VIEW. On the Native Section tab, the **same top-right row** instead shows **Report ▾**, **Export TIFF…**, and **Open in ImageJ**. The bulky Output sidebar dock introduced in ID053 is removed so the ROI tools have more vertical space. Preview YZ/ZX remain nonquantitative and offer **no TIFF export**.
- Fiji code, output file formats, source CT pixels and ROI numeric algorithms are unchanged by ID054.
- Validation: Python regression checks pass; actual Windows Qt layout, HiDPI, Fiji transfer remain to be verified.

## 0.9.5 [Development] — 2026-10-19

- Fiji IPC: prefer structured READY receiver; fallback to ImageJ1 OtherInstance RMI via a small Java 8 client, using the configured Fiji's own ij.jar. No second Fiji process when one is running.
- Fiji IPC: runtime-only receiver bootstrap using Java/Jython, preserving custom `StartupMacros.fiji.ijm` and macros/AutoRun untouched. No persistent startup modification, even if repair was requested in v0.9.4.
- Fiji IPC: INCOMPATIBLE and absent receiver states now use RMI fallback; disabled RMI produces an explicit manual macro fallback. IPC acknowledgement does not claim completed import. Windows/Fiji repeat-transfer validation pending.
- ID047: Pixel Size value and unit in a single row; Scale bar wrapped to its own row for 3/4 VIEW (and 1/2 VIEW).
- ID050: standardized `ImageJ/FIJI` labels in user-facing UI.
- Validation: 286 passed, 11 skipped (optional PySide6/pyqtgraph); Java 8 class built and tested against synthetic ImageJ1 stub. Windows UI and actual Fiji RMI not tested.

See docs/RELEASE_NOTES_0.9.5.md and docs/WINDOWS_CHECKLIST_0.9.5.md.

## 0.9.4 [Development] — 2026-10-19

- ID043–045 report header deduplication, full source path and PNG/PDF dark text parity.
- ID046 High Resolution uses regular ImagePanel's native ROI editor and annotations; image-local Z coordinates are mapped to source Z readouts.
- Fiji startup customization repair now requires separate explicit opt-in and preserves an exact backup; minimal AutoRun loader is installed only upon approval. Original default Fiji toolbar startup macros are not reproduced by the minimal loader. READY/2nd transfer is Windows-unverified.
- See docs/RELEASE_NOTES_0.9.4.md for details and caveats.

## v0.9.3 [Development] — 2026-10-19

ID035–042: direct-entry calibration UI, FIT affordance, responsive 3/4 VIEW,
High Resolution Rectangle and on-demand line graph, ROI menu consistency,
Fiji prelaunch receiver setup and READY health check. Not Windows verified.
See docs/RELEASE_NOTES_0.9.3.md.

## v0.9.2 [Development] — 2026-10-19

Orthogonal Preview fast path for uncompressed contiguous TIFF via mmap/native
pixel sampling with compressed TIFF decoder fallback. UI/Fiji and measurement
workflow changes ID 024–034; see `docs/RELEASE_NOTES_0.9.2.md`.
Headless tests: 270 PASS / 10 SKIP. Windows GUI/Fiji tests pending.

## v0.9.1 [Development] — 2026-10-19

23 tracked changes. See `docs/RELEASE_NOTES_0.9.1.md`.

## LOUPE v0.9.0 [Development] — GUIFix1 (2026-10-19)

- Fixed Orthogonal View failing to open on Windows/PySide6 with `QSplitter.addWidget(QVBoxLayout)`: pass the `sidebar` QWidget instead of its `side` QVBoxLayout.
- Added a Qt-independent regression test for the splitter child widget contract.
- No changes to TIFF processing, calibration, ROI values, exports or main VIEW behavior.
- Windows GUI validation is still required; the build environment cannot install PySide6.

## LOUPE v0.9.0 [Development] (2026-10-19)

- Add GUI-accessible, opt-in full-resolution orthogonal workspace in Orthogonal View.
- Generate YZ/ZX from native CT TIFF files in a worker with live progress/STOP.
- Native coordinates 1-based in GUI; Z range select; optional custom verified Z spacing.
- Preview cache never used for quantitative intensity measurement; source images not modified.
- Native value readout, draggable line profile and rectangle mean/column profile (provisional, phase-3 features under validation).
- Temporary TIFF+JSON until explicit Export; permanent TIFF used for existing Fiji relay.
- Version 0.9.0; preserved UI Standard v1.0 and existing 1–4 VIEW comparison.

# Changelog

## [0.8.5] — 2026-10-18 (Development; Windows GUI validation pending)

- UI-16/17: compact top application toolbar; primary measure, view and linked-slice controls and core Save/Load/Report commands share the top row. Export CSV and ImageJ macro remain available in an Export dropdown. Removed the tall blank area to prioritize image viewing; on narrower windows link toggles wrap onto the next row.
- UI-18/19: restored one-click **Auto Contrast** next to **Window / Level…** and **Reset** on every VIEW. Manual Window/Level disables auto; mode remains per VIEW and saved/reloaded through the existing session JSON. Only display levels change, not source image measurements.
- UI-20: responsive toolbar handling for window sizes and 1–4 views; window scaling still requires Windows confirmation.
- IJ-26: explicit VIEW selection for **Open Current TIFF** and **Open Stack** before dispatching data to Fiji; show filenames and slice positions, exclude unloaded/non-TIFF panels; preserve stack range dialog, memory safety checks and existing Receiver.
- No changes to TIFF/IMG pixel arrays, Orthogonal Preview algorithm, JSON schema, Fiji protocol or measurement geometry. Added review document for the **next, not yet implemented** high-resolution YZ/ZX stage.


## [0.8.3] — 2026-10-18 (Development patch; Windows GUI validation pending)

- Fixed **IJ-25**: Windows Explorer window titled `Fiji - エクスプローラー` no longer counts as running Fiji. Now confirm the actual owning process PID/executable for titled ImageJ/Fiji windows; preserve launch safety on process-enumeration errors.
- Preserve verified Fiji Receiver automatic startup, transfer into existing Fiji, and 50-frame non-virtual Stack import; no changes to memory preflight or TIFF values.
- Orthogonal **ORT-08**: PNG/PDF reports now use the ordinary Save As file-name dialog, remember the last chosen folder, confirm overwrites, and render atomically to avoid corrupting existing reports if export fails.
- Orthogonal **ORT-09**: For each selected source VIEW, honor its Scale bar checkbox. XY/YZ/ZX use the same isotropic source-pixel calibration, including correct reduced-preview spatial coordinates; scale bars are included in report images. Uncalibrated/OFF views show no scale bars.
- Optional comments already supported in Orthogonal PNG/PDF are retained, along with preview resolution warnings.
- Added focused regression tests and a Windows GUI validation checklist. Previous 2D features and comparison JSON schema unchanged.


## [0.8.2] — 2026-10-18 (Development hotfix)

- Simplified per-VIEW contrast toolbar to one **Window / Level…** button. Auto, Reset (Full), Min/Max and histogram remain available in the dialog; Auto retains its per-slice behavior.
- Fixed `OrthogonalDialog._build_ui` referring to undefined local `selected_view` instead of the instance field `self._selected_view`.
- This prevented opening Orthogonal Preview after v0.8.1 VIEW-selection support was added.
- Added regression tests for both source-level validation and the Qt dialog's selection initialization.
- No change to Fiji, IMG/TIFF handling, source images, numerical algorithms, or existing JSON schema.
- Windows GUI needs verification; PySide6 and pyqtgraph unavailable on build host.


## [0.8.1] - 2026-10-18 (Development / Windows validation pending)

- Orthogonal Preview VIEW selector for independently loaded reconstructed CT datasets;
  selected dataset's cache is reused; non-selected datasets stay inactive.
- Orthogonal display reports in PNG/PDF with optional comments, XY/YZ/ZX,
  voxel size and coordinates, plus non-quantitative preview warning.
- Fiji bridge: one-time optional startup hook installer; session-by-session manual
  Jython script start is no longer required on supported Fiji installations.
- Authenticated structured OPEN requests avoid generating user macros for a
  running compatible Fiji receiver; returns accepted/loading/completed/failed status.
- Correct Windows CRLF `QUEUED` acknowledgement handling; confirm actual slice count.
- Preserve conservative Java Heap and free-RAM guards; recommend a safe subset size.
- Image measurement algorithms, original TIFF/IMG data, existing ROI/JSON workflows
  and legacy Fiji macro compatibility remain unchanged.
- Caveat: Fiji AutoRun integration, PDF visual layout and Qt UI require Windows
  workstation validation; success is not claimed yet.

## [0.8.0-alpha.1] — 2026-10-18 (Orthogonal preview prototype)

- Added on-demand CT Orthogonal View workspace: original TIFF XY plus YZ/ZX preview from a bounded 256³ float32 disk-backed cache (at most 64 MiB) with spatially aligned crosshairs and X/Y/Z sliders. Source CT pixels are read in streaming fashion; no full 3D RAM allocation or quantitative inference from preview data.
- Cache runs on a worker with cancellation, progress, atomic writes, reuse and data-change invalidation. Orthogonal is disabled for arbitrary radiography/IMG sequences and CT series with missing recNNNNN slices.
- Isotropic X/Y/Z sampling assumption for BL09W ordinary unresized projection-derived CT; TIFF header pixel size is shared in the preview. High-resolution YZ/ZX generation and quantitative analyses intentionally postponed.
- Copy ROI now explicitly selects source ROI and target VIEW, independent of last mouse hover (ROI-01).
- File menu shortcut column and dropdown arrow/spacing revised (UI-13/14).
- Scale bars default OFF when opening datasets; session JSON still restores saved state (UI-15).
- ImageJ/Fiji Open Stack now offers inclusive start/end slice selection before heap/RAM preflight (IJ-08). Macro targets only selected slice range; Fiji GUI interoperability untested.
- Existing beta.2 IMG display, TIFF metadata, image comparison, PDF/PNG reports and Fiji safety checks preserved.
- **Development alpha**: Windows GUI, ImageJ importer and real CT cache timings are not yet validated. Do not replace proven v0.7.x versions.

## [0.7.0-beta.2] — 2026-10-18 (IMG viewer preview)

- Added strict 64-byte-header BL09W legacy IMG reader based on the supplied `q0200.img`: uncompressed 2048×2048 uint16 sample (supports other dimensions with the same verified layout).
- Added IMG file/folder import, drag-and-drop, serial slice browsing/cache, measurements, contrast, 1–4 VIEW comparisons, and existing PNG/PDF report rendering from the native uint16 values.
- When a folder has both TIFF and IMG, TIFF is selected by default; explicitly select an `.img` file to use the IMG sequence. Do not mix image formats in a series.
- IMG has **no verified pixel-size or rotation-center metadata**; calibration stays unset until the user specifies it. A native IMG cannot currently be sent directly to ImageJ/Fiji; TIFF-only Fiji actions fail with an explanatory message.
- Reject unknown IMG headers, unsupported dtype codes, truncated files, and trailing data rather than guessing at contents.
- This beta is for Windows validation; Qt GUI drag/drop and actual image display have not been Windows-tested.

# Changelog

## [0.7.0-beta.1] — 2026-10-18

- Consolidates planned v0.6.1 presentation corrections with v0.7.0 features.
- Replaces blurry raster icon with transparent grid-sharp pixel art (About/window/taskbar).
- Reports omit empty profile boxes and use full height for images.
- Keeps slice slider, counter and controls fixed during drag previews.
- Single default instance with activation via per-user local Qt socket; File → New Window creates an isolated comparison.
- Third and subsequent comparison windows show a memory warning; outputs retain exclusive filename reservations.
- Opt-in, localhost authenticated Fiji Jython relay for automatic macro sending to an already-running Fiji. If absent, safe manual clipboard fallback remains; no second JVM starts.
- Preserves TIFF header-based pixel size and rotation-center display from 0.7.0-alpha.1.
- No changes to measurement algorithms or JSON schema.
- Developer beta: Windows GUI, Fiji Jython relay, and ImageJ stack handoff require real-machine tests.

## [0.7.0-alpha.1] — TIFF metadata trial (2026-10-18)

- Read BL09W reconstruction TIFF ImageDescription first two tab-separated values (pixel size in µm/px; rotation center in px).
- Auto-initialize per-view calibration and scale bar when new dataset is opened; allow manual overrides and preserve saved comparison calibration.
- Show rotation center beside source image metadata; tooltip carries full value for compact layouts.
- No hardware operation, no changes to pixel intensity/profiles. Other planned v0.7.0 work is NOT included.

# Changelog

## [0.6.0] — 2026-10-18 (Development / Windows validation pending)

### Added
- BL09W finalized LOUPE pixel icon (application/window/taskbar/About; Windows EXE ICO included).
- Contrast editor with live Window/Level, histogram draggable range, Auto, Full Reset, numeric Min/Max.
- Resizable vertical image/profile splitter (image gets more height by default).
- Windows Fiji process detection before every launch; on existing Fiji, copy macro for manual execution in that instance, and do not start another JVM automatically.
- Windows packaging BAT with application icon.

### Changed
- Major controls start at Measure / Count; Profile controls moved under measurement toolbar.
- Rectangle mean X/Y hidden from profile-source selector; analysis functions retained for legacy sessions.
- Pixel Size presented with two decimal places; stored precision preserved until the user changes the value.
- Fiji Java Heap UI changed to GiB; corrected GiB display formula.
- PNG/PDF report title fixed to LOUPE and a smaller grey Version 0.6.0 line; profile color aligned with GUI cyan (#27b5e9).

### Safety and limits
- Normally sized in-memory Stack only; insufficient Java Heap or available RAM blocks import.
- Pre-existing Fiji is **not automatically remotely controlled**. Existing-instance handoff uses copy-paste macro instructions, rather than an unsafe second launch.
- Qt GUI, Windows taskbar, actual Fiji import, and PDF/PNG rendering require Windows verification before promoting release status.
- No changes intended to source TIFF arrays, ROI geometry, JSON Schema, or acquisition hardware.

# Changelog

LOUPEアプリのリリース版のみ記載。開発中の細かな変更はGitコミットに記録。

## [0.5.0] — 2026-10-18 (Development baseline)

### Release identity
- Phase A v1.6 + BL09W UI Standard v1.0 統合版を開発基準として採用。
- `loupe/version.py`にバージョン識別を集約。About、起動ログ、Bug Reportに版とビルド情報を反映。
- Gitバージョン管理をこのスナップショットから開始。旧開発ZIP群は歴史資料として維持。

### Included functionality (inherited from the earlier prototypes)
- 1〜4 VIEW横並び、最大化起動、連番TIFFスライダー、ドラッグ＆ドロップ。
- Line/Rectangle/Ellipse ROI編集、ラインプロファイル、パネル別Pixel Sizeとスケールバー。
- PNG/PDF比較レポート、CSV/JSON、ImageJ/Fiji連携、Stackメモリ確認、ログ・バグ報告。
- BL09W UI Design Standard v1.0のテーマ適用。

### Validation / limitations
- Python自動テストと静的検査の結果は`docs/RELEASE_NOTES_0.5.0.md`参照。
- Windows GUI実機・ImageJ/Fiji実起動・PDF実描画の本リリースでの再検証は**未実施**。
- 旧1.5.2は過去にWindows実機正常動作の報告あり。0.5.0とは同一の検証状態ではない。
- JSONのスキーマは今回変更していない。正式1.0.0以前の仕様変更余地がある。
