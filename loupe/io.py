from pathlib import Path
import numpy as np
import tifffile

TIFF_EXTS = frozenset(('.tif', '.tiff'))
IMG_EXTS = frozenset(('.img',))
EXTS = TIFF_EXTS | IMG_EXTS


def discover(path):
    """Find a TIFF or BL09W IMG series without mixing different file formats.

    Explicit file selection always selects that file's format/series. Directory
    selections prefer TIFF when both TIFF and IMG intermediates exist; select a
    specific IMG file to request the IMG sequence instead.
    """
    path = Path(path)
    if path.is_file() and path.suffix.lower() in EXTS:
        family = IMG_EXTS if path.suffix.lower() in IMG_EXTS else TIFF_EXTS
        files = sorted(p for p in path.parent.iterdir()
                       if p.is_file() and p.suffix.lower() in family)
    elif path.is_dir():
        contents = [p for p in path.iterdir() if p.is_file()]
        tiffs = sorted(p for p in contents if p.suffix.lower() in TIFF_EXTS)
        imgs = sorted(p for p in contents if p.suffix.lower() in IMG_EXTS)
        files = tiffs if tiffs else imgs
    else:
        raise ValueError('Select a TIFF/IMG image or folder containing supported images')
    if not files:
        raise ValueError('No TIFF or supported IMG images found')
    return files, (files.index(path) if path.is_file() else 0)


def load_frame(path):
    path = Path(path)
    if path.suffix.lower() in IMG_EXTS:
        from .img_format import read_img
        return read_img(path)
    if path.suffix.lower() not in TIFF_EXTS:
        raise ValueError(f'Unsupported image extension: {path.suffix}')
    arr = tifffile.imread(path)
    if arr.ndim != 2:
        raise ValueError(f'Only 2D grayscale TIFF is supported: shape={arr.shape}')
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f'Unsupported data type: {arr.dtype}')
    return arr


def display_limits(arr):
    finite = np.asarray(arr)[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(finite, [0.5, 99.5])
    if hi <= lo:
        lo, hi = float(finite.min()), float(finite.max())
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def resolve_image_levels(arr, *, auto=True, manual=None, auto_levels=None):
    """Select valid levels BEFORE handing an image to pyqtgraph.ImageItem.

    pyqtgraph must never paint a float32/float64 ImageItem with unset levels.
    Manual contrast is respected when valid; otherwise safe auto limits apply.
    auto_levels is an optional cached (min, max) to avoid rescanning huge TIFFs.
    """
    import math
    if not auto and manual is not None:
        try:
            low, high = map(float, manual)
            if math.isfinite(low) and math.isfinite(high) and high > low:
                return low, high
        except (TypeError, ValueError):
            pass
    if auto_levels is None:
        auto_levels = display_limits(arr)
    low, high = map(float, auto_levels)
    if not (math.isfinite(low) and math.isfinite(high) and high > low):
        return 0.0, 1.0
    return low, high


def estimate_frame_bytes(path):
    """Estimate frame size from TIFF/IMG header for bounded prefetch."""
    path = Path(path)
    if path.suffix.lower() in IMG_EXTS:
        from .img_format import inspect_img
        return inspect_img(path)['data_bytes']
    if path.suffix.lower() not in TIFF_EXTS:
        raise ValueError(f'Unsupported image extension: {path.suffix}')
    with tifffile.TiffFile(path) as tf:
        if len(tf.pages)!=1 or len(tf.pages[0].shape)!=2:
            raise ValueError('Only a single grayscale image is supported')
        page=tf.pages[0]
        return int(np.prod(page.shape))*np.dtype(page.dtype).itemsize
