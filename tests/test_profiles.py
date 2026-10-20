import numpy as np
from loupe.profiles import sample_line

def test_horizontal():
    a=np.arange(25,dtype=np.uint16).reshape((5,5))
    x,y=sample_line(a,(0,2),(4,2))
    assert np.allclose(x,[0,1,2,3,4])
    assert np.allclose(y,[10,11,12,13,14])

def test_subpixel():
    a=np.array([[0,10],[20,30]],dtype=np.float32)
    x,y=sample_line(a,(0.5,0.5),(0.5,0.5))
    assert np.allclose(y,[15,15])

def test_outside():
    _,y=sample_line(np.ones((2,2)),(-2,0),(0,0))
    assert np.isnan(y[0]) and np.isfinite(y[-1])
