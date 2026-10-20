"""Read the legacy BL09W reconstruction TIFF metadata (header-only).

Supported legacy ImageDescription format, verified with rec00000.tif:
    pixel_size_um <TAB> rotation_center_px <TAB> ... (6 numeric fields)

This format is NOT a standard TIFF pixel resolution tag. Unrecognised formats
are left uncalibrated; no physical scale is ever guessed.
"""
from __future__ import annotations
import math
from pathlib import Path
import tifffile


def parse_reconstruction_description(description, *, width):
    """Return parsed values or None, without assuming generic TIFF descriptions.

    The six-token tab-delimited layout is legacy reconstruction software
    specific. Only the first two positions have confirmed meanings.
    """
    if not isinstance(description, str) or not 1 <= len(description) <= 512:
        return None
    tokens = description.strip().split('\t')
    if len(tokens) != 6 or any(not v.strip() for v in tokens):
        return None
    try:
        nums = [float(token) for token in tokens]
        size_um, center_px = nums[:2]
        width = int(width)
    except (ValueError, TypeError, OverflowError):
        return None
    if not all(math.isfinite(x) for x in nums):
        return None
    if not (width > 0 and 0 < size_um <= 1e5 and 0 <= center_px <= width):
        return None
    return {'pixel_size_um': size_um,
            'rotation_center_px': center_px,
            'source': 'tiff_header'}


def read_reconstruction_metadata(path):
    """Open TIFF header only; never load the 2D image into RAM."""
    with tifffile.TiffFile(Path(path)) as tif:
        if not tif.pages:
            return None
        page = tif.pages[0]
        tag = page.tags.get('ImageDescription')
        if tag is None:
            return None
        return parse_reconstruction_description(tag.value, width=page.imagewidth)
