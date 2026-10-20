import math
import json
import zipfile
import numpy as np
import pytest
from loupe.measurements import (create_annotation, validate_annotation, adjust_annotation,
    frame, caption, physical_dimensions, snap_endpoint, measurement, rotated_rect_mean_profile)
from loupe.exports import write_session, read_session
from loupe.diagnostics import start_logging,close_logging,logger,log_action,create_bug_report,sanitize


def test_ellipse_non_circular_rectangle_creation():
    e=create_annotation('ellipse',(12,20),(52,40),identifier='el')
    assert e['center']==[32,30]
    assert e['width']==40 and e['height']==20
    assert validate_annotation(e)==e
    assert caption(e)=='40.0 × 20.0 px'
    assert 'px²' not in caption(e)


def test_rectangle_rotation_and_corner_edits():
    r=create_annotation('rect',(10,20),(50,40),identifier='r')
    rotated=adjust_annotation(r,'rotate',(30+15,30),image_shape=(200,200))
    assert rotated['angle']==pytest.approx(90)
    assert frame(rotated)[2:4]==(40,20)
    # Drag a rotated corner by +5px along its local horizontal axis.
    rad=math.radians(rotated['angle'])
    cx,cy,w,h,ang=frame(rotated)
    x,y=cx+(w/2+5)*math.cos(rad)-(h/2)*math.sin(rad),cy+(w/2+5)*math.sin(rad)+(h/2)*math.cos(rad)
    modified=adjust_annotation(rotated,'se',(x,y))
    assert frame(modified)[2]==pytest.approx(45)
    assert frame(modified)[3]==pytest.approx(20)
    assert modified['id']=='r'


def test_shift_square_when_resizing_drawn_rectangle():
    r=create_annotation('rect',(10,10),(30,22),identifier='r')
    new=adjust_annotation(r,'se',(38,17),constrain=True)
    assert frame(new)[2]==pytest.approx(frame(new)[3])
    assert new['rect'][:2]==pytest.approx([10,10])


def test_shift_circle_when_resizing_ellipse():
    e=create_annotation('ellipse',(10,20),(60,40),identifier='el')
    n=adjust_annotation(e,'se',(66,50),constrain=True)
    assert n['width']==pytest.approx(n['height'])
    assert validate_annotation(n)==n

@pytest.mark.parametrize('cursor',[(22,3),(5,20),(-5,20),(-18,-16),(50,0)])
def test_shift_snap_eight_possible_directions(cursor):
    fx,fy=5,5
    x,y=snap_endpoint((fx,fy),cursor)
    a=(math.degrees(math.atan2(y-fy,x-fx))+360)%180
    assert min(abs(a-v) for v in (0,45,90,135,180))<1e-7


def test_line_shift_edit_fixed_opposite_end():
    a=create_annotation('line',(10,10),(20,16),identifier='a')
    changed=adjust_annotation(a,'end',(19,13),constrain=True)
    assert changed['start']==[10,10]
    assert changed['end'][1]==pytest.approx(10)
    changed2=adjust_annotation(a,'start',(0,25),constrain=True)
    assert changed2['end']==[20,16]


def test_angle_snapping_keeps_inside_image():
    p=snap_endpoint((18,18),(100,100),(20,20))
    assert p==pytest.approx([19,19])


def test_calibration_disabled_and_anisotropy():
    r=create_annotation('rect',(0,0),(100,50),identifier='r',angle=90)
    cal={'enabled':True,'x':.5,'y':1.5,'unit':'µm'}
    assert physical_dimensions(r,cal)['width']==pytest.approx(150)
    assert physical_dimensions(r,cal)['height']==pytest.approx(25)
    assert 'µm' in caption(r,cal)
    assert physical_dimensions(r,dict(cal,enabled=False)) is None
    line=create_annotation('line',(0,0),(3,4),identifier='l')
    assert physical_dimensions(line,cal)['length']==pytest.approx(math.hypot(1.5,6))


def test_rotated_rectangle_mean_finite_and_axis_specific():
    a=np.arange(10000,dtype=float).reshape(100,100)
    r=create_annotation('rect',(35,40),(65,60),angle=30,identifier='rot')
    d,v,x,y=rotated_rect_mean_profile(a,r,'x')
    assert len(d)==30 and len(v)==30
    assert np.isfinite(v).any()
    assert len(x)==len(v)==len(y)


def test_json_v13_roundtrip_and_legacy(tmp_path):
    item=create_annotation('ellipse',(0,0),(11,25),angle=35,identifier='e')
    state={'settings':{'calibration':{'enabled':True,'x':0.5,'y':0.6,'unit':'µm'}},
       'panels':[{'annotations_by_image':{'a':[item]}},{}]}
    dest=tmp_path/'session.json';write_session(dest,state)
    restored=read_session(dest)
    assert validate_annotation(restored['panels'][0]['annotations_by_image']['a'][0])==item
    assert restored['settings']['calibration']['x']==0.5
    legacy={'id':'c','type':'circle','center':[10,10],'radius':5}
    assert validate_annotation(legacy)==legacy


def test_readable_bug_report_and_no_tiff(tmp_path):
    start_logging(tmp_path)
    logger().info('Testing reproducibility')
    log_action('Rectangle rotated',angle=30)
    report=create_bug_report(tmp_path/'report.zip',
         description='Crash after rotate',expected='Shape remains selected',root=tmp_path)
    with zipfile.ZipFile(report) as f:
        assert set(f.namelist())=={'report.txt','loupe.log','error.log','environment.txt'}
        assert 'Rectangle rotated' in f.read('loupe.log').decode()
        assert b'Crash after rotate' in f.read('report.txt')
        assert not any(x.lower().endswith('.tif') for x in f.namelist())
    close_logging()


def test_sanitize_user_directories():
    assert '<USER>' in sanitize(r'C:\Users\alice\Documents\file.tif') or '<USER_HOME>' in sanitize(r'C:\Users\alice\Documents\file.tif')
