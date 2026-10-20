"""Isolated, headless validation for quantitative CT HR orthogonal extraction."""
import json
from pathlib import Path
import numpy as np
import pytest
import tifffile

from loupe.orthogonal.high_resolution import (
    SeriesValidationError, ExtractionCancelled, scan_series, extract_plane
)


def sample_ct(tmp_path, *, dtype=np.float32, count=5, h=7, w=9,
              compression=None, start=3, header=True):
    data = []
    for iz in range(count):
        a = np.array([[1000 * iz + 25*y + x for x in range(w)] for y in range(h)], dtype=dtype)
        desc = f"0.650000\t1016.500000\t1801\t0.000000\t0.000000\t116.299942" if header else None
        # Legacy parser requires rotation center within source width.
        if header:
            desc=f"0.650000\t4.500000\t1801\t0.000000\t0.000000\t116.299942"
        tifffile.imwrite(tmp_path / f"rec{start+iz:05d}.tif",a, description=desc,
                         metadata=None, compression=compression)
        data.append(a)
    return np.stack(data)


@pytest.mark.parametrize("dtype",[np.float32, np.uint16])
@pytest.mark.parametrize("plane,fixed", [("YZ",2),("ZX",4)])
@pytest.mark.parametrize("compression",[None,"zlib"])
def test_native_values_axis_dtype_and_subrange(tmp_path, dtype, plane, fixed, compression):
    data = sample_ct(tmp_path, dtype=dtype, compression=compression)
    ct = scan_series(tmp_path)
    assert ct.pixel_size_um == 0.65
    out = tmp_path / "exports"
    progress=[]
    result=extract_plane(ct, plane=plane, fixed_index=fixed, output_dir=out,
                         z_start=1, z_stop=4, on_progress=lambda a,b:progress.append((a,b)))
    pixels=tifffile.imread(result.tiff_path)
    expected=data[1:4,:,fixed] if plane=="YZ" else data[1:4,fixed,:]
    assert pixels.shape==expected.shape
    assert pixels.dtype==expected.dtype
    np.testing.assert_array_equal(pixels,expected)
    assert progress==[(1,3),(2,3),(3,3)]
    doc=json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert doc["quantitative"] is True
    assert doc["source_first_slice_index"]==4
    assert doc["source_last_slice_index"]==6
    assert doc["source_axis_order"]=="Z,Y,X"
    assert doc["horizontal_spacing_um"]==doc["vertical_z_spacing_um"]==0.65
    assert doc["output_axis_order"]==("Z,Y" if plane=="YZ" else "Z,X")
    with tifffile.TiffFile(result.tiff_path) as f:
        assert f.is_imagej
        assert str(f.pages[0].tags["ResolutionUnit"].value.name)=="CENTIMETER"
        xnum,xden=f.pages[0].tags["XResolution"].value
        ynum,yden=f.pages[0].tags["YResolution"].value
        assert (xnum/xden)==pytest.approx(10000/0.65,rel=1e-4)
        assert (ynum/yden)==pytest.approx(10000/0.65,rel=1e-4)
    assert sorted(p.suffix for p in out.iterdir())==[".json",".tif"]


def test_z_anisotropy_and_unknown_calibration(tmp_path):
    sample_ct(tmp_path, header=False)
    ct=scan_series(tmp_path)
    assert ct.pixel_size_um is None
    r=extract_plane(ct, plane="YZ",fixed_index=1, output_dir=tmp_path/"exp")
    assert r.metadata["horizontal_spacing_um"] is None
    assert r.metadata["vertical_z_spacing_um"] is None
    assert not tifffile.TiffFile(r.tiff_path).is_imagej
    ct=scan_series(tmp_path,pixel_size_um=0.5)
    r=extract_plane(ct, plane="ZX",fixed_index=2, output_dir=tmp_path/"exp", z_spacing_um=2.0)
    assert r.metadata["horizontal_spacing_um"]==0.5
    assert r.metadata["vertical_z_spacing_um"]==2
    assert r.metadata["z_calibration_source"]=="user_verified"


def test_missing_rejected(tmp_path):
    sample_ct(tmp_path)
    (tmp_path/"rec00005.tif").unlink()
    with pytest.raises(SeriesValidationError,match="Missing"):
        scan_series(tmp_path)


