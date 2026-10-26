"""v0.9.0 source contracts and optional Windows PySide6 GUI smoke."""
import ast
import os
from pathlib import Path
import pytest
import numpy as np
import tifffile

ROOT=Path(__file__).resolve().parents[1]


def test_gui_integration_contract_without_qt():
    src=(ROOT/'loupe/orthogonal/viewer.py').read_text(encoding='utf-8')
    child=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf-8')
    ast.parse(src);ast.parse(child)
    assert 'HighResolutionWidget' in src
    assert "self.tabs.addTab(self.hr_widget,'Native Section')" in src
    assert 'self.hr_widget.select_plane_from_preview' in src
    assert 'self.hr_widget.dispose()' in src
    assert 'self.preview_report_button.setVisible(is_preview)' in src
    assert 'QtCore.QTimer.singleShot(0,self.close)' in src
    for marker in ('scan_series(paths, pixel_size_um=xy_um, cancelled=cancel.is_set',
                   'result=extract_plane(series,plane=plane',
                   'self._signals.completed.emit',
                   'self._cancel.set()',
                   'source_paths=[str(path)]',
                   'QFileDialog.getSaveFileName',
                   'TemporaryDirectory('):
        assert marker in child


def test_v090_gui_real_when_qt_available(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6'); pytest.importorskip('pyqtgraph')
    from PySide6 import QtWidgets,QtCore
    from loupe.orthogonal.viewer import OrthogonalDialog
    from loupe.version import APP_VERSION
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    paths=[]
    for i in range(4):
        p=tmp_path/f'rec{i:05}.tif'
        tifffile.imwrite(p,(np.arange(9*12,dtype='float32').reshape(9,12)+i*1000))
        paths.append(p)
    dialog=OrthogonalDialog(paths,initial_slice=0)
    import time
    end=time.monotonic()+12
    while dialog._volume is None and time.monotonic()<end:
        app.processEvents(); time.sleep(.025)
    assert dialog._volume is not None
    dialog._sliders['X'].setValue(5)
    dialog._sliders['Y'].setValue(6)
    dialog._select_high_res('ZX')
    child=dialog.hr_widget
    assert child.plane.currentIndex()==1
    assert child.index.value()==7
    child.start()
    end=time.monotonic()+12
    while child.busy and time.monotonic()<end:
        app.processEvents(); time.sleep(.025)
    assert not child.busy
    assert child._result is not None
    assert np.array_equal(child._image_data[0],tifffile.imread(paths[0])[6,:])
    assert child._result.metadata['fixed_index_px']==6
    assert APP_VERSION=='0.9.8d'
    dialog.close(); app.processEvents()
