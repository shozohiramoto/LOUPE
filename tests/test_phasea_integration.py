"""Integration tests for the serializable Phase A model (GUI needs Windows test)."""
import csv
import json
import numpy as np
from loupe.exports import write_csv, write_session, read_session, imagej_macro
from loupe.measurements import create_annotation, validate_annotation, rect_mean_profile, measurement_row, write_measurement_csv


def test_session_roundtrip_all_shapes_and_legacy(tmp_path):
    annotations=[
        create_annotation('line',(1,2),(4,6),identifier='line-a'),
        create_annotation('rect',(10,20),(30,50),identifier='rect-a'),
        create_annotation('circle',(22,33),(27,33),identifier='circle-a'),
        create_annotation('count',(123,234),number=1,identifier='count-a')]
    state={'settings':{'profile_mode':True,'profile_source':'rect_x',
            'linked_slices':True,'width_px':11},
        'panels':[
            {'side':'LEFT','path':'C:/sample/rec00001.tif',
             'annotations_by_image':{'C:/sample/rec00001.tif':annotations}},
            {'side':'RIGHT','path':None,'annotations_by_image':{}}]}
    file=tmp_path/'comp.json'
    write_session(file,state)
    reread=read_session(file)
    assert reread['settings']['linked_slices']
    assert [validate_annotation(a) for a in reread['panels'][0]['annotations_by_image']['C:/sample/rec00001.tif']]==annotations
    assert reread['panels'][1]['annotations_by_image']=={}
    # Old Day 3 JSON remains loadable.
    legacy=tmp_path/'legacy.json'
    legacy.write_text(json.dumps({'schema':'loupe.comparison.v1','settings':{'width_px':1},
        'panels':[{'side':'LEFT','path':None},{'side':'RIGHT','path':None}]}))
    assert read_session(legacy)['settings']['width_px']==1


def test_rectangle_export_native_means(tmp_path):
    a=np.array([[1,3,5,7],[9,11,13,15]],dtype=np.float32)
    d,v,x,y=rect_mean_profile(a,[0,0,4,2],'x')
    assert v.tolist()==[5,7,9,11]
    file=tmp_path/'rect.csv'
    write_csv(file,[{'side':'LEFT','path':'C:/r.tif','slice':1,'width':2,
                     'kind':'rect_mean_x','line':None,'profile':(d,v),'coords':(x,y)}])
    with file.open(encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.DictReader(stream))
    assert len(rows)==4
    assert rows[2]['method']=='rect_mean_x'
    assert rows[2]['mean_intensity']=='9'
    assert rows[2]['y_px']=='0.5'


def test_roi_csv_multiple_slices(tmp_path):
    a=create_annotation('line',(0,0),(3,4),identifier='line-x')
    b=create_annotation('count',(2,3),number=5,identifier='count-x')
    rows=[measurement_row('LEFT','C:/rec0001.tif',2,a),
          measurement_row('RIGHT','C:/rec0049.tif',50,b)]
    file=tmp_path/'data.csv';write_measurement_csv(file,rows)
    with file.open(encoding='utf-8-sig',newline='') as stream:
        rows2=list(csv.DictReader(stream))
    assert rows2[0]['length_px']=='5.0'
    assert rows2[1]['count_number']=='5'


def test_macro_does_not_claim_to_reproduce_rectangle_mean():
    state={'settings':{'width_px':5,'profile_source':'rect_y'},
           'panels':[{'side':'LEFT','path':'C:/a.tif','levels':[-1,2],
                      'line':[[10,20],[50,20]]},{'side':'RIGHT','path':None}]}
    macro=imagej_macro(state)
    assert 'Rectangle mean profile' in macro
    assert 'run("Plot Profile")' not in macro
