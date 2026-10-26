"""Headless regressions for Relative Linked View, RAM indicator and HIS streaming."""
import struct
from pathlib import Path
import numpy as np
import pytest
from loupe.io import discover, load_frame, estimate_frame_bytes
from loupe.his_format import inspect_his, his_ref, parse_his_ref, source_path
from loupe.relative_view import validate_offsets, anchor_range, move_range, center_difference
from loupe.ram_monitor import format_ram, memory_snapshot


def make_his(path, arrays, *, corrupt_last=False):
    with open(path, 'wb') as f:
        for i,frame in enumerate(arrays):
            h,w=frame.shape
            buf=bytearray(64)
            buf[:2]=b'IM'
            struct.pack_into('<H',buf,2,7 if i==0 else 0)
            struct.pack_into('<H',buf,4,w)
            struct.pack_into('<H',buf,6,h)
            struct.pack_into('<H',buf,12,2)
            struct.pack_into('<I',buf,14,len(arrays))
            f.write(buf)
            if i == 0:f.write(b'COMMENT')
            pixels=frame.astype('<u2').tobytes()
            if corrupt_last and i==len(arrays)-1:pixels=pixels[:-3]
            f.write(pixels)


def test_his_frames_in_place_and_correct_values(tmp_path):
    data=[(np.arange(35,dtype=np.uint16).reshape(5,7)+i*123) for i in range(4)]
    source=tmp_path/'a.his'
    make_his(source,data)
    info=inspect_his(source)
    assert (info['width'],info['height'],info['frames'],info['bytes_per_frame'])==(7,5,4,70)
    files,initial=discover(source)
    assert initial==0 and len(files)==4
    assert source_path(files[2])==source and parse_his_ref(files[2])[1]==2
    assert estimate_frame_bytes(files[1])==70
    for actual,ref in zip(data,files):
        frame=load_frame(ref)
        assert np.array_equal(actual,frame)
        assert frame.dtype==np.dtype('uint16')
    assert discover(files[2])[1]==2


def test_his_rejects_corrupted_or_unrelated_data(tmp_path):
    path=tmp_path/'bad.his'
    make_his(path,[np.arange(12,dtype=np.uint16).reshape(3,4)],corrupt_last=True)
    with pytest.raises(ValueError,match='Truncated'):inspect_his(path)
    path2=tmp_path/'not_his.his'
    path2.write_bytes(b'BAD'+b'\x00'*80)
    with pytest.raises(ValueError,match='Invalid HIS'):inspect_his(path2)


def test_only_real_his_file_selected(tmp_path):
    path=tmp_path/'a.his'
    make_his(path,[np.ones((3,4),dtype=np.uint16)])
    with pytest.raises(ValueError):discover(tmp_path)
    other=tmp_path/'rec00001.tif';other.write_bytes(b'x')
    files,index=discover(tmp_path)
    assert files==[other] and index==0


def test_relative_offsets_persist_when_zoom_changes():
    r=[[100.0,200.0],[50.0,150.0]]
    offsets=validate_offsets([[0,0],[10,-7],[-12,15],[0,22]])
    source=move_range(r,offsets[1])
    base=anchor_range(source,offsets[1])
    assert base==r
    assert move_range(base,offsets[2])==[[88,188],[65,165]]
    assert center_difference(source,base)==(10,-7)
    r_zoom=[[125,175],[75,125]]
    assert move_range(r_zoom,offsets[1])==[[135,185],[68,118]]
    assert validate_offsets([[1,2],[3,4],[5,6],[7,8]])[0]==(0,0)
    assert validate_offsets([[0,0],[float('nan'),0],[0,0],[0,0]])==[(0.0,0.0)]*4


def test_memory_monitor_does_not_invent_missing_measurements():
    label,tip,pct=format_ram(16*2**30,12*2**30,4*2**30,2*2**30)
    assert pct==75 and '12.0 GiB' in label and 'LOUPE process' in tip
    assert format_ram(None,None,None,None)[2] is None
    assert len(memory_snapshot())==4
