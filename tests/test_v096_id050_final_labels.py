"""ID050 staff-preview: full-width menu uses ImageJ/Fiji, compact buttons remain ImageJ."""
from pathlib import Path
import ast
import os
import pytest

ROOT=Path(__file__).resolve().parents[1]
GUI=(ROOT/'loupe/gui.py').read_text(encoding='utf-8')
NATIVE=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf-8')


def test_menu_final_labels_and_existing_handlers():
    ast.parse(GUI)
    expected={
        "imagej_menu=self.menuBar().addMenu('ImageJ/Fiji')":None,
        "imagej_menu.addAction('Configure ImageJ/Fiji…').triggered.connect(self.configure_imagej)":None,
        "imagej_menu.addAction('ImageJ/Fiji Connection Check…').triggered.connect(self.fiji_relay_setup)":None,
        "imagej_menu.addAction('Open Current Image in ImageJ/Fiji…').triggered.connect(self.open_imagej_current)":None,
        "imagej_stack_action=imagej_menu.addAction('Open Stack in ImageJ/Fiji…')":None,
        "imagej_stack_action.triggered.connect(self.open_imagej_stack)":None,
        "imagej_stack_action.setStatusTip('TIFF/IMG stack with slice-range and RAM preflight')":None,
    }
    for fragment in expected:
        assert fragment in GUI
    for obsolete in ('ImageJ/FIJI', 'Open Current Image in Fiji…',
                     'Open Stack (TIFF / IMG, normal RAM)…',
                     "addAction('Fiji connection check…')"):
        assert obsolete not in GUI
    assert "ImageJ/Fiji → Configure ImageJ/Fiji…" in GUI
    assert 'ImageJ/Fiji → ImageJ/Fiji Connection Check…' in GUI
    assert "self.fiji_button.setText('Open in ImageJ')" in NATIVE


def test_gui_labels_optional_qt():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6.QtWidgets import QApplication
    from loupe.gui import MainWindow
    app=QApplication.instance() or QApplication([])
    window=MainWindow()
    try:
        actions=[a for a in window.menuBar().actions() if a.text()=='ImageJ/Fiji']
        assert len(actions)==1
        names=[a.text() for a in actions[0].menu().actions()]
        assert names==[
            'Configure ImageJ/Fiji…',
            'ImageJ/Fiji Connection Check…',
            'Open Current Image in ImageJ/Fiji…',
            'Open Stack in ImageJ/Fiji…',
        ]
    finally:
        window.close()
