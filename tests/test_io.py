from pathlib import Path
import numpy as np
import tifffile
from loupe.io import discover, load_frame, display_limits

def test_discover(tmp_path):
    for i in range(3):
        tifffile.imwrite(tmp_path / f'{i:03}.tif', np.ones((16, 16), dtype=np.uint16)*i)
    paths, index = discover(tmp_path / '001.tif')
    assert len(paths) == 3 and index == 1

def test_float_image(tmp_path):
    img = np.arange(100, dtype=np.float32).reshape(10, 10)
    p = tmp_path / 'test.tiff'
    tifffile.imwrite(p, img)
    assert np.array_equal(load_frame(p), img)
    lo, hi = display_limits(img)
    assert lo < hi

def test_constant_limits():
    assert display_limits(np.zeros((4,4)))[1] > display_limits(np.zeros((4,4)))[0]
