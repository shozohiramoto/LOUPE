"""Bounded, read-only HiPic HIS grayscale frame indexing for BL09W.

Only the validated 64-byte IM-header layout (8- or 16-bit single-channel)
is supported. Every frame header and the file terminator are checked before
pixels are read. Frame indexing never expands the complete image stack.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import re
import struct
import numpy as np

_REF = re.compile(r'^(.*\.his)::HIS:(\d{6,9})$', re.IGNORECASE)
_MAX_FRAME_BYTES = 512 * 1024 * 1024
_MAX_FRAMES = 100_000


def his_ref(path, index):
    return f'{Path(path).resolve()}::HIS:{int(index):06d}'


def parse_his_ref(path):
    match = _REF.fullmatch(str(path))
    return (Path(match.group(1)), int(match.group(2))) if match else None


def source_path(path):
    ref = parse_his_ref(path)
    return ref[0] if ref else Path(path)


def _header(f, offset, file_size):
    if offset + 64 > file_size:
        raise ValueError(f'Truncated HIS header at byte {offset}')
    f.seek(offset)
    raw = f.read(64)
    if len(raw) != 64 or raw[:2] != b'IM':
        raise ValueError(f'Invalid HIS IM frame header at byte {offset}')
    comment, width, height, xoffset, yoffset, typ = struct.unpack_from('<6H', raw, 2)
    if typ not in (0, 1, 2):
        raise ValueError(f'Unsupported HIS file type {typ}; only 8/16-bit grayscale is supported')
    channels = struct.unpack_from('<H', raw, 18)[0]
    if channels:
        raise ValueError('Multichannel HIS is not supported')
    if not (0 < width <= 32768 and 0 < height <= 32768):
        raise ValueError('Invalid HIS frame geometry')
    pixel_bytes = width * height * (2 if typ == 2 else 1)
    if pixel_bytes > _MAX_FRAME_BYTES:
        raise ValueError('HIS frame too large for the safe per-frame limit')
    pixel_offset = offset + 64 + comment
    end = pixel_offset + pixel_bytes
    if end > file_size:
        raise ValueError(f'Truncated HIS frame starting at byte {offset}')
    return (width, height, typ, pixel_offset, end)


@lru_cache(maxsize=6)
def _index(path, file_size, mtime_ns):
    """Return immutable offsets. Size/mtime are part of cache key."""
    offsets = []
    next_header = 0
    expected = None
    with open(path, 'rb') as f:
        while next_header < file_size:
            if len(offsets) >= _MAX_FRAMES:
                raise ValueError('HIS exceeds maximum supported number of frames')
            width, height, typ, pixel_offset, end = _header(f, next_header, file_size)
            geometry = (width, height, typ)
            if expected is None:
                expected = geometry
            elif geometry != expected:
                raise ValueError(f'HIS geometry or pixel type changes at frame {len(offsets)+1}')
            offsets.append(pixel_offset)
            next_header = end
    if not offsets or next_header != file_size:
        raise ValueError('HIS frame layout does not end exactly at file boundary')
    return expected, tuple(offsets)


def inspect_his(path):
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != '.his':
        raise ValueError('Select a real .his file')
    stat = path.stat()
    (w, h, kind), offsets = _index(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    return {'width': w, 'height': h, 'file_type': kind, 'dtype': 'uint16' if kind==2 else 'uint8',
            'frames': len(offsets), 'bytes_per_frame': w*h*(2 if kind==2 else 1)}


def read_his_frame(reference):
    parsed = parse_his_ref(reference)
    if not parsed:
        raise ValueError('Expected an indexed HIS frame reference')
    path, index = parsed
    stat = path.stat()
    (width, height, typ), offsets = _index(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    if not 0 <= index < len(offsets):
        raise IndexError('HIS frame number out of range')
    nbytes = width * height * (2 if typ == 2 else 1)
    with path.open('rb') as f:
        f.seek(offsets[index])
        raw = f.read(nbytes)
    if len(raw) != nbytes:
        raise ValueError('HIS frame was truncated during reading')
    dtype = np.dtype('<u2') if typ == 2 else np.dtype('u1')
    # Buffer remains owned by returned array; neither a global mmap nor whole-stack allocation.
    return np.frombuffer(raw, dtype=dtype).reshape(height, width).copy()
