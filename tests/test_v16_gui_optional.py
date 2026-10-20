"""Run on the target Windows workstation with PySide6 and pyqtgraph installed."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
import numpy as np
from pathlib import Path
pytest.importorskip('PySide6')
pytest.importorskip('pyqtgraph')
from PySide6 import QtWidgets
from loupe.gui import MainWindow
from loupe.report import export_png_report,export_pdf_report


@pytest.fixture(scope='module')
def app():
    application=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return application


def test_view_labels_and_actions(app):
    window=MainWindow()
    try:
        assert [panel.display_name for panel in window.panels]==['VIEW 1','VIEW 2','VIEW 3','VIEW 4']
        assert [panel.objectName() for panel in window.panels]==['LEFT','RIGHT','THIRD','FOURTH']
        assert window.report_pdf_button.text()=='Report PDF'
        actions=[action.text() for action in window.menuBar().actions()]
        assert 'ImageJ/Fiji' in actions
    finally:
        window.close()


def test_pdf_and_png_report_valid_files(app,tmp_path):
    arr=np.arange(64*64,dtype=np.float32).reshape(64,64)
    make=lambda n:{'side':f'VIEW {n}', 'path':str(tmp_path/f'rec{n:05}.tif'),
        'slice':n,'image':arr,'levels':(0.0,4095.0),
        'view_range':[[0.0,64.0],[0.0,64.0]],'annotations':[],
        'calibration':{'enabled':True,'pixel_size':0.5,'unit':'µm'},
        'show_scale_bar':True, 'profile':None,'profile_line':None}
    panels=[make(i) for i in range(1,5)]
    png=tmp_path/'report.png';pdf=tmp_path/'report.pdf'
    export_png_report(png,panels,comment='4-view test',title='LOUPE v1.6')
    export_pdf_report(pdf,panels,comment='4-view test',title='LOUPE v1.6')
    assert png.read_bytes().startswith(b'\x89PNG')
    assert pdf.read_bytes().startswith(b'%PDF')
    assert pdf.stat().st_size>1000
