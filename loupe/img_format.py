"""Strict reader for the BL09W legacy IM container supplied as q0200.img.

Only the observed format is supported: a 64-byte header, `IM\0\0` magic,
uint16 little-endian width/height at offsets 4/6, uint32 code 2 at offset
12, followed by uncompressed uint16 little-endian pixel samples (row-major).
The other header words are intentionally NOT interpreted as calibration.
"""
from pathlib import Path
import struct
import numpy as np

HEADER_SIZE = 64
MAGIC = b'IM\0\0'
PIXEL_TYPE_UINT16 = 2
MAX_PIXELS = 100_000_000


def inspect_img(path):
    """Validate the entire container without reading image pixels.

    Returns width/height/dtype/bytes; unknown IMG formats fail closed.
    """
    path = Path(path)
    actual_size = path.stat().st_size
    with path.open('rb') as f:
        header = f.read(HEADER_SIZE)
    if len(header) != HEADER_SIZE or header[:4] != MAGIC:
        raise ValueError(f'Unsupported IMG format or short header: {path.name}')
    width, height = struct.unpack_from('<HH', header, 4)
    pixel_type = struct.unpack_from('<I', header, 12)[0]
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise ValueError(f'Invalid IMG dimensions: {width} x {height}')
    if pixel_type != PIXEL_TYPE_UINT16:
        raise ValueError(f'Unsupported IMG pixel type: {pixel_type} (only uint16 code 2 verified)')
    expected_size = HEADER_SIZE + width * height * 2
    if actual_size != expected_size:
        raise ValueError(f'IMG length mismatch: expected {expected_size}, got {actual_size} bytes')
    return {'width': width, 'height': height, 'shape': (height, width),
            'dtype': 'uint16', 'data_bytes': width * height * 2,
            'header_bytes': HEADER_SIZE}


def read_img(path):
    """Load the verified legacy IMG as a native uint16 NumPy array."""
    details = inspect_img(path)
    with Path(path).open('rb') as f:
        f.seek(HEADER_SIZE)
        data = np.fromfile(f, dtype='<u2', count=details['width'] * details['height'])
    if data.size != details['width'] * details['height']:
        raise ValueError('IMG data truncated while reading')
    return data.reshape(details['shape'])
