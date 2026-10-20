"""Bounded orthogonal preview cache for a *contiguous reconstructed CT* series.

Only up to 256 source images are opened per cache build; a single source frame
is live at a time. Cache creation is atomic and user-cancellable. The output
is a float32 NumPy memory-mapped array (Z,Y,X), at most 64 MiB.

Preview samples pixels and slices rather than averaging: it is not quantitative
and must NEVER be passed into intensity or distance measurements.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

import numpy as np

from ..io import load_frame
import tifffile

EDGE = 256
RECON_NAME = re.compile(r'^(?:rec)(\d+)\.(?:tif|tiff)$', re.I)


def validate_ct_series(paths):
    paths = [Path(p) for p in paths]
    if len(paths) < 2:
        raise ValueError('Orthogonal view requires at least two reconstructed CT slices')
    numbers = []
    parents = set()
    for p in paths:
        m = RECON_NAME.fullmatch(p.name)
        if not m:
            raise ValueError('Orthogonal view currently supports recNNNNN.tif/.tiff CT series only')
        if not p.is_file():
            raise FileNotFoundError(p)
        numbers.append(int(m.group(1)))
        parents.add(p.resolve().parent)
    if len(parents) != 1 or any(b != a+1 for a, b in zip(numbers, numbers[1:])):
        raise ValueError('CT series must be in one folder, ordered and without missing slices')
    return paths


def sample_indices(size, limit=EDGE):
    if size < 1:
        raise ValueError('Invalid CT dimension')
    return np.linspace(0, size-1, min(size, limit)).round().astype(np.intp)


def source_fingerprint(paths):
    """Bounded scan of file metadata, not the image content."""
    h = hashlib.sha256(b'LOUPE Orthogonal preview v1\0')
    for p in paths:
        st = p.stat()
        h.update(f'{p.name}\0{st.st_size}\0{st.st_mtime_ns}\n'.encode('utf-8'))
    return h.hexdigest()


def default_cache_root():
    return Path(os.environ.get('LOCALAPPDATA') or (Path.home() / '.cache')) / 'LOUPE' / 'orthogonal'


def cache_paths(paths, root=None):
    key = source_fingerprint(paths)
    folder = Path(root) if root is not None else default_cache_root()
    return folder / f'{key}.npy', folder / f'{key}.json'


def cache_metadata(paths, root=None):
    npy, meta = cache_paths(paths, root)
    if not npy.is_file() or not meta.is_file():
        return None
    try:
        m = json.loads(meta.read_text(encoding='utf-8'))
        if m.get('schema') != 'loupe_ortho_preview_v1' or m.get('count') != len(paths):
            return None
        arr = np.load(npy, mmap_mode='r', allow_pickle=False)
        if arr.ndim != 3 or arr.dtype != np.float32 or arr.shape != tuple(m['shape']):
            return None
        if arr.size > EDGE**3:
            return None
        return m
    except (OSError, ValueError, TypeError, KeyError):
        return None


def read_preview_sample(path, yind, xind, *, loader=load_frame):
    """Sample a CT TIFF with minimal IO. Uncompressed contiguous TIFFs are
    memory-mapped; compressed/tiled files and injected test loaders fall back
    to the validated one-frame reader. No source is ever modified.
    """
    if loader is load_frame:
        try:
            frame=tifffile.memmap(path, mode='r')
            if frame.ndim != 2 or not np.issubdtype(frame.dtype, np.number):
                raise ValueError('Invalid grayscale TIFF image')
            values=np.asarray(frame[np.ix_(yind,xind)],dtype=np.float32)
            del frame
            return values
        except (ValueError, TypeError, OSError, KeyError, RuntimeError):
            pass  # Compressed/stripped noncontiguous TIFF; use safe decoder.
    frame=np.asarray(loader(path))
    if frame.ndim != 2 or not np.issubdtype(frame.dtype,np.number):
        raise ValueError('Invalid grayscale TIFF image')
    result=np.asarray(frame[np.ix_(yind,xind)],dtype=np.float32)
    del frame
    return result


def inspect_preview_shape(path, *, loader=load_frame):
    if loader is load_frame:
        with tifffile.TiffFile(path) as tif:
            if len(tif.pages) != 1 or len(tif.pages[0].shape) != 2:
                raise ValueError('Only single-page grayscale TIFF supported')
            page=tif.pages[0]
            if not np.issubdtype(np.dtype(page.dtype),np.number):
                raise ValueError('Invalid grayscale TIFF dtype')
            return tuple(page.shape)
    arr=np.asarray(loader(path))
    if arr.ndim != 2 or not np.issubdtype(arr.dtype,np.number):
        raise ValueError('Invalid grayscale CT slice')
    return tuple(arr.shape)


def build_preview(paths, *, root=None, on_progress=None, cancelled=None,
                  loader=load_frame, edge=EDGE):
    """Return a metadata dict and disk cache path. Raises InterruptedError on stop.

    Temporaries are confined to the cache directory and removed on failure.
    Cache identity changes whenever any input file's size/mtime changes.
    """
    if not 1 <= edge <= EDGE:
        raise ValueError('Preview edge must be between 1 and 256')
    paths = validate_ct_series(paths)
    cache, meta = cache_paths(paths, root)
    old = cache_metadata(paths, root)
    if old is not None:
        return old, cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    zind = sample_indices(len(paths), edge)
    tmp = cache.with_name(f'{cache.stem}.{uuid.uuid4().hex}.tmp.npy')
    tmp_meta = meta.with_name(f'{meta.stem}.{uuid.uuid4().hex}.tmp.json')
    arr_out = None
    try:
        # All source frames have identical dimensions in a valid CT stack.
        # Inspect headers rather than decoding the first 16 MiB frame.
        shape=inspect_preview_shape(paths[int(zind[0])], loader=loader)
        yind, xind = sample_indices(shape[0],edge),sample_indices(shape[1],edge)
        arr_out=np.lib.format.open_memmap(tmp,mode='w+',dtype=np.float32,
                               shape=(len(zind),len(yind),len(xind)))
        for zi, source in enumerate(zind):
            if cancelled is not None and cancelled():
                raise InterruptedError('Orthogonal cache generation cancelled')
            # Header consistency is cheap; check sampled frame shape before
            # reading pixels to avoid silent coordinate errors.
            src=paths[int(source)]
            if inspect_preview_shape(src,loader=loader)!=shape:
                raise ValueError(f'Inconsistent CT slice dimensions: {src.name}')
            arr_out[zi]=read_preview_sample(src,yind,xind,loader=loader)
            if on_progress is not None:
                on_progress(zi+1,len(zind))
        if cancelled is not None and cancelled():
            raise InterruptedError('Orthogonal cache generation cancelled')
        arr_out.flush()
        del arr_out
        arr_out = None
        m = dict(schema='loupe_ortho_preview_v1', count=len(paths),
            shape=[len(zind),len(yind),len(xind)], source_shape=list(shape),
            samples_z=zind.tolist(), samples_y=yind.tolist(), samples_x=xind.tolist(),
            dtype='float32', quantitative=False, source_folder=str(paths[0].parent))
        tmp_meta.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, cache)
        os.replace(tmp_meta, meta)
        return m, cache
    finally:
        if arr_out is not None:
            del arr_out
        tmp.unlink(missing_ok=True)
        tmp_meta.unlink(missing_ok=True)


def preview_planes(volume, x, y, z):
    """Read-only XY, YZ, ZX slices from a (Z,Y,X) memmap.

    YZ horizontal = Y, vertical = Z. ZX horizontal = X, vertical = Z.
    """
    if volume.ndim != 3:
        raise ValueError('Expected Z,Y,X volume')
    d, h, w = volume.shape
    if not (0 <= x < w and 0 <= y < h and 0 <= z < d):
        raise IndexError('Preview crosshair outside volume')
    return volume[z, :, :], volume[:, :, x], volume[:, y, :]
