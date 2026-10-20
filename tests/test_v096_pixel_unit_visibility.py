"""v0.9.6: regression for blank µm selector in 4 VIEW at Windows 125% DPI."""
import ast
import os
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
GUI = (ROOT/'loupe/gui.py').read_text(encoding='utf-8')
QSS = (ROOT/'bl09w_ui/qt_theme.qss').read_text(encoding='utf-8')


def test_unit_selector_no_longer_zero_width_or_far_from_value():
    ast.parse(GUI)
    assert "setObjectName('LOUPE_PixelUnit')" in GUI
    assert 'self.cal_unit.setFixedWidth(48 if ultra else 54)' not in GUI
    assert 'self.cal_unit.setFixedWidth(max(78, unit_text_px+48))' in GUI
    assert 'self.calibration_value_layout.addWidget(self.cal_size)' in GUI
    assert 'self.calibration_value_layout.addWidget(self.cal_unit)' in GUI
    assert 'self.calibration_value_layout.addStretch(1)' in GUI


def test_object_specific_combo_css_has_content_and_dropdown_space():
    assert 'QComboBox#LOUPE_PixelUnit {' in QSS
    assert 'padding-right: 19px;' in QSS
    assert 'QComboBox#LOUPE_PixelUnit::drop-down {' in QSS
    assert 'width: 17px;' in QSS
    assert 'subcontrol-origin: border;' in QSS


def test_qt_four_view_unit_text_uses_visible_space_if_installed():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6 import QtWidgets
    from loupe.gui import MainWindow
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow()
    try:
        w.view_count.setCurrentIndex(3)
        w.resize(1916, 1050)
        w.show()
        app.processEvents()
        for p in w.visible_panels():
            p.set_compact_mode(True, ultra=True)
            p.set_calibration({'enabled': True, 'pixel_size': .65, 'unit': 'µm',
                               'source':'manual'})
            p.show()
            app.processEvents()
            assert p.cal_unit.currentText() == 'µm'
            assert p.cal_unit.width() >= 78
            unit_text=max(p.cal_unit.fontMetrics().horizontalAdvance(p.cal_unit.itemText(i))
                          for i in range(p.cal_unit.count()))
            assert p.cal_unit.width() >= unit_text + 48
            assert p.cal_unit.x() >= p.cal_size.x()
    finally:
        w.close()
