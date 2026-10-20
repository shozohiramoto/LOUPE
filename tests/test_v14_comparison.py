"""Regression tests for 4-view comparisons, scalar calibration and TIFF drop."""
import json
import math
from pathlib import Path

import numpy as np
import pytest
import tifffile

from loupe.comparison import (
    MAX_PANELS, normalize_pixel_size, panel_indices_for_drop,
    is_supported_drop_path, paths_from_mime,
)
from loupe.exports import read_session, write_session, imagej_macro


def test_one_manual_pixel_size_and_legacy_values():
    assert normalize_pixel_size({'pixel_size': 0.5, 'x': 0.1, 'y': 2}) == 0.5
    assert normalize_pixel_size({'x': 0.5, 'y': 0.5}) == 0.5
    assert normalize_pixel_size({'x': 0.5, 'y': 0.3}) == 0.5
    assert normalize_pixel_size({}) == 1.0
    assert normalize_pixel_size(None) == 1.0


@pytest.mark.parametrize('bad', [-1, 0, float('inf'), float('nan'), 'bad'])
def test_bad_calibration_rejected(bad):
    with pytest.raises(ValueError):
        normalize_pixel_size({'pixel_size': bad})


@pytest.mark.parametrize('count', [1, 2, 3, 4])
def test_1_to_4_panel_json_roundtrip(tmp_path, count):
    panels = [dict(side=f'VIEW-{i}', path=None, levels=[0, 1]) for i in range(count)]
    state = dict(settings={'width_px': 1, 'calibration': {'pixel_size': 0.5}}, panels=panels)
    f = tmp_path / 'session.json'
    write_session(f, state)
    restored = read_session(f)
    assert restored['panels'] == panels
    assert restored['settings']['calibration']['pixel_size'] == 0.5
    macro = imagej_macro(state)
    assert macro.count('setBatchMode(false)') == 1


def test_schema_rejects_more_than_four(tmp_path):
    path=tmp_path / 'bad.json'
    path.write_text(json.dumps({'schema':'loupe.comparison.v1','settings':{},'panels':[{}]*5}))
    with pytest.raises(ValueError):
        read_session(path)


def test_drag_drop_panel_assignments():
    assert panel_indices_for_drop(0,4) == [0,1,2,3]
    assert panel_indices_for_drop(1,3) == [1,2,3]
    assert panel_indices_for_drop(3,1) == [3]
    with pytest.raises(ValueError):
        panel_indices_for_drop(3,2)
    with pytest.raises(ValueError):
        panel_indices_for_drop(0,0)
    with pytest.raises(ValueError):
        panel_indices_for_drop(0,5)


def test_tiff_drop_filter(tmp_path):
    folder = tmp_path/'sample';folder.mkdir()
    img=folder/'rec0001.TIFF';tifffile.imwrite(img,np.ones((5,5),dtype=np.uint16))
    assert is_supported_drop_path(img)
    assert is_supported_drop_path(folder)
    assert not is_supported_drop_path(tmp_path/'unknown.txt')
    empty=tmp_path/'empty';empty.mkdir()
    assert not is_supported_drop_path(empty)


class FakeUrl:
    def __init__(self, path, local=True):self.path=path;self.local=local
    def isLocalFile(self):return self.local
    def toLocalFile(self):return self.path


class FakeMime:
    def __init__(self, urls):self.u=urls
    def hasUrls(self):return bool(self.u)
    def urls(self):return self.u


def test_drops_only_local_urls():
    assert paths_from_mime(FakeMime([FakeUrl('C:/data/a.tif')])) == ['C:/data/a.tif']
    assert paths_from_mime(FakeMime([FakeUrl('https://abc', False)])) == []
    assert paths_from_mime(FakeMime([])) == []
    assert paths_from_mime(FakeMime([FakeUrl(f'{i}.tif') for i in range(5)])) == []
