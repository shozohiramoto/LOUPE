"""Lossless IMG→TIFF bridge; only validated BL09W legacy IMG is accepted."""
from pathlib import Path
import os
import time
import uuid
import numpy as np
import tifffile
from .img_format import read_img

def converted_img_file(path, pixel_size_um=None, cache_dir=None):
    src=Path(path).resolve(strict=True)
    if src.suffix.lower()!='.img':raise ValueError('Expected IMG input')
    if cache_dir is None:
        base=os.environ.get('LOCALAPPDATA') or str(Path.home()/'.local'/'share')
        cache_dir=Path(base)/'LOUPE'/'Fiji_TEMP_Imports'
    directory=Path(cache_dir)
    directory.mkdir(parents=True,exist_ok=True)
    pixels=read_img(src)
    assert pixels.ndim==2 and pixels.dtype==np.uint16
    path_out=directory/('LOUPE_IMG_'+uuid.uuid4().hex+'.tif')
    kw={'imagej':True,'photometric':'minisblack','metadata':{'axes':'YX'}}
    if pixel_size_um is not None:
        spacing=float(pixel_size_um)
        if not 0<spacing<1e9:raise ValueError('Invalid pixel size')
        kw.update(resolution=(10000/spacing,10000/spacing),resolutionunit='CENTIMETER')
        kw['metadata']['unit']='um'
    try:
        tifffile.imwrite(path_out,pixels,**kw)
        return path_out
    except BaseException:
        path_out.unlink(missing_ok=True)
        raise

def clean_old_temporary_imports(cache_dir=None,max_age_days=3):
    base=os.environ.get('LOCALAPPDATA') or str(Path.home()/'.local'/'share')
    folder=Path(cache_dir) if cache_dir else Path(base)/'LOUPE'/'Fiji_TEMP_Imports'
    if not folder.is_dir():return 0
    cutoff=time.time()-max_age_days*86400
    count=0
    for entry in folder.glob('LOUPE_IMG_*.tif'):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink();count+=1
        except OSError:pass
    return count
