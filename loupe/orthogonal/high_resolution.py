"""LOUPE high-resolution CT orthogonal slice extraction (experimental engine).

No GUI imports; never modifies source images or preview caches. The caller must
run scan/extract on a worker thread to keep an interactive application responsive.

Input volume indexing (z, y, x) is native file order, with no interpolation.
YZ -> output[z, y], ZX -> output[z, x]. Row 0 is the lowest-numbered TIFF.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Callable, Optional, Sequence
import uuid

import numpy as np
import tifffile

from ..tiff_metadata import parse_reconstruction_description

_RECON_NAME = re.compile(r"^(rec)(\d+)\.(tif|tiff)$", re.IGNORECASE)
_SUPPORTED_DTYPES = {np.dtype("float32"), np.dtype("uint16")}
_MAX_FRAME_BYTES = 512 * 1024 * 1024


class SeriesValidationError(ValueError):
    """Input series is not an unambiguous, consistent reconstructed CT series."""


class ExtractionCancelled(InterruptedError):
    """High-resolution extraction was stopped by the operator."""


@dataclass(frozen=True)
class CTSeries:
    paths: tuple[Path, ...]
    indices: tuple[int, ...]
    shape: tuple[int, int]  # (height=y, width=x)
    dtype: str
    fingerprints: tuple[tuple[int, int], ...]  # (size, mtime_ns) from validated headers
    pixel_size_um: Optional[float]
    calibration_source: str

    @property
    def count(self) -> int:
        return len(self.paths)

    @property
    def width(self) -> int:
        return self.shape[1]

    @property
    def height(self) -> int:
        return self.shape[0]

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * np.dtype(self.dtype).itemsize


@dataclass(frozen=True)
class ExtractionResult:
    tiff_path: Path
    metadata_path: Path
    shape: tuple[int, int]
    dtype: str
    elapsed_seconds: float
    metadata: dict


def _positive_finite(value: Optional[float], field: str) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SeriesValidationError(f"Invalid {field}: {value!r}") from exc
    if not math.isfinite(result) or result <= 0:
        raise SeriesValidationError(f"{field} must be a finite positive number")
    return result


def _check_cancel(cancelled: Optional[Callable[[], bool]]) -> None:
    if cancelled is not None and cancelled():
        raise ExtractionCancelled("High-resolution orthogonal extraction cancelled")


def _candidate_paths(paths: Sequence[str | Path] | str | Path) -> tuple[Path, ...]:
    if isinstance(paths, (str, Path)):
        chosen = Path(paths)
        if chosen.is_dir():
            candidates = [p for p in chosen.iterdir() if p.is_file() and _RECON_NAME.fullmatch(p.name)]
        elif chosen.is_file() and _RECON_NAME.fullmatch(chosen.name):
            match = _RECON_NAME.fullmatch(chosen.name)
            candidates = [p for p in chosen.parent.iterdir() if p.is_file()
                          and (m := _RECON_NAME.fullmatch(p.name))
                          and m.group(1).lower() == match.group(1).lower()]
        else:
            raise SeriesValidationError("Choose a CT folder or a recNNNNN.tif/.tiff file")
    else:
        candidates = [Path(p) for p in paths]
    if len(candidates) < 2:
        raise SeriesValidationError("At least two recNNNNN TIFF slices are required")
    parsed = []
    for p in candidates:
        m = _RECON_NAME.fullmatch(p.name)
        if not m or not p.is_file():
            raise SeriesValidationError(f"Not a reconstructed CT TIFF slice: {p}")
        parsed.append((int(m.group(2)), p.resolve()))
    if len({p.parent for _, p in parsed}) != 1:
        raise SeriesValidationError("All CT slices must reside in a single folder")
    parsed.sort(key=lambda entry: entry[0])
    indices = [num for num, _ in parsed]
    for a, b in zip(indices, indices[1:]):
        if b == a:
            raise SeriesValidationError(f"Duplicate CT slice index {a}; check .tif/.tiff duplicates")
        if b != a + 1:
            raise SeriesValidationError(f"Missing CT slices between {a} and {b}; extraction aborted")
    return tuple(p for _, p in parsed)


def scan_series(paths: Sequence[str | Path] | str | Path, *,
                pixel_size_um: Optional[float] = None,
                cancelled: Optional[Callable[[], bool]] = None,
                on_progress: Optional[Callable[[int, int], None]] = None,
                max_frame_bytes: int = _MAX_FRAME_BYTES) -> CTSeries:
    """Validate all TIFF headers (no pixels loaded), continuity, shape and dtype.

    Caller-supplied pixel_size_um overrides legacy header calibration, e.g. for
    explicitly verified anisotropic datasets (use z_spacing_um at extraction).
    Without an override, partially calibrated series or inconsistent per-slice
    calibrations fail; unknown formats remain uncalibrated rather than guessed.
    """
    candidates = _candidate_paths(paths)
    override = _positive_finite(pixel_size_um, "pixel_size_um")
    if int(max_frame_bytes) < 1:
        raise SeriesValidationError("max_frame_bytes must be positive")
    shape = dtype = None
    spacing = []
    fingerprints = []
    for i, path in enumerate(candidates):
        _check_cancel(cancelled)
        try:
            initial_stat = path.stat()
            with tifffile.TiffFile(path) as tif:
                if len(tif.pages) != 1:
                    raise SeriesValidationError(f"Expected one image per TIFF: {path.name}")
                page = tif.pages[0]
                current_shape = tuple(page.shape)
                current_dtype = np.dtype(page.dtype)
                if len(current_shape) != 2 or any(n < 1 for n in current_shape):
                    raise SeriesValidationError(f"Expected 2D grayscale TIFF: {path.name}: {current_shape}")
                if current_dtype.newbyteorder("=") not in _SUPPORTED_DTYPES:
                    raise SeriesValidationError(f"Unsupported dtype in {path.name}: {current_dtype}; use uint16 or float32")
                if int(np.prod(current_shape)) * current_dtype.itemsize > max_frame_bytes:
                    raise SeriesValidationError(f"Uncompressed frame exceeds memory budget: {path.name}")
                if shape is None:
                    shape, dtype = current_shape, current_dtype
                elif current_shape != shape or current_dtype != dtype:
                    raise SeriesValidationError(f"Shape/dtype mismatch at {path.name}: {current_shape}/{current_dtype}, expected {shape}/{dtype}")
                tag = page.tags.get("ImageDescription")
                header = parse_reconstruction_description(tag.value, width=current_shape[1]) if tag else None
                spacing.append(header["pixel_size_um"] if header else None)
            final_stat = path.stat()
            signature = (initial_stat.st_size, initial_stat.st_mtime_ns)
            if signature != (final_stat.st_size, final_stat.st_mtime_ns):
                raise SeriesValidationError(f"CT slice changed during header validation: {path.name}")
            fingerprints.append(signature)
        except (OSError, tifffile.TiffFileError) as exc:
            raise SeriesValidationError(f"Unreadable TIFF header: {path.name}: {exc}") from exc
        if on_progress:
            on_progress(i + 1, len(candidates))
    _check_cancel(cancelled)
    if override is not None:
        final_spacing, source = override, "user_verified"
    elif all(x is None for x in spacing):
        final_spacing, source = None, "uncalibrated"
    elif any(x is None for x in spacing):
        raise SeriesValidationError("Mixed calibrated/uncalibrated TIFF headers; supply verified pixel_size_um")
    else:
        final_spacing = spacing[0]
        if any(not math.isclose(x, final_spacing, rel_tol=1e-7, abs_tol=1e-10) for x in spacing[1:]):
            raise SeriesValidationError("Inconsistent TIFF pixel sizes; supply verified pixel_size_um")
        source = "bl09w_legacy_tiff_header"
    result_indices = tuple(int(_RECON_NAME.fullmatch(p.name).group(2)) for p in candidates)
    return CTSeries(paths=candidates, indices=result_indices, shape=shape,
                    dtype=dtype.str, fingerprints=tuple(fingerprints),
                    pixel_size_um=final_spacing, calibration_source=source)


def _read_frame(path: Path, mode: str):
    """Prefer TIFF memmap for compatible uncompressed files; fallback to decode.

    Returns (array, backing_memmap) so the caller can promptly close mappings.
    """
    if mode not in ("auto", "memmap", "decode"):
        raise ValueError("read_mode must be auto, memmap or decode")
    if mode != "decode":
        try:
            arr = tifffile.memmap(path)
            return arr, arr if isinstance(arr, np.memmap) else None
        except (ValueError, TypeError, OSError):
            if mode == "memmap":
                raise
    return tifffile.imread(path), None


def _closed(memmap: Optional[np.memmap]) -> None:
    if memmap is not None:
        mm = getattr(memmap, "_mmap", None)
        if mm is not None:
            mm.close()


def extract_plane(series: CTSeries, *, plane: str, fixed_index: int,
                  output_dir: str | Path, z_start: int = 0, z_stop: Optional[int] = None,
                  z_spacing_um: Optional[float] = None, assume_isotropic: bool = True,
                  cancelled: Optional[Callable[[], bool]] = None,
                  on_progress: Optional[Callable[[int, int], None]] = None,
                  read_mode: str = "auto", output_prefix: str = "LOUPE") -> ExtractionResult:
    """Generate one lossless quantitative orthogonal TIFF and a JSON sidecar.

    z_start is inclusive and z_stop exclusive, in zero-based file-list order.
    This is not the same as the numeric suffix in recNNNNN filenames.
    No interpolation, 8-bit conversion or axis reversal is performed.
    Disk-backed scratch buffer is used even when output is small.
    """
    started = time.perf_counter()
    if not isinstance(series, CTSeries) or series.count < 2:
        raise TypeError("Pass CTSeries produced by scan_series")
    plane = str(plane).upper()
    if plane not in ("YZ", "ZX"):
        raise ValueError("plane must be YZ (X fixed) or ZX (Y fixed)")
    if isinstance(fixed_index, bool) or not isinstance(fixed_index, (int, np.integer)):
        raise ValueError("fixed_index must be an integer source-pixel coordinate")
    fixed_index = int(fixed_index)
    upper = series.width if plane == "YZ" else series.height
    if not 0 <= fixed_index < upper:
        raise IndexError(f"Fixed {'X' if plane == 'YZ' else 'Y'} index {fixed_index} outside 0..{upper-1}")
    if isinstance(z_start, bool) or not isinstance(z_start, (int, np.integer)):
        raise ValueError("z_start must be an integer")
    if z_stop is None:
        z_stop = series.count
    if isinstance(z_stop, bool) or not isinstance(z_stop, (int, np.integer)):
        raise ValueError("z_stop must be an integer")
    z_start, z_stop = int(z_start), int(z_stop)
    if not (0 <= z_start < z_stop <= series.count):
        raise IndexError("Require 0 <= z_start < z_stop <= number of CT slices")
    if z_spacing_um is not None:
        z_scale = _positive_finite(z_spacing_um, "z_spacing_um")
        z_source = "user_verified"
    elif assume_isotropic and series.pixel_size_um is not None:
        z_scale, z_source = series.pixel_size_um, "assumed_isotropic_ct"
    else:
        z_scale, z_source = None, "uncalibrated"
    x_scale = series.pixel_size_um
    if (x_scale is None) != (z_scale is None):
        # Separate scales can be represented in metadata, but incomplete
        # calibration must not look authoritative to downstream measurement.
        raise ValueError("Both in-plane and Z spacing must be calibrated, or neither")
    if read_mode not in ("auto", "memmap", "decode"):
        raise ValueError("read_mode must be auto, memmap or decode")
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        raise ValueError("output_dir must be a directory")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", output_prefix):
        raise ValueError("output_prefix must contain only letters, numbers, _, . or -")
    span = z_stop - z_start
    horizontal = series.height if plane == "YZ" else series.width
    output_shape = (span, horizontal)
    axis = "X" if plane == "YZ" else "Y"
    now = datetime.now(timezone.utc)
    # Collision-resistant unique name; never overwrite previous exports.
    dataset_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", series.paths[0].parent.name).strip("_")[:35] or "CT"
    name = (f"{output_prefix}_{dataset_slug}_{series.paths[0].stem}_{plane}_{axis}{fixed_index:05d}"
            f"_Z{series.indices[z_start]:05d}-{series.indices[z_stop-1]:05d}"
            f"_{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}")
    final_tiff, final_json = output_dir / (name + ".tif"), output_dir / (name + ".json")
    fd, scratch_name = tempfile.mkstemp(prefix=".loupe_hr_", suffix=".npy", dir=output_dir)
    os.close(fd)
    fd, temporary_tiff_name = tempfile.mkstemp(prefix=".loupe_hr_", suffix=".tif", dir=output_dir)
    os.close(fd)
    fd, temporary_json_name = tempfile.mkstemp(prefix=".loupe_hr_", suffix=".json", dir=output_dir)
    os.close(fd)
    scratch, temporary_tiff, temporary_json = map(Path, (scratch_name, temporary_tiff_name, temporary_json_name))
    result = None
    published = []
    try:
        _check_cancel(cancelled)
        result = np.lib.format.open_memmap(scratch, mode="w+", dtype=np.dtype(series.dtype), shape=output_shape)
        for row, path in enumerate(series.paths[z_start:z_stop]):
            _check_cancel(cancelled)
            expected_signature = series.fingerprints[z_start + row]
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns) != expected_signature:
                raise SeriesValidationError(f"CT source changed since header scan: {path.name}")
            frame = backing = None
            try:
                frame, backing = _read_frame(path, read_mode)
                if tuple(frame.shape) != series.shape or np.dtype(frame.dtype).str != series.dtype:
                    raise SeriesValidationError(f"Source TIFF changed since scan: {path.name}")
                if plane == "YZ":
                    result[row, :] = frame[:, fixed_index]
                else:
                    result[row, :] = frame[fixed_index, :]
            except (OSError, tifffile.TiffFileError) as exc:
                raise SeriesValidationError(f"Failed to decode {path.name}: {exc}") from exc
            finally:
                if frame is not None:
                    del frame
                _closed(backing)
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns) != expected_signature:
                raise SeriesValidationError(f"CT source changed during extraction: {path.name}")
            if on_progress:
                on_progress(row + 1, span)
        _check_cancel(cancelled)
        result.flush()
        source_files = [p.name for p in series.paths[z_start:z_stop]]
        source_file_signatures = [list(sig) for sig in series.fingerprints[z_start:z_stop]]
        metadata = {
            "schema": "loupe_orthogonal_high_resolution_v1",
            "quantitative": True,
            "interpolation": "none",
            "plane": plane,
            "source_axis_order": "Z,Y,X",
            "output_axis_order": "Z,Y" if plane == "YZ" else "Z,X",
            "output_rows": "ascending TIFF numerical index; not reversed",
            "output_columns": "ascending native Y" if plane == "YZ" else "ascending native X",
            "fixed_axis": axis,
            "fixed_index_px": fixed_index,
            "z_start_zero_based_inclusive": z_start,
            "z_stop_zero_based_exclusive": z_stop,
            "source_first_slice_index": series.indices[z_start],
            "source_last_slice_index": series.indices[z_stop - 1],
            "source_slice_files": source_files,
            "source_size_bytes_and_mtime_ns": source_file_signatures,
            "source_directory": str(series.paths[0].parent),
            "source_shape_yx": list(series.shape),
            "output_shape_row_col": list(output_shape),
            "dtype": np.dtype(series.dtype).name,
            "horizontal_spacing_um": x_scale,
            "vertical_z_spacing_um": z_scale,
            "in_plane_calibration_source": series.calibration_source,
            "z_calibration_source": z_source,
            "z_order_verified": False,
            "note": "Slice index order is numerical; physical upward/downward order must be verified by operator.",
            "generated_utc": now.isoformat(),
        }
        opts = {"photometric": "minisblack", "metadata": {"unit": "um"} if x_scale is not None else None}
        if x_scale is not None:
            # TIFF resolution units: pixels per centimetre, for ImageJ/Fiji.
            opts.update({"imagej": True,
                         "resolution": (10000.0 / x_scale, 10000.0 / z_scale),
                         "resolutionunit": "CENTIMETER"})
        else:
            # Readable by any standard TIFF viewer; physical scale absent.
            opts["description"] = "LOUPE high-resolution orthogonal TIFF (uncalibrated); see JSON sidecar"
        tifffile.imwrite(temporary_tiff, result, **opts)
        temporary_json.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        _check_cancel(cancelled)
        # Reserve without overwrite: a fresh UUID makes collisions vanishingly
        # unlikely; O_EXCL is a final guard rather than silently replacing.
        for src, dst in ((temporary_tiff, final_tiff), (temporary_json, final_json)):
            fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            published.append(dst)
            os.replace(src, dst)
        return ExtractionResult(tiff_path=final_tiff, metadata_path=final_json,
                                shape=output_shape, dtype=np.dtype(series.dtype).name,
                                elapsed_seconds=time.perf_counter() - started, metadata=metadata)
    except BaseException:
        for p in published:
            p.unlink(missing_ok=True)
        raise
    finally:
        if result is not None:
            result.flush()
            del result
        for p in (scratch, temporary_tiff, temporary_json):
            p.unlink(missing_ok=True)
