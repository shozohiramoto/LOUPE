"""Pixel-size-preserving scale bars for native-coordinate orthogonal previews."""
import math

def scale_bar_spec(x_range, pixel_size_um, fraction=0.23):
    """Return (length_in_source_pixels, physical_length_um) for a nice scale bar.

    Preview plots have native source-pixel coordinates even when their image
    arrays are subsampled, so the three planes use the SAME physical scale.
    """
    if pixel_size_um is None or not math.isfinite(float(pixel_size_um)) or pixel_size_um <= 0:
        return None
    lo, hi = map(float, x_range)
    if hi <= lo or not math.isfinite(hi-lo):
        return None
    target = (hi-lo)*float(pixel_size_um)*fraction
    decade = 10**math.floor(math.log10(target))
    choices = [n*decade for n in (1,2,5,10)]
    physical = max((v for v in choices if v <= target), default=decade/2)
    return physical/float(pixel_size_um), physical


def scale_bar_label(physical_um):
    """Physical units (no fake gain in resolution from preview subsampling)."""
    if physical_um >= 1000:
        return f'{physical_um / 1000:g} mm'
    if physical_um < 0.1:
        return f'{physical_um * 1000:g} nm'
    return f'{physical_um:g} µm'

