"""The verified BL09W 64-byte IMG container, without requiring Qt."""
import struct
from pathlib import Path
import numpy as np
import pytest
import tifffile
from loupe.img_format import inspect_img, read_img
from loupe.io import discover, load_frame, estimate_frame_bytes
from loupe.comparison import is_supported_drop_path


def write_img(path, pixels, dtype_code=2):
    pixels = np.asarray(pixels, dtype='<u2')
    h, w = pixels.shape
    header = bytearray(64)
    header[:4] = b'IM\x00\x00'
    struct.pack_into('<HH', header, 4, w, h)
    struct.pack_into('<I', header, 12, dtype_code)
    path.write_bytes(header + pixels.tobytes(order='C'))
    return path


def test_img_exact_pixel_values_and_header(tmp_path):
    raw=np.array([[0,1,200,65535],[777,4096,4097,9876]],dtype=np.uint16)
    p=write_img(tmp_path/'q0001.img',raw)
    info=inspect_img(p)
    assert info['shape']==(2,4)
    assert info['data_bytes']==16
    assert info['header_bytes']==64
    assert np.array_equal(read_img(p),raw)
    assert np.array_equal(load_frame(p),raw)
    assert load_frame(p).dtype==np.uint16
    assert estimate_frame_bytes(p)==16


def test_img_rejects_corrupt_and_unsupported(tmp_path):
    p=write_img(tmp_path/'x.img',np.arange(16,dtype=np.uint16).reshape(4,4))
    cases=[(p.read_bytes()[:25], 'short'),
           (b'NOPE'+p.read_bytes()[4:], 'magic'),
           (p.read_bytes()[:-1], 'size'),
           (p.read_bytes()+b'junk','extra')]
    for data,tag in cases:
        p.write_bytes(data)
        with pytest.raises(ValueError):load_frame(p)
    p=write_img(p,np.zeros((4,4),dtype=np.uint16),dtype_code=4)
    with pytest.raises(ValueError,match='pixel type'):
        load_frame(p)
    p.write_bytes(b'\x00'*64)
    with pytest.raises(ValueError):inspect_img(p)


def test_discover_img_and_mixed_formats(tmp_path):
    imgs=[write_img(tmp_path/f'q{i:04d}.IMG',np.ones((3,4),np.uint16)*i) for i in range(3)]
    files,index=discover(imgs[1]);assert files==imgs and index==1
    assert is_supported_drop_path(imgs[0]) and is_supported_drop_path(tmp_path)
    t=tmp_path/'rec00000.tif';tifffile.imwrite(t,np.ones((3,4),np.uint16))
    assert discover(tmp_path)[0]==[t]  # directory prefers TIFF to avoid mixing intermediates
    assert discover(imgs[2])[0]==imgs
    assert discover(t)[0]==[t]


def test_img_overflow_dimensions(tmp_path):
    p=write_img(tmp_path/'sample.img',np.zeros((2,3),np.uint16))
    data=bytearray(p.read_bytes());struct.pack_into('<HH',data,4,0,3);p.write_bytes(data)
    with pytest.raises(ValueError,match='dimensions'):inspect_img(p)


def test_img_and_tiff_independent_values_and_auto_ranges(tmp_path):
    from loupe.io import display_limits
    raw=np.arange(4096,dtype=np.uint16).reshape(64,64)
    p=write_img(tmp_path/'q0020.img',raw)
    t=tmp_path/'rec00000.tif';tifffile.imwrite(t,raw.astype(np.float32))
    assert np.array_equal(load_frame(p).astype(np.float32),load_frame(t))
    assert display_limits(load_frame(p))==display_limits(load_frame(t))


def test_real_uploaded_q0200_img_when_present():
    """Manual environment-specific sample check; no sample needed for Windows distribution."""
    real=Path('/mnt/data/q0200.img')
    if not real.exists():pytest.skip('User-provided sample not mounted')
    info=inspect_img(real)
    assert info['shape']==(2048,2048)
    assert info['dtype']=='uint16'
    assert real.stat().st_size==8388672
    arr=load_frame(real)
    assert arr.min()==5266
    assert arr.max()==65269