def test_duplicate_rejected(tmp_path):
    sample_ct(tmp_path)
    (tmp_path/"rec3.tif").write_bytes((tmp_path/"rec00003.tif").read_bytes())
    with pytest.raises(SeriesValidationError,match="Duplicate"):
        scan_series(tmp_path)


def test_shape_dtype_mismatch(tmp_path):
    sample_ct(tmp_path)
    tifffile.imwrite(tmp_path/"rec00007.tif", np.zeros((8,9),dtype=np.float32))
    with pytest.raises(SeriesValidationError,match="mismatch"):
        scan_series(tmp_path)


def test_dtype_mismatch(tmp_path):
    sample_ct(tmp_path)
    tifffile.imwrite(tmp_path/"rec00007.tif", np.zeros((7,9),dtype=np.uint16))
    with pytest.raises(SeriesValidationError,match="mismatch"):
        scan_series(tmp_path)


def test_corrupt_file_rejected(tmp_path):
    sample_ct(tmp_path)
    (tmp_path/"rec00007.tif").write_bytes(b"not a tiff")
    with pytest.raises((SeriesValidationError,ValueError)):
        scan_series(tmp_path)


def test_non_ct_series_rejected(tmp_path):
    tifffile.imwrite(tmp_path/"radio00001.tif",np.ones((4,4),dtype=np.uint16))
    tifffile.imwrite(tmp_path/"radio00002.tif",np.ones((4,4),dtype=np.uint16))
    with pytest.raises(SeriesValidationError):
        scan_series(tmp_path)


def test_zero_mutation_and_cancellation(tmp_path):
    source=sample_ct(tmp_path)
    ct=scan_series(tmp_path)
    n=[0]
    def report(done,total):n[0]=done
    with pytest.raises(ExtractionCancelled):
        extract_plane(ct,plane="YZ",fixed_index=2,output_dir=tmp_path/"exp",
                      cancelled=lambda: n[0]>=2,on_progress=report,read_mode="decode")
    assert list((tmp_path/"exp").iterdir())==[]
    assert np.array_equal(tifffile.imread(tmp_path/"rec00003.tif"),source[0])


def test_input_unchanged_on_success(tmp_path):
    sample_ct(tmp_path)
    files=sorted(tmp_path.glob("rec*.tif"))
    before=[(p.stat().st_size,p.stat().st_mtime_ns,p.read_bytes()) for p in files]
    ct=scan_series(files)
    extract_plane(ct,plane="ZX",fixed_index=3,output_dir=tmp_path/"exp")
    assert before==[(p.stat().st_size,p.stat().st_mtime_ns,p.read_bytes()) for p in files]


def test_invalid_index_z_range(tmp_path):
    sample_ct(tmp_path)
    ct=scan_series(tmp_path)
    with pytest.raises(IndexError):
        extract_plane(ct,plane="YZ",fixed_index=ct.width,output_dir=tmp_path/"exp")
    with pytest.raises(IndexError):
        extract_plane(ct,plane="ZX",fixed_index=ct.height,output_dir=tmp_path/"exp")
    with pytest.raises(IndexError):
        extract_plane(ct,plane="YZ",fixed_index=0,z_start=2,z_stop=2,output_dir=tmp_path/"exp")


def test_override_calibration_size_guard(tmp_path):
    sample_ct(tmp_path)
    with pytest.raises(SeriesValidationError,match="memory budget"):
        scan_series(tmp_path,max_frame_bytes=10)
    with pytest.raises(SeriesValidationError):
        scan_series(tmp_path,pixel_size_um=-1)


def test_input_file_selection_and_numeric_order(tmp_path):
    sample_ct(tmp_path,start=9)
    f=tmp_path/"rec00011.tif"
    ct=scan_series(f)
    assert ct.indices==(9,10,11,12,13)


def test_unexpected_header_metadata_rejected(tmp_path):
    sample_ct(tmp_path)
    tifffile.imwrite(tmp_path/"rec00007.tif",np.zeros((7,9),dtype=np.float32),
                     description="0.7\t4.5\t1801\t0\t0\t99",metadata=None)
    with pytest.raises(SeriesValidationError,match="Inconsistent TIFF pixel sizes"):
        scan_series(tmp_path)
