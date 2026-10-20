"""Optional Qt smoke: run on Windows/PySide6, not the headless build host."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest


def test_orthogonal_window_basic_when_qt_available(tmp_path):
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6 import QtWidgets,QtCore
    import tifffile
    import numpy as np
    from loupe.orthogonal.viewer import OrthogonalDialog
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    paths=[]
    for i in range(3):
        p=tmp_path / f'rec{i:05d}.tif'
        tifffile.imwrite(p,np.ones((12,14),dtype='float32')*i)
        paths.append(p)
    dialog=OrthogonalDialog(paths,initial_slice=1,pixel_size_um=.65)
    import time
    end=time.monotonic()+8
    while dialog._volume is None and time.monotonic()<end:
        app.processEvents()
        time.sleep(.02)
    assert dialog._volume is not None
    assert dialog._volume.shape==(3,12,14)
    dialog._sliders['X'].setValue(5)
    dialog._sliders['Y'].setValue(6)
    assert dialog._positions['X'].text()=='6 px'
    dialog.close()
