"""GUI-independent functional regression for v1.5 per-panel scale/report geometry."""
import math
from pathlib import Path
import pytest
import numpy as np
from loupe.calibration import normalize_calibration, scale_bar_for_span
from loupe.report import report_grid, source_view_range
from loupe.measurements import create_annotation, caption
from loupe.exports import read_session,write_session


def test_independent_panel_pixel_size_and_units():
    a=normalize_calibration({'enabled':True,'pixel_size':0.5,'unit':'µm'})
    b=normalize_calibration({'enabled':True,'pixel_size':150,'unit':'nm'})
    assert a['x']==a['y']==0.5
    assert b['x']==b['y']==150
    roi=create_annotation('rect',(0,0),(40,10),identifier='a')
    assert '20.00' in caption(roi,a)
    assert '6000.00' in caption(roi,b)


def test_old_global_calibration_fallback():
    old={'enabled':True,'x':.25,'y':.25,'unit':'µm'}
    assert normalize_calibration(None,old)['pixel_size']==.25
    assert normalize_calibration({'enabled':True,'pixel_size':.8,'unit':'mm'},old)['pixel_size']==.8
    assert not normalize_calibration(None)['enabled']


@pytest.mark.parametrize('invalid',[-2,0,float('nan'),float('inf')])
def test_invalid_calibration_rejected(invalid):
    with pytest.raises(ValueError):normalize_calibration({'pixel_size':invalid})


def test_invalid_unit_rejected():
    with pytest.raises(ValueError): normalize_calibration({'unit':'inch'})


@pytest.mark.parametrize('pixel_size,span,expected',[(0.5,1000,100.),(1,100,20.),(0.05,3000,20.)])
def test_scale_bar_round_nice_units(pixel_size,span,expected):
    cal={'enabled':True,'pixel_size':pixel_size,'unit':'µm'}
    size=scale_bar_for_span(span,cal)
    assert size['physical']==pytest.approx(expected)
    assert size['pixels']*pixel_size==pytest.approx(expected)
    assert size['pixels']<=span*0.22+1e-9
    assert size['label'].endswith('µm')


def test_scale_bar_unset_and_invalid_view():
    assert scale_bar_for_span(1000,{'enabled':False,'pixel_size':.5}) is None
    with pytest.raises(ValueError):scale_bar_for_span(0,{'enabled':True,'pixel_size':1})


def test_pan_zoom_changes_scale_bar_length_in_native_pixel_coordinates():
    cal={'enabled':True,'pixel_size':.5,'unit':'µm'}
    a=scale_bar_for_span(2000,cal)
    b=scale_bar_for_span(300,cal)
    assert a['physical']>b['physical']
    assert a['pixels']==a['physical']/.5
    assert b['pixels']==b['physical']/.5


def test_comparison_json_preserves_distinct_panels(tmp_path):
    cal1=normalize_calibration({'enabled':True,'pixel_size':.5,'unit':'µm'})
    cal2=normalize_calibration({'enabled':True,'pixel_size':120,'unit':'nm'})
    obj={'settings':{'calibration':cal1,'calibration_mode':'per_panel'},
         'panels':[{'side':'LEFT','path':None,'calibration':cal1,'show_scale_bar':True},
                   {'side':'RIGHT','path':None,'calibration':cal2,'show_scale_bar':False}]}
    f=tmp_path/'test.json';write_session(f,obj)
    reloaded=read_session(f)
    assert reloaded['panels'][0]['calibration']['pixel_size']==.5
    assert reloaded['panels'][1]['calibration']['pixel_size']==120
    assert reloaded['panels'][1]['show_scale_bar'] is False


@pytest.mark.parametrize('count,expected',[(1,(1,1)),(2,(2,1)),(3,(2,2)),(4,(2,2))])
def test_report_grid(count,expected):
    assert report_grid(count)==expected


@pytest.mark.parametrize('count',[0,5,-1,1.5])
def test_report_grid_invalid(count):
    with pytest.raises(ValueError):report_grid(count)


def test_source_view_clips_none_and_sorts_ranges():
    assert source_view_range(None,(200,500))==((0,500.),(0,200.))
    assert source_view_range([[100,20],[60,40]],(200,500))==((20,100),(40,60))


def test_source_view_range_bad_input():
    with pytest.raises(ValueError):source_view_range([[1,1],[0,100]],(100,100))
    with pytest.raises(ValueError):source_view_range([[0,float('inf')],[0,10]],(100,100))
