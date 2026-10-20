"""ID054: single VIEW-like output location on Orthogonal tab switch."""
from pathlib import Path
import ast
import os
import time
import pytest
import numpy as np
import tifffile

ROOT=Path(__file__).resolve().parents[1]
VIEW=(ROOT/'loupe/orthogonal/viewer.py').read_text(encoding='utf-8')
HR=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf-8')


def test_output_actions_are_tab_specific_and_export_implementations_unchanged():
    ast.parse(VIEW);ast.parse(HR)
    assert "self.preview_report_button.setText('Report ▾')" in VIEW
    assert "self.preview_png_action=preview_report_menu.addAction('PNG…')" in VIEW
    assert "self.preview_pdf_action=preview_report_menu.addAction('PDF…')" in VIEW
    assert "self.preview_report_button.setVisible(is_preview)" in VIEW
    assert "action.setVisible(not is_preview)" in VIEW
    assert "self.hr_widget.move_output_controls_to(navigation)" in VIEW
    assert "self.hr_widget.report_menu" in VIEW
    assert "self.hr_widget.save_button" in VIEW
    assert "self.hr_widget.fiji_button" in VIEW
    assert "self.preview_report_button.setEnabled(False)" in VIEW
    assert "self.preview_report_button.setEnabled(True)" in VIEW
    assert "self.save_button.clicked.connect(self.export)" in HR
    assert "self.fiji_button.clicked.connect(self.open_fiji)" in HR
    assert "self.png_action.triggered.connect(lambda:self.export_report('PNG'))" in HR
    assert "self.pdf_action.triggered.connect(lambda:self.export_report('PDF'))" in HR
    assert "sidecar=path.with_suffix('.json')" in HR
    assert "self.output_group=" not in HR
    assert "self.png_button" not in VIEW


def test_optional_qt_tab_switch_has_one_report_and_top_right_native_actions(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6');pytest.importorskip('pyqtgraph')
    from PySide6 import QtWidgets,QtCore
    from loupe.orthogonal.viewer import OrthogonalDialog
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    paths=[]
    for i in range(5):
        path=tmp_path/f'rec{i:05}.tif'
        tifffile.imwrite(path,np.arange(60,dtype='uint16').reshape(6,10)+i*100)
        paths.append(path)
    dialog=OrthogonalDialog(paths)
    try:
        dialog.show();app.processEvents()
        deadline=time.monotonic()+15
        while dialog._volume is None and time.monotonic()<deadline:
            app.processEvents();time.sleep(.025)
        assert dialog._volume is not None
        assert dialog.preview_report_button.isVisible()
        assert not dialog.hr_widget.report_menu.isVisible()
        dialog.tabs.setCurrentWidget(dialog.hr_widget)
        app.processEvents()
        assert not dialog.preview_report_button.isVisible()
        for button in (dialog.hr_widget.report_menu,dialog.hr_widget.save_button,
                       dialog.hr_widget.fiji_button):
            assert button.isVisible()
            assert button.parentWidget() is dialog
            assert not button.isEnabled()  # Need native image before exporting.
        assert dialog.hr_widget._output_row.indexOf(dialog.hr_widget.save_button)==-1
        assert dialog.hr_widget.save_button.toolTip().find('JSON')>=0
        dialog.tabs.setCurrentIndex(0);app.processEvents()
        assert dialog.preview_report_button.isVisible()
    finally:
        dialog.close();app.processEvents()
