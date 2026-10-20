import numpy as np
from loupe.profiles import sample_line, sample_thick_line


def test_width_one_equivalence():
    arr=np.arange(100,dtype=float).reshape(10,10)
    for a,b in [((1,2),(8,7)), ((1,2),(1,2))]:
        d0,v0=sample_line(arr,a,b)
        d1,v1=sample_thick_line(arr,a,b,1)
        assert np.array_equal(d0,d1) and np.array_equal(v0,v1)


def test_horizontal_mean_and_sum():
    arr=np.tile(np.arange(7,dtype=float)[:,None],(1,7))
    _,mean=sample_thick_line(arr,(1,3),(5,3),3,'mean')
    _,total=sample_thick_line(arr,(1,3),(5,3),3,'sum')
    assert np.allclose(mean,3)
    assert np.allclose(total,9)


def test_edge_ignores_outside():
    arr=np.ones((3,5))
    _,mean=sample_thick_line(arr,(0,0),(4,0),5,'mean')
    _,total=sample_thick_line(arr,(0,0),(4,0),5,'sum')
    assert np.allclose(mean,1)
    assert np.allclose(total,3)


def test_invalid_args():
    import pytest
    for width in [0,102]:
        with pytest.raises(ValueError): sample_thick_line(np.ones((3,3)),(0,0),(2,2),width)
