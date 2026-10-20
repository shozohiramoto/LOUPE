import math
import pytest
from loupe.measurements import adjust_annotation, create_annotation, measurement, validate_annotation


def test_rectangle_corner_resize_preserves_opposite_corner_and_id():
    item=create_annotation('rect',(10,20),(30,40),identifier='r1')
    new=adjust_annotation(item,'se',(34,48),image_shape=(100,100))
    assert new['id']=='r1'
    assert new['rect']==[10.,20.,24.,28.]
    assert measurement(new)['area_px2']==672
    nw=adjust_annotation(new,'nw',(8,16),image_shape=(100,100))
    assert nw['rect']==[8.,16.,26.,32.]
    assert item['rect']==[10.,20.,20.,20.]  # original immutability/undo basis


def test_rectangle_moves_without_resizing_and_clamps_to_image():
    item=create_annotation('rect',(10,10),(20,30),identifier='rect')
    moved=adjust_annotation(item,'move',(37,65),drag_start=(15,20),image_shape=(50,50))
    assert moved['rect']==[32.,30.,10.,20.]
    bounded=adjust_annotation(item,'move',(999,999),drag_start=(15,20),image_shape=(50,50))
    assert bounded['rect']==[40.,30.,10.,20.]


def test_rectangle_minimum_size():
    item=create_annotation('rect',(10,10),(30,30),identifier='r')
    new=adjust_annotation(item,'nw',(500,500),image_shape=(1000,1000))
    assert new['rect'][2:]==[0.5,0.5]


def test_circle_center_drag_keeps_radius_and_id():
    c=create_annotation('circle',(20,30),(25,30),identifier='c')
    n=adjust_annotation(c,'move',(35,48),drag_start=(20,30),image_shape=(100,100))
    assert n['center']==[35,48]
    assert n['radius']==5
    assert n['id']=='c'


def test_circle_radius_drag_stays_circle_not_ellipse():
    c=create_annotation('circle',(20,30),(25,30),identifier='c')
    n=adjust_annotation(c,'radius',(20,43),image_shape=(100,100))
    assert n['center']==[20,30]
    assert n['radius']==13
    assert measurement(n)['area_px2']==pytest.approx(math.pi*169)
    assert validate_annotation(n)==n


def test_invalid_handle_and_geometry():
    c=create_annotation('circle',(20,30),(25,30),identifier='c')
    with pytest.raises(ValueError):adjust_annotation(c,'se',(1,1))
    with pytest.raises(ValueError):adjust_annotation(c,'move',(1,1))
    with pytest.raises(ValueError):adjust_annotation(c,'radius',(float('nan'),1))


def test_line_move_and_count_unchanged():
    line=create_annotation('line',(1,2),(4,6),identifier='l')
    moved=adjust_annotation(line,'move',(5,6),drag_start=(4,5),image_shape=(100,100))
    assert moved['start']==[2,3]
    assert moved['end']==[5,7]
    count=create_annotation('count',(5,5),number=1,identifier='c')
    with pytest.raises(ValueError):adjust_annotation(count,'move',(8,8),drag_start=(5,5))
