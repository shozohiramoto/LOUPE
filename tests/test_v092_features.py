"""v0.9.2: measurable, GUI-independent regression tests and source contracts."""
from pathlib import Path
import numpy as np
import pytest
import tifffile

from loupe.version import APP_VERSION
from loupe.fiji_transfer import make_transfer
from loupe.imagej_bridge import imagej_current_with_transfer_macro
from loupe.orthogonal.cache import (build_preview, sample_indices,
                                     read_preview_sample, inspect_preview_shape)

ROOT=Path(__file__).resolve().parents[1]
GUI=(ROOT/'loupe/gui.py').read_text(encoding='utf-8')
HR=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf-8')


def test_release_identity_and_ui_contract():
    assert APP_VERSION=='0.9.8d'
    for name in ('Session ▾','Report ▾','Export ▾','Linked profiles','Pan / Zoom',
                 'Save Session…','Open Session…','Profile Data (CSV)…',
                 'ROI Measurements (CSV)…'):
        assert name in GUI
    assert "self.width_label.setVisible(active)" in GUI
    assert "self.profile_width.setVisible(active)" in GUI
    assert "self.pan_button.setChecked(self.annotation_tool.currentData()=='pan')" in GUI
    assert "self.roi_selector.addItem(f'{i} — {display}',item['id'])" in GUI
    assert 'QScrollArea()' in HR
    assert "self.show_profile_button.setVisible(False)" in HR
    assert 'HighResROIController(self)' in HR
    assert "HighResROIController(self)" in HR


def test_memmap_preview_native_pixel_indices(tmp_path):
    path=tmp_path/'rec00000.tif'
    arr=np.arange(1000*1200,dtype=np.float32).reshape(1000,1200)
    tifffile.imwrite(path,arr,compression=None)
    yy,xx=sample_indices(1000),sample_indices(1200)
    assert inspect_preview_shape(path)==arr.shape
    assert np.array_equal(read_preview_sample(path,yy,xx),arr[np.ix_(yy,xx)])


def test_compressed_tiff_preview_fallback(tmp_path):
    path=tmp_path/'rec00000.tif'
    data=np.arange(32*49,dtype=np.uint16).reshape(32,49)
    tifffile.imwrite(path,data,compression='deflate')
    yy,xx=sample_indices(32),sample_indices(49)
    assert np.array_equal(read_preview_sample(path,yy,xx),data[np.ix_(yy,xx)])


def test_preview_cache_matches_source_for_rectangular_float_frames(tmp_path):
    folder=tmp_path/'frames';folder.mkdir()
    paths=[]
    for i in range(5):
        yy,xx=np.mgrid[:90,:125]
        data=(i*100+yy*.1+xx*.01).astype(np.float32)
        file=folder/f'rec{i:05d}.tif';tifffile.imwrite(file,data)
        paths.append(file)
    meta,p=build_preview(paths,root=tmp_path/'cache',edge=48)
    result=np.load(p)
    source=tifffile.imread(paths[2])
    assert np.array_equal(result[2],source[np.ix_(meta['samples_y'],meta['samples_x'])])
    assert result.shape==(5,48,48)
    assert meta['quantitative'] is False


def test_fiji_manifest_validate_and_preserve_geometry():
    annotations=[
        {'id':'line','type':'line','start':[.25,10.5],'end':[13.75,18.25]},
        {'id':'n1','type':'count','point':[5.5,6.5],'number':1},
    ]
    t=make_transfer(annotations=annotations,selected_id='line',width_px=5,
                    display_limits=(-20.,23.),
                    calibration={'enabled':True,'unit':'nm','pixel_size':650,'source':'manual'})
    assert t['rois'][0]['start']==[.25,10.5]
    assert t['line_width_px']==5
    assert t['display']=={'min':-20.,'max':23.}
    assert t['calibration']['width_um']==pytest.approx(.65)
    assert t['selected_id']=='line'


def test_invalid_fiji_contrast_rejected():
    with pytest.raises(ValueError):
        make_transfer(display_limits=(10.,10.))
    with pytest.raises(ValueError):
        make_transfer(display_limits=(float('nan'),100.))


def test_fiji_launch_macro_current_path_and_settings(tmp_path):
    path=tmp_path/'rec00000.tif'
    tifffile.imwrite(path,np.ones((10,10),dtype='float32'))
    t=make_transfer(annotations=[{'id':'a','type':'line','start':[0,1],'end':[3,5]}],
                    width_px=3, display_limits=(0,2))
    macro=imagej_current_with_transfer_macro(path,t)
    assert 'open(' in macro
    assert 'makeLine(0, 1, 3, 5)' in macro
    assert 'setMinAndMax(0, 2)' in macro
    assert 'roiManager("Add")' in macro


def test_existing_fiji_uses_manifest_not_macro_export():
    src=(ROOT/'loupe/fiji_bridge.py').read_text()
    receiver=(ROOT/'fiji/LOUPE_receiver.py').read_text()
    assert 'transfer=transfer' in GUI
    assert "'schema':'loupe_fiji_transfer_v1'" in (ROOT/'loupe/fiji_transfer.py').read_text()
    assert "'transfer':transfer" in src
    assert "_request('CAPS',manifest)!='TRANSFER_V1'" in src
    assert "if payload=='CAPS'" in receiver
    assert 'def _apply_transfer(image, transfer):' in receiver
    assert "image.setDisplayRange(lo,hi)" in receiver
    assert 'if len(paths)>1 and self.job.get' in receiver
