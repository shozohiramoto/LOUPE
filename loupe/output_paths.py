"""Collision-resistant export naming and a predictable sample-level output folder."""
from datetime import datetime
from pathlib import Path
import os
import re


def safe_name(value):
    """File-system-friendly sample label (no home directory or path information)."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' ._')
    s = re.sub(r'\s+', '_', s)
    return (s[:65].rstrip(' ._') or 'dataset')


def source_folder_label(source):
    source = Path(source)
    folder = source if source.is_dir() else source.parent
    # Reconstructed CT images often live in SAMPLE/rec/recXXXXX.tif.
    if folder.name.lower() in ('rec', 'reconstruction', 'reconstructed'):
        return safe_name(folder.parent.name)
    return safe_name(folder.name)


def default_export_folder(sources, fallback=None):
    """Sibling LOUPE_Exports for the first loaded dataset; fallback to Documents."""
    first = next((Path(p) for p in sources if p), None)
    if first is not None:
        folder = first if first.is_dir() else first.parent
        if folder.name.lower() in ('rec', 'reconstruction', 'reconstructed'):
            folder = folder.parent
        return folder.parent / 'LOUPE_Exports'
    return (Path(fallback) if fallback else Path.home()/'Documents')/'LOUPE_Exports'


def suggested_path(sources, kind, ext, *, at=None, folder=None):
    items = [str(p) for p in sources if p]
    prefix = source_folder_label(items[0]) if items else 'LOUPE'
    stamp = (at or datetime.now()).strftime('%Y%m%d_%H%M%S')
    kind = safe_name(kind)
    extension = ext.lstrip('.')
    count = f'_V{len(items)}' if len(items)>1 else ''
    return (Path(folder) if folder else default_export_folder(items)) / f'{prefix}{count}_{kind}_{stamp}.{extension}'


def reserve_unique_path(path):
    """Atomically claim a path to prevent accidental overwrite, even if raced.

    The empty placeholder must be deleted by the caller if export fails.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    for index in range(0,10000):
        candidate = path if index==0 else path.with_name(f'{stem}_{index:03d}{path.suffix}')
        try:
            fd=os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY,0o666)
        except FileExistsError:
            continue
        else:
            os.close(fd)
            return candidate
    raise FileExistsError(f'No available unique filename based on {path}')


def rollback_empty(path):
    try:
        path=Path(path)
        if path.exists() and path.stat().st_size==0:path.unlink()
    except OSError:
        pass
