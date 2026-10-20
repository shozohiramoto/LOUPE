import math
import pytest
from loupe.measurements import adjust_annotation, create_annotation, measurement, validate_annotation, measurement_row


def _line(a=(2,3),b=(5,7)):
    return create_annotation('line',a,b,identifier='line-7')


def test_start_endpoint_drag_and_length():
    origin=_line()
    changed=adjust_annotation(origin,'start',(2,7),image_shape=(100,100))
    assert changed['start']==[2,7]
    assert changed['end']==[5,7]
    assert changed['id']==origin['id']
    assert measurement(changed)['length_px']==pytest.approx(3)
    assert origin['start']==[2,3]


def test_end_endpoint_drag_and_length():
    changed=adjust_annotation(_line(),'end',(8,11),image_shape=(100,100))
    assert changed['start']==[2,3]
    assert changed['end']==[8,11]
    assert measurement(changed)['length_px']==pytest.approx(10)


def test_drag_move_preserves_length_angle_id():
    origin=_line()
    moved=adjust_annotation(origin,'move',(11,16),drag_start=(9,12),image_shape=(100,100))
    assert moved['start']==[4,7]
    assert moved['end']==[7,11]
    assert moved['id']==origin['id']
    assert measurement(moved)==measurement(origin)
    assert validate_annotation(moved)==moved


def test_move_clamps_whole_segment_to_image():
    origin=_line((2,3),(5,7))
    moved=adjust_annotation(origin,'move',(100,100),drag_start=(3.5,5),image_shape=(10,10))
    assert moved['start']==[6,5]
    assert moved['end']==[9,9]
    assert measurement(moved)['length_px']==5


def test_endpoint_clips_to_original_image_coordinates():
    origin=_line()
    changed=adjust_annotation(origin,'end',(100,-50),image_shape=(10,10))
    assert changed['end']==[9,0]


def test_move_without_drag_start_raises():
    with pytest.raises(ValueError,match='drag_start'):
        adjust_annotation(_line(),'move',(7,8))


def test_degenerate_and_invalid_endpoint_rejected():
    with pytest.raises(ValueError,match='too short'):
        adjust_annotation(_line(),'end',(2,3))
    with pytest.raises(ValueError):
        adjust_annotation(_line(),'start',(float('nan'),2))
    with pytest.raises(ValueError,match='Unknown line handle'):
        adjust_annotation(_line(),'radius',(2,3))


def test_editable_line_json_safe_and_csv_updated():
    changed=adjust_annotation(_line(),'end',(8.5,6),image_shape=(100,100))
    row=measurement_row('LEFT','C:/temp/rec00049.tif',50,changed)
    assert row['roi_id']=='line-7'
    assert row['x1_px']==8.5
    assert row['length_px']==pytest.approx(math.hypot(6.5,3))


def test_subpixel_precision_kept():
    changed=adjust_annotation(_line(),'start',(2.1,3.2))
    assert changed['start']==pytest.approx([2.1,3.2])
