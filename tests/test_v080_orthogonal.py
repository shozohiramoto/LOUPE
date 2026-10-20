"""Headless tests for bounded orthogonal preview and v0.8.0 minor fixes."""
import json
from pathlib import Path
import numpy as np
import pytest
import tifffile

from loupe.orthogonal.cache import (
    EDGE, build_preview, cache_metadata, cache_paths, preview_planes,
    sample_indices, validate_ct_series)
from loupe.imagej_bridge import inspect_sequence, stack_preflight, imagej_stack_macro, MIB


def make_ct(folder, n=12, h=13, w=17):
    folder.mkdir(exist_ok=True, parents=True)
    paths=[]
    for z in range(n):
        yy,xx=np.mgrid[:h,:w]
        p=folder / f'rec{z:05d}.tif'
        tifffile.imwrite(p, (1000*z+10*yy+xx).astype('float32'))
        paths.append(p)
    return paths


def test_preview_is_bounded_and_source_order_is_correct(tmp_path):
    paths=make_ct(tmp_path/'ct')
    progress=[]
    meta, cache=build_preview(paths,root=tmp_path/'cache',on_progress=lambda n,total:progress.append((n,total)))
    arr=np.load(cache, mmap_mode='r')
    assert arr.shape==(12,13,17)
    assert arr.dtype==np.float32
    assert progress[-1]==(12,12)
    xy,yz,zx=preview_planes(arr, x=4, y=7, z=2)
    assert float(xy[7,4])==2074
    assert float(yz[2,7])==2074
    assert float(zx[2,4])==2074
    assert meta['quantitative'] is False
    # Second open is cache-only and does not read TIFF pixels.
    def bad_loader(_):raise RuntimeError('cache not used')
    again,cache2=build_preview(paths,root=tmp_path/'cache',loader=bad_loader)
    assert again==meta and cache==cache2


def test_large_cube_caps_xy_and_z_to_256(tmp_path):
    paths=make_ct(tmp_path/'ct',n=300,h=3,w=4)
    meta,cache=build_preview(paths,root=tmp_path/'cache',edge=256)
    assert meta['shape']==[256,3,4]
    assert cache.stat().st_size<256*3*4*4+512
    assert meta['samples_z'][0]==0 and meta['samples_z'][-1]==299
    assert len(set(meta['samples_z']))==256
    assert sample_indices(2048).size==EDGE


def test_cache_detects_modified_input_and_rebuilds(tmp_path):
    paths=make_ct(tmp_path/'ct',n=3)
    meta,cache=build_preview(paths,root=tmp_path/'cache')
    tifffile.imwrite(paths[-1], np.ones((13,17),dtype='float32')*1234)
    cache2,_=cache_paths(paths,root=tmp_path/'cache')
    assert cache2!=cache
    assert cache_metadata(paths,root=tmp_path/'cache') is None
    new,actual=build_preview(paths,root=tmp_path/'cache')
    assert actual==cache2 and float(np.load(actual, mmap_mode='r')[-1,0,0])==1234


def test_cancel_removes_partial_cache(tmp_path):
    paths=make_ct(tmp_path/'ct')
    with pytest.raises(InterruptedError):
        build_preview(paths,root=tmp_path/'cache',cancelled=lambda:True)
    assert list((tmp_path/'cache').glob('*.npy')) == []


def test_reject_missing_slices_and_other_image_types(tmp_path):
    paths=make_ct(tmp_path/'ct')
    with pytest.raises(ValueError,match='missing'):
        validate_ct_series(paths[:-2]+paths[-1:])
    with pytest.raises(ValueError,match='recNNNNN'):
        validate_ct_series([paths[0],tmp_path/'ct'/'q0001.img'])
    with pytest.raises(IndexError):
        preview_planes(np.zeros((3,4,5)), 5,0,0)


def test_stack_subset_memory_and_macro(tmp_path):
    paths=make_ct(tmp_path/'ct',n=16,h=100,w=80)
    sel=paths[5:10]
    info=inspect_sequence(sel,allow_subset=True)
    assert info['count']==5 and info['starting']==6
    macro=imagej_stack_macro(info)
    assert 'number=5' in macro and 'starting=6' in macro
    assert 'increment=1' in macro and 'virtual' in macro.lower()
    budget=stack_preflight(info,10*1024*MIB,2048)
    assert budget>info['bytes']
    with pytest.raises(ValueError,match='other TIFF'):
        inspect_sequence(sel)


def test_v080_gui_styling_without_qt():
    root=Path(__file__).resolve().parents[1]
    src=(root/'loupe/gui.py').read_text(encoding='utf-8')
    qss=(root/'bl09w_ui/qt_theme.qss').read_text(encoding='utf-8')
    assert 'self.show_scale_bar.setChecked(False)' in src
    assert "bool(state.get('show_scale_bar',False))" in src
    assert "def open_orthogonal_view(self)" in src
    assert "Orthogonal View (Preview)…" in src
    assert 'source_combo=QtWidgets.QComboBox()' in src
    assert 'target_combo=QtWidgets.QComboBox()' in src
    assert 'file_menu.setMinimumWidth' in src
    assert 'QComboBox::drop-down' in qss
