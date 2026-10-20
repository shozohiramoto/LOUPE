"""ID053 actions are retained; ID054 refines their placement to VIEW-style toolbar."""
import ast
import os
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
HR=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf-8')
VIEW=(ROOT/'loupe/orthogonal/viewer.py').read_text(encoding='utf-8')
QSS=(ROOT/'bl09w_ui/qt_theme.qss').read_text(encoding='utf-8')


def test_source_contract():
    ast.parse(HR);ast.parse(VIEW)
    assert "self.report_menu.setText('Report ▾')" in HR
    assert "report_menu.addAction('PNG…')" in HR
    assert "report_menu.addAction('PDF…')" in HR
    assert "self.save_button=QtWidgets.QPushButton('Export TIFF…')" in HR
    assert "self.fiji_button.clicked.connect(self.open_fiji)" in HR
    assert "self.report_menu.setEnabled(True)" in HR
    assert "self.report_menu.setEnabled(False)" in HR
    assert "self.hr_widget.move_output_controls_to(navigation)" in VIEW
    assert "self._output_row.removeWidget(action)" in HR
    assert "target_layout.addWidget(action)" in HR
    assert "self.output_group=" not in HR
    assert "splitter.addWidget(scroll)" in HR


def test_styles_match_normal_view_and_are_keyboard_accessible():
    for selector in ('QToolButton#LOUPE_OrthogonalReport',
                     'QPushButton#LOUPE_OrthogonalOutputButton'):
        assert selector in QSS
        for suffix in (':hover',':focus',':disabled'):
            assert selector+suffix in QSS


def test_qt_native_toolbar_actions_if_available():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6');pytest.importorskip('pyqtgraph')
    from PySide6 import QtWidgets
    from loupe.orthogonal.high_resolution_widget import HighResolutionWidget
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget=HighResolutionWidget()
    try:
        widget.resize(1050,700);widget.show();app.processEvents()
        buttons=(widget.report_menu,widget.save_button,widget.fiji_button)
        assert [a.text() for a in widget.report_menu.menu().actions()]==['PNG…','PDF…']
        assert not any(b.isEnabled() for b in buttons)
        assert widget.save_button.toolTip().find('JSON')>=0
        assert widget._output_row.indexOf(widget.report_menu)>-1
        assert widget._output_row.indexOf(widget.save_button)>-1
        assert widget._output_row.indexOf(widget.fiji_button)>-1
    finally:
        widget.dispose();widget.close()
