"""LOUPE v0.8.5 regression checks (Qt GUI integration is run on Windows)."""
from pathlib import Path
import pytest
from loupe.version import APP_VERSION

ROOT=Path(__file__).resolve().parents[1]
GUI=(ROOT/'loupe/gui.py').read_text(encoding='utf-8')
CSS=(ROOT/'bl09w_ui/qt_theme.qss').read_text(encoding='utf-8')


def test_version():
    assert APP_VERSION=='0.9.6'


def test_toolbar_two_level_structure():
    assert 'self.primary_toolbar_row' in GUI
    assert 'self.secondary_toolbar_row' in GUI
    assert 'self.link_toolbar_row' in GUI
    assert 'self._set_toolbar_compact(event.size().width() < 1450)' in GUI
    assert 'self.link_toolbar_row.addWidget(checkbox)' in GUI
    assert 'self.primary_toolbar_row.addWidget(button)' in GUI


def test_export_actions_not_lost():
    assert "self.export_menu_button.setPopupMode" in GUI
    assert "em.addAction('Profile Data (CSV)…')" in GUI
    assert "em.addAction('ROI Measurements (CSV)…')" in GUI
    for button in ('self.session_button','self.report_button','self.export_menu_button'):
        assert button in GUI
    for signal in ('self.export_csv','self.save_json','self.load_json',
                   'self.export_report_png','self.export_report_pdf'):
        assert signal in GUI


def test_auto_contrast_is_per_panel_and_persistent():
    assert "QtWidgets.QPushButton('Auto Contrast')" in GUI
    assert 'self.auto_button.clicked.connect(self.enable_auto_contrast)' in GUI
    assert 'self.auto.toggled.connect(self.auto_button.setChecked)' in GUI
    assert "QPushButton#LOUPE_AutoContrast:checked" in CSS
    assert 'self.auto_button.setChecked(False)' in GUI
    assert 'self.auto_button.setChecked(self.auto.isChecked())' in GUI
    assert 'self.image.setLevels((low, high))' in GUI


def test_fiji_both_actions_use_explicit_view_selector():
    assert "panel=self._choose_imagej_view('Open Current Image')" in GUI
    assert "panel=self._choose_imagej_view('Open Stack',sequence=True)" in GUI
    assert "return self.panels[int(combo.currentData())]" in GUI
    assert "suffix.lower() in ('.tif','.tiff','.img')" in GUI
    assert "if default in supported:" in GUI
    assert "panel.files[start_box.value()-1:end_box.value()]" in GUI
    assert "stack_preflight(info,available,heap)" in GUI


def test_optional_qt_integration(monkeypatch, tmp_path):
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6 import QtWidgets, QtCore
    from loupe.gui import MainWindow
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win=MainWindow()
    try:
        assert win.primary_toolbar_row.count()>10
        assert win.panels[0].auto_button.text()=='Auto Contrast'
        assert win.panels[0].wl_button.text()=='Window / Level…'
        assert win.panels[0].reset_button.text()=='Reset'
        assert win.export_menu_button.menu().actions()[0].text()=='Profile Data (CSV)…'
        # Change width/compact mode without destroying controls.
        win._set_toolbar_compact(False)
        assert win.link_view.parentWidget() is not None
        win._set_toolbar_compact(True)
        assert win.link_view.parentWidget() is not None
        # Selection prompts must not launch Fiji when canceled.
        monkeypatch.setattr(QtWidgets.QDialog,'exec',lambda *_:QtWidgets.QDialog.DialogCode.Rejected)
        assert win._choose_imagej_view('Open Current TIFF') is None
    finally:
        win.close()
