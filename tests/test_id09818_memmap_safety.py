"""Regression tests for ID098-18 read-only mapped input and cleanup."""
import numpy as np
import tifffile
from loupe.orthogonal import high_resolution as hr


def test_memmap_is_readonly(tmp_path, monkeypatch):
    src = tmp_path / 'rec00001.tif'
    tifffile.imwrite(src, np.arange(8*12,dtype=np.uint16).reshape(8,12))
    original = tifffile.memmap
    modes=[]
    def track(*args, **kwargs):
        modes.append(kwargs.get('mode'))
        return original(*args,**kwargs)
    monkeypatch.setattr(hr.tifffile, 'memmap',track)
    frame, backing=hr._read_frame(src, 'memmap')
    assert modes==['r']
    assert backing is frame
    assert not frame.flags.writeable
    np.testing.assert_array_equal(frame[0],np.arange(12,dtype=np.uint16))
    del frame, backing
