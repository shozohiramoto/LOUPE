import csv
import numpy as np
import pytest
from loupe.measurements import (create_annotation, validate_annotation,
    measurement, caption, rect_mean_profile, measurement_row, write_measurement_csv)


def test_basic_measures():
    line=create_annotation('line',(1,1),(4,5),identifier='one')
    assert measurement(line)['length_px']==5
    rect=create_annotation('rect',(5,7),(2,2),identifier='two')
    assert rect['rect']==[2.0,2.0,3.0,5.0]
    assert measurement(rect)['area_px2']==15
    circ=create_annotation('circle',(2,3),(5,7),identifier='three')
    assert measurement(circ)['diameter_px']==10
    count=create_annotation('count',(3.5,4.5),number=7,identifier='four')
    assert caption(count)=='7'
    assert validate_annotation(circ)==circ
    assert validate_annotation(rect)==rect
    assert validate_annotation(line)==line


def test_rect_profile_x_y():
    arr=np.array([[1,2,3,4],[5,6,7,8],[9,10,11,12]],dtype=float)
    d,v,x,y=rect_mean_profile(arr,[1,0,2,3],'x')
    assert d.tolist()==[0,1]
    assert v.tolist()==[6,7]
    assert x.tolist()==[1,2]
    assert y.tolist()==[1,1]
    d,v,x,y=rect_mean_profile(arr,[1,0,2,3],'y')
    assert v.tolist()==[2.5,6.5,10.5]
    assert y.tolist()==[0,1,2]
    assert x.tolist()==[1.5]*3


def test_clipping_nan_and_empty():
    a=np.array([[1.,np.nan,3.],[2.,4.,6.]])
    _,v,_,_=rect_mean_profile(a,[-1,-1,4,3],'x')
    assert v.tolist()==[1.5,4,4.5]
    assert all(len(x)==0 for x in rect_mean_profile(a,[8,8,3,3],'x'))
    with pytest.raises(ValueError):validate_annotation({'type':'circle','id':'bad','center':[0,0],'radius':-1})


def test_measurement_csv(tmp_path):
    a=create_annotation('count',(10,20),number=4,identifier='c4')
    file=tmp_path/'rois.csv';write_measurement_csv(file,[measurement_row('RIGHT','C:/data/rec49.tif',50,a)])
    with open(file,encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.DictReader(stream))
    assert rows[0]['count_number']=='4'
    assert rows[0]['slice_1_based']=='50'
