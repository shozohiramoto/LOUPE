"""Legacy reconstruction TIFF-header interpretation without Qt or loading full image."""
from pathlib import Path
import numpy as np
import pytest
import tifffile
from loupe.tiff_metadata import (parse_reconstruction_description,
                                 read_reconstruction_metadata)
from loupe.calibration import normalize_calibration

DESCRIPTION='0.650000\t1016.500000\t1801\t0.000000\t0.000000\t116.299942'


def test_rec_description_from_uploaded_sample():
    assert parse_reconstruction_description(DESCRIPTION, width=2048)=={
        'pixel_size_um':0.65, 'rotation_center_px':1016.5,
        'source':'tiff_header'}


def test_tiff_header_only_parses_legacy(tmp_path):
    path=tmp_path/'rec00000.tif'
    tifffile.imwrite(path,np.zeros((2048,2048),dtype=np.float32),
                     description=DESCRIPTION,metadata=None)
    meta=read_reconstruction_metadata(path)
    assert meta['pixel_size_um']==pytest.approx(.65)
    assert meta['rotation_center_px']==pytest.approx(1016.5)


def test_does_not_guess_generic_imagej_description(tmp_path):
    p=tmp_path/'unrelated.tif'
    tifffile.imwrite(p,np.zeros((32,16),dtype=np.uint8),
                     description='ImageJ=1.53\nunit=um\n',metadata=None)
    assert read_reconstruction_metadata(p) is None


@pytest.mark.parametrize('desc',[
    '0.65 1016.5 1801 0 0 116',
    'ImageJ=1.53',
    '0.65\tNaN\t1801\t0\t0\t116',
    '-1\t1016.5\t1801\t0\t0\t116',
    '0.65\t2050\t1801\t0\t0\t116',
    '0.65\t1016.5\t1801\t0\t0',
    '',None,
])
def test_rejects_ambiguous_or_invalid_headers(desc):
    assert parse_reconstruction_description(desc,width=2048) is None


def test_header_source_retained_by_comparison_calibration():
    cal=normalize_calibration({'enabled':True,'pixel_size':.65,
                               'unit':'µm','source':'tiff_header'})
    assert cal['pixel_size']==.65
    assert cal['source']=='tiff_header'
    assert cal['x']==cal['y']==.65
    assert normalize_calibration({'enabled':True,'pixel_size':.65})['source']=='manual'


def test_gui_integration_readable_source():
    src=(Path(__file__).resolve().parents[1]/'loupe/gui.py').read_text()
    assert "read_reconstruction_metadata(path)" in src
    assert "self._header_cal_pending" in src
    assert "Rotation center:" in src
    assert "source': 'tiff_header'" in src
