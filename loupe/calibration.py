"""Per-view square pixel calibration and readable physical scale-bar selection."""
import math
from .comparison import normalize_pixel_size

UNITS = ('nm', 'µm', 'mm')


def normalize_calibration(value=None, default=None):
    """Normalize per-panel calibration, using v1.4 global settings only as fallback.

    'pixel_size' always denotes physical length per image pixel, not per display
    pixel. Older x/y aliases are accepted but never presented as two controls.
    """
    src = value if value is not None else (default if default is not None else {})
    if not isinstance(src, dict):
        raise ValueError('Calibration must be an object')
    size = normalize_pixel_size(src)
    unit = src.get('unit', 'µm')
    if unit not in UNITS:
        raise ValueError(f'Invalid calibration unit: {unit!r}')
    source = src.get('source', 'manual')
    if source not in ('manual', 'tiff_header', 'dataset_json'):
        source = 'manual'  # legacy/untrusted JSON never invents an origin
    return {'enabled': bool(src.get('enabled', False)), 'pixel_size': size,
            'x': size, 'y': size, 'unit': unit, 'source': source}


def scale_bar_for_span(span_px, calibration, fraction=0.22):
    """Return a nice (1/2/5)*10^n scale-bar size below target view width.

    Returns {'pixels', 'physical', 'label'} or None if uncalibrated. A valid
    calibration is isotropic. This works independent of Qt/zoom/rendering.
    """
    cal = normalize_calibration(calibration)
    if not cal['enabled']:
        return None
    span_px = float(span_px)
    fraction = float(fraction)
    if not (math.isfinite(span_px) and span_px > 0 and 0 < fraction < 1):
        raise ValueError('Invalid scale-bar viewport')
    target = span_px * cal['pixel_size'] * fraction
    if not (math.isfinite(target) and target > 0):
        raise ValueError('Invalid physical span')
    power = math.floor(math.log10(target))
    candidates = [m * 10.0**e for e in range(power-1, power+2) for m in (1, 2, 5)]
    physical = max(x for x in candidates if x <= target * (1+1e-12))
    label = f'{physical:.8g} {cal["unit"]}'
    return {'pixels': physical/cal['pixel_size'], 'physical': physical, 'label': label}
