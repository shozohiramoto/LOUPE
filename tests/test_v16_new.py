"""Headless v1.6 tests: no Qt needed for safety and data-compatibility logic."""
from pathlib import Path
from datetime import datetime
import os
import numpy as np
import pytest
import tifffile
from loupe.output_paths import (safe_name,source_folder_label,default_export_folder,
    suggested_path,reserve_unique_path,rollback_empty)
from loupe.imagej_bridge import (heap_from_cfg,inspect_sequence,stack_preflight,
    imagej_stack_macro,imagej_current_macro,MIB)
from loupe.cache import FrameCache
from loupe.exports import read_session,write_session
from loupe.report import report_grid


def test_sample_and_ct_rec_naming(tmp_path):
    sample=tmp_path/'Sample Name'/'rec'
    sample.mkdir(parents=True)
    source=sample/'rec0001.tif';source.write_bytes(b'123')
    path=suggested_path([source],'Report','pdf',at=datetime(2026,10,17,9,8,7))
    assert path.name=='Sample_Name_Report_20261017_090807.pdf'
    assert path.parent==tmp_path/'LOUPE_Exports'


def test_multi_view_and_radiography(tmp_path):
    d=tmp_path/'radiography_session';d.mkdir()
    source=d/'a.TIFF';source.write_bytes(b'')
    p=suggested_path([source,source],'ROI','csv',at=datetime(2026,10,17,0,0,0))
    assert p.name=='radiography_session_V2_ROI_20261017_000000.csv'
    assert source_folder_label(source)=='radiography_session'


@pytest.mark.parametrize('bad',['a/b','a:b','a<b','\\folder','   '])
def test_safe_filename(bad):
    s=safe_name(bad)
    assert all(x not in s for x in '<>:"/\\|?*') and len(s)>0


def test_unique_reservation_and_no_overwrite(tmp_path):
    p=tmp_path/'report.pdf';p.write_text('original')
    a=reserve_unique_path(p); a.write_text('new')
    b=reserve_unique_path(p);b.write_text('next')
    assert a.name=='report_001.pdf' and b.name=='report_002.pdf'
    assert p.read_text()=='original'
    rollback_empty(b)
    assert b.read_text()=='next'
    c=reserve_unique_path(p)
    rollback_empty(c)
    assert not c.exists()


def _make_tiffs(folder,n=3,shape=(8,12),dtype=np.uint16):
    folder.mkdir(exist_ok=True)
    files=[]
    for i in range(n):
        path=folder/f'rec{i:05}.tif'
        tifffile.imwrite(path,np.ones(shape,dtype=dtype)*i)
        files.append(path)
    return files


def test_stack_preflight_and_nonvirtual_macro(tmp_path):
    files=_make_tiffs(tmp_path/'rec')
    info=inspect_sequence(files)
    assert info['shape']==(8,12) and info['count']==3
    assert info['bytes']==8*12*2*3
    assert 'Virtual' not in imagej_stack_macro(info).split('run(',1)[1]
    assert 'Image Sequence...' in imagej_stack_macro(info)
    required=stack_preflight(info,available_bytes=4*1024*MIB,heap_mib=8192)
    assert required>info['bytes']


def test_reject_inconsistent_tiffs(tmp_path):
    files=_make_tiffs(tmp_path/'rec')
    tifffile.imwrite(files[1],np.ones((12,12),dtype=np.uint16))
    with pytest.raises(ValueError,match='Different image dimensions'):
        inspect_sequence(files)


def test_reject_non_supported_dtype(tmp_path):
    files=_make_tiffs(tmp_path/'rec',dtype=np.float64)
    with pytest.raises(ValueError,match='requires uint8'):
        inspect_sequence(files)


def test_reject_unknown_or_insufficient_heap(tmp_path):
    info=inspect_sequence(_make_tiffs(tmp_path/'rec'))
    for heap in (None,0):
        with pytest.raises(ValueError):stack_preflight(info,50*1024*MIB,heap)
    with pytest.raises(MemoryError):stack_preflight(info,50*1024*MIB,heap_mib=512)
    with pytest.raises(MemoryError):stack_preflight(info,1*MIB,heap_mib=8192)


def test_heap_config(tmp_path):
    exe=tmp_path/'ImageJ.exe';exe.write_text('')
    (tmp_path/'ImageJ.cfg').write_text('-Xmx8g\n-Xms256m')
    assert heap_from_cfg(exe)==8192


def test_no_wrong_folder_images(tmp_path):
    files=_make_tiffs(tmp_path/'rec')
    with pytest.raises(ValueError,match='other TIFF'):
        inspect_sequence(files[:1])


def test_frame_cache_lru_and_prefetch(tmp_path):
    cache=FrameCache(64)
    a=np.ones((2,4),dtype=np.float32)
    b=a*2;c=a*3
    cache.put('a',a);cache.put('b',b)
    assert cache.get('a') is not None
    cache.put('c',c)
    assert cache.get('b') is None and cache.get('c') is not None
    assert cache.bytes_used<=64
    cache.clear();assert cache.bytes_used==0
    assert not cache.prefetch('x',lambda _path:(_ for _ in ()).throw(RuntimeError('read')),lambda _:100)


def test_legacy_json_with_view_ids(tmp_path):
    state={'settings':{'width_px':1,'profile_mode':False},'panels':[
        {'side':'LEFT','path':None},{'side':'RIGHT','path':None}]}
    path=tmp_path/'old.json';write_session(path,state)
    assert [p['side'] for p in read_session(path)['panels']]==['LEFT','RIGHT']


def test_gui_integration_source():
    source=(Path(__file__).parents[1]/'loupe'/'gui.py').read_text(encoding='utf-8')
    assert "('VIEW 1', 'VIEW 2', 'VIEW 3', 'VIEW 4')" in source
    assert "('LEFT','RIGHT','THIRD','FOURTH')" in source
    assert "self.export_report_pdf" in source
    assert "self.open_imagej_stack" in source
    assert "render_report_image(items" in source
    assert "copy_roi_to_view" in source
    assert "overlay_profiles" in source
    assert 'FrameCache()' in source
    assert 'showMaximized()' in (Path(__file__).parents[1]/'main.py').read_text()


def test_report_grid_still_supports_four():
    assert report_grid(4)==(2,2)
