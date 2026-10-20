"""v0.9.4 regression tests, including optional Qt widget behavior on Windows."""
import ast
import os
from pathlib import Path
import pytest
import tifffile
import numpy as np

from loupe.version import APP_VERSION
from loupe.fiji_bridge import autostart_status
from loupe.tiff_metadata import read_reconstruction_metadata

ROOT=Path(__file__).resolve().parents[1]
GUI=(ROOT/'loupe/gui.py').read_text(encoding='utf8')
HR=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf8')
CAL=(ROOT/'loupe/calibration_spin.py').read_text(encoding='utf8')


def test_release_and_compilable_gui_modules():
    assert APP_VERSION=='0.9.6'
    for code in (GUI,HR,CAL):
        ast.parse(code)
    assert 'self.secondary_toolbar_row.addWidget(self.profile_source)' not in GUI
    assert "self.fit_button = QtWidgets.QPushButton('Fit')" not in GUI
    assert "self.image_fit_button = QtWidgets.QPushButton('FIT'" in GUI


def test_calibration_text_entry_and_responsive_labels():
    assert 'class CalibrationSpinBox(QtWidgets.QLineEdit)' in CAL
    assert 'self.editingFinished.connect(self._commit)' in CAL
    assert 'def wheelEvent(self, event):' in CAL
    assert "self.cal_enabled.setText('Px size')" not in GUI
    assert "self.show_scale_bar.setText('Bar')" not in GUI
    assert "(self.show_scale_bar,1,0,1,3)" in GUI
    assert 'self.cal_size.setValue(cal[\'pixel_size\'])' in GUI


def test_high_resolution_tools_not_confused_with_profiles():
    assert "'Rectangle (px)'" in HR
    assert "'Line (px)'" in HR
    assert "'Count 1, 2, 3…'" in HR
    assert 'HighResROIController(self)' in HR
    assert "' · Rectangle mean not measured'" in HR
    assert "self.show_profile_button.setVisible(False)" in HR
    assert "dlg.resize(920,500)" in HR
    assert 'side.addWidget(self.profile_plot)' not in HR
    assert 'self._profile_dialog.hide()' in HR


def test_fiji_receiver_setup_is_explicit_and_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'AppData'))
    exe=tmp_path/'Fiji.app'/'ImageJ-win64.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'mock')
    assert autostart_status(exe)=='STARTUP_UNSUPPORTED'
    startup=exe.parent/'macros'/'StartupMacros.fiji.ijm'
    startup.parent.mkdir(parents=True,exist_ok=True)
    startup.write_text('macro \"AutoRun\" { runMacro(\"AutoRun/a.ijm\"); } // AutoRun/',encoding='utf8')
    receiver=tmp_path/'AppData'/'LOUPE'/'bridge'/'LOUPE_receiver.py'
    receiver.parent.mkdir(parents=True)
    receiver.write_text('# receiver',encoding='utf8')
    hook=exe.parent/'macros'/'AutoRun'/'LOUPE_Bridge_AutoRun.ijm'
    hook.parent.mkdir(parents=True)
    hook.write_text('// wrong path',encoding='utf8')
    assert autostart_status(exe)=='OUTDATED'
    hook.write_text('call("ij.plugin.Macro_Runner.runPython", "'+str(receiver.resolve()).replace('\\','/')+'", "");',encoding='utf8')
    assert autostart_status(exe)=='INSTALLED'
    assert '_fiji_prelaunch_setup(executable)' in GUI
    assert '_check_fiji_receiver_after_launch' in GUI


def test_realistic_legacy_tiff_header_calibration(tmp_path):
    f=tmp_path/'rec00000.tif'
    a=np.arange(24*48,dtype=np.float32).reshape(24,48)
    tifffile.imwrite(f,a,description='0.65\t24\t0\t0\t0\t0')
    meta=read_reconstruction_metadata(f)
    assert meta is not None and meta['pixel_size_um']==0.65


def test_qt_gui_calibration_and_roi_modes_if_available(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6 import QtWidgets
    from loupe.gui import MainWindow
    from loupe.orthogonal.high_resolution_widget import HighResolutionWidget
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow()
    try:
        panel=w.panels[0]
        panel.set_calibration({'enabled':True,'pixel_size':.65,'unit':'µm',
                               'source':'tiff_header'})
        assert panel.cal_size.text()=='0.65'
        panel.set_compact_mode(True,ultra=True)
        assert panel.cal_unit.currentText()=='µm'
        assert panel.show_scale_bar.text()=='Scale bar'
        assert panel.image_fit_button.text()=='FIT'
        assert w.profile_source not in [w.secondary_toolbar_row.itemAt(i).widget()
                              for i in range(w.secondary_toolbar_row.count())]
        child=HighResolutionWidget()
        try:
            assert child.profile_mode.count()==5
            assert child.profile_mode.itemText(2)=='Rectangle (px)'
            child.profile_mode.setCurrentIndex(2)
            assert not child.profile_plot.isVisible()
        finally:
            child.dispose()
    finally:
        w.close()
