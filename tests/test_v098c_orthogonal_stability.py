"""Regression tests for v0.9.8d Orthogonal Preview / Native Section fixes."""
from pathlib import Path
import json
import numpy as np
import pytest
import tifffile

from loupe.orthogonal.image_buffers import qt_owned_plane
from loupe.orthogonal.cache import build_preview, preview_planes
from loupe.diagnostics import (create_bug_report, start_fault_diagnostics,
                                close_fault_diagnostics, start_logging)

ROOT=Path(__file__).resolve().parents[1]


def test_strided_readonly_memmap_planes_become_independent_native_buffers(tmp_path):
    file=tmp_path/'cache.npy'
    mm=np.lib.format.open_memmap(file,mode='w+',dtype=np.float32,shape=(5,7,9))
    mm[:]=np.arange(5*7*9,dtype=np.float32).reshape(5,7,9)
    mm.flush()
    del mm
    mmap=np.load(file,mmap_mode='r')
    xy,yz,zx=preview_planes(mmap,4,3,2)
    assert not yz.flags.c_contiguous and not zx.flags.c_contiguous
    for a in (xy,yz,zx):
        owned=qt_owned_plane(a)
        assert owned.flags.owndata and owned.flags.c_contiguous
        assert owned.dtype==np.float32
        assert np.array_equal(owned,a)
        assert not np.shares_memory(owned,mmap)
        before=owned.copy()
        del mmap
        assert np.array_equal(owned,before)
        mmap=np.load(file,mmap_mode='r')


def test_qt_owned_plane_rejects_invalid_inputs():
    with pytest.raises(ValueError): qt_owned_plane(np.zeros((2,3,4)))
    with pytest.raises(ValueError): qt_owned_plane(np.array([['a','b']]))
    with pytest.raises(ValueError): qt_owned_plane(np.arange(10))


def test_two_concurrent_preview_caches_independent(tmp_path):
    frames=[]
    for i in range(7):
        p=tmp_path/f'rec{i:05}.tif'
        tifffile.imwrite(p,np.ones((14,13),dtype=np.float32)*i)
        frames.append(p)
    cache1=tmp_path/'cache1'
    cache2=tmp_path/'cache2'
    m1,p1=build_preview(frames,root=cache1)
    m2,p2=build_preview(frames,root=cache2)
    assert m1==m2
    assert np.array_equal(qt_owned_plane(np.load(p1,mmap_mode='r')[:,0,:]),
                          qt_owned_plane(np.load(p2,mmap_mode='r')[:,0,:]))


def test_native_middle_drag_is_distinct_from_offset_edit_logic():
    text=(ROOT/'loupe/gui.py').read_text(encoding='utf-8')
    assert 'event.button() == QtCore.Qt.MouseButton.MiddleButton' in text
    assert "getattr(host, 'measure_viewbox', None) is self" in text
    assert 'self.translateBy(x=last.x()-now.x(), y=last.y()-now.y())' in text
    assert "adjust = getattr(host, 'adjust_offset', None)" in text
    widget=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf-8')
    assert 'Middle-button drag: pan' in widget


def test_preview_crash_stage_logging_and_safe_shutdown():
    text=(ROOT/'loupe/orthogonal/viewer.py').read_text(encoding='utf-8')
    assert 'qt_owned_plane(arr)' in text
    for s in ('[PREVIEW_STAGE]', 'gui.cache.map.begin','gui.preview.render.done',
              'def _poll_close(self):','self._future_lock', 'wait=True'):
        assert s in text


def test_opt_in_faulthandler_log_is_exportable(tmp_path):
    # This enables the native fault hook only within this test, then restores.
    root=tmp_path/'logs'
    start_logging(root=root)
    try:
        start_fault_diagnostics(root=root)
        import loupe.diagnostics as diagnostics
        assert diagnostics._FAULT_FILE is not None
        diagnostics._FAULT_FILE.write('test diagnostic marker\n')
        diagnostics._FAULT_FILE.flush()
        z=create_bug_report(tmp_path/'report.zip',root=root)
        import zipfile
        with zipfile.ZipFile(z) as archive:
            assert 'fatal.log' in archive.namelist()
            assert 'test diagnostic marker' in archive.read('fatal.log').decode('utf-8')
    finally:
        close_fault_diagnostics()
