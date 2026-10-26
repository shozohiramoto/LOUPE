"""GUI-independent comparison, calibration and TIFF-drop helpers (Phase A v1.4)."""
from pathlib import Path
import math

MAX_PANELS = 4
TIFF_EXTENSIONS = frozenset(('.tif', '.tiff'))
IMAGE_EXTENSIONS = TIFF_EXTENSIONS | frozenset(('.img', '.his'))


def normalize_pixel_size(calibration):
    """Read v1.4 scalar calibration or older v1.3 x/y values.

    Assumes square source pixels. Legacy X is authoritative when X and Y differ.
    """
    if calibration is None:
        return 1.0
    if not isinstance(calibration, dict):
        raise ValueError('Calibration must be an object')
    value = float(calibration.get('pixel_size', calibration.get('x', calibration.get('y', 1.0))))
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Pixel size must be positive and finite')
    return value


def panel_indices_for_drop(start, count, maximum=MAX_PANELS):
    """Assign dropped files to consecutive comparison panels without wrapping."""
    if not (0 <= int(start) < maximum and 1 <= int(count) <= maximum):
        raise ValueError('Invalid TIFF drop target or file count')
    indices = list(range(int(start), int(start)+int(count)))
    if indices[-1] >= maximum:
        raise ValueError(f'Only {maximum} panels supported. Drop fewer TIFFs or start from an earlier panel.')
    return indices


def is_supported_drop_path(path):
    """Accept TIFF, BL09W IMG or HIS files and folders containing either."""
    p = Path(path)
    try:
        return p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS or (p.is_dir() and
            any(item.is_file() and item.suffix.lower() in (TIFF_EXTENSIONS | frozenset(('.img',))) for item in p.iterdir()))
    except (OSError, PermissionError):
        return False


def paths_from_mime(mime):
    """Extract local paths only; URLs from the network are never auto-read."""
    if not mime.hasUrls():
        return []
    urls = mime.urls()
    if not urls or len(urls) > MAX_PANELS:
        return []
    result = []
    for url in urls:
        if not url.isLocalFile():
            return []
        path = url.toLocalFile()
        if not path:
            return []
        result.append(path)
    return result
