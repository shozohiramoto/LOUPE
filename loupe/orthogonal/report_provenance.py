"""Human-readable orthogonal report provenance derived from native extraction JSON.

An explicit top-to-bottom / left-to-right description is vital: a user must
never confuse the numeric Z slice index with a verified physical orientation.
This is intentionally pure Python so it can be tested without Qt installed.
"""
from __future__ import annotations


def _calibration(value, source, per):
    if value is None:
        return "unverified (no physical scale)"
    units = "µm/" + per
    descriptions = {
        "bl09w_legacy_tiff_header": "original TIFF header",
        "user_verified": "operator-verified entry",
        "assumed_isotropic_ct": "ISOTROPIC ASSUMPTION (not independently verified)",
        "uncalibrated": "uncalibrated",
    }
    return f"{float(value):.8g} {units} [{descriptions.get(source, source or 'source not specified')}]"


def orthogonal_provenance_lines(meta):
    """Build verifiable, printable provenance for PNG and PDF report panels.

    1-based coordinates are shown for operators, and zero-based for software.
    File suffix indices and ordinal slice positions are kept DISTINCT.
    All authoritative fields come from the produced native TIFF sidecar.
    """
    if not isinstance(meta, dict):
        raise TypeError("Orthogonal provenance requires extraction metadata")
    plane = meta['plane']
    if plane not in ('YZ', 'ZX'):
        raise ValueError('Only native YZ/ZX sections support this provenance')
    fixed = 'X' if plane == 'YZ' else 'Y'
    if meta['fixed_axis'] != fixed:
        raise ValueError('Fixed axis does not match orthogonal section plane')
    index = int(meta['fixed_index_px'])
    start = int(meta['z_start_zero_based_inclusive'])
    stop = int(meta['z_stop_zero_based_exclusive'])
    first = int(meta['source_first_slice_index'])
    last = int(meta['source_last_slice_index'])
    rows, cols = map(int, meta['output_shape_row_col'])
    if index < 0 or start < 0 or stop <= start or rows != stop-start or cols < 1 or last < first:
        raise ValueError('Invalid native section extraction bounds')
    horiz = 'Y' if plane == 'YZ' else 'X'
    xy = _calibration(meta.get('horizontal_spacing_um'),
                      meta.get('in_plane_calibration_source'), 'px')
    z = _calibration(meta.get('vertical_z_spacing_um'),
                     meta.get('z_calibration_source'), 'slice')
    gen = meta.get('generated_utc') or '(unavailable)'
    lines = [
        f'Cut position: {plane} (fixed {fixed}) | {fixed}={index+1} px (1-based, internal {index})',
        f'Section direction: horizontal +{horiz} → right; vertical increasing numeric Z → down',
        f'Source Z: rec{first:05d}–rec{last:05d} | ordinal slices {start+1}–{stop} (1-based), {rows} rows',
        f'XY spacing: {xy} | Z spacing: {z}',
        f'Generation: source TIFF native pixels | {meta["dtype"]} | {cols}×{rows} px | no interpolation / resampling / 8-bit conversion',
        f'Generated (UTC): {gen} | Physical Z up/down NOT verified',
    ]
    return tuple(lines)
