"""Non-Qt tests for v0.9.1 changes plus lightweight GUI source contracts."""
from pathlib import Path
import struct
import numpy as np
import tifffile
import pytest
from loupe.version import APP_VERSION, APP_STATUS
from loupe.img_to_fiji import converted_img_file, clean_old_temporary_imports

ROOT=Path(__file__).resolve().parents[1]
GUI=(ROOT/'loupe/gui.py').read_text(encoding='utf-8')
HR=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf-8')
VIEW=(ROOT/'loupe/orthogonal/viewer.py').read_text(encoding='utf-8')
REPORT=(ROOT/'loupe/report.py').read_text(encoding='utf-8')

def test_v091_identity_and_branding():
    assert APP_VERSION=='0.9.6'
    assert APP_STATUS=='Development'
    assert 'Photon Science Innovation Center (PhoSIC)' in GUI
    assert 'UI Standard v{UI_STANDARD_VERSION}' in GUI
    assert 'Build JST:' in GUI
    assert 'Acquisition hardware is not controlled' not in GUI
    assert 'Copy Active Profile' not in GUI
    assert "QPushButton('Copy Graph')" in GUI


def test_new_icon_and_calibration_controls():
    from PIL import Image
    im=Image.open(ROOT/'assets/loupe.png')
    assert im.size==(256,256)
    assert (ROOT/'assets/loupe.ico').stat().st_size>1000
    source=(ROOT/'loupe/calibration_spin.py').read_text()
    assert 'QtWidgets.QLineEdit' in source and 'editingFinished.connect(self._commit)' in source
    assert 'wheelEvent' in source and 'event.ignore()' in source
    assert 'CalibrationSpinBox()' in GUI and 'CalibrationSpinBox()' in HR


def test_orthogonal_controls_and_reports():
    assert 'self.setWindowTitle(\'LOUPE — Orthogonal View (Preview)\' if index==0' in VIEW
    assert 'screen.availableGeometry()' in VIEW
    assert "'Ellipse / Circle (px)'" in HR
    assert 'sample_thick_line(arr,a,b,width=width)' in HR
    assert "self.png_action.triggered.connect(lambda:self.export_report('PNG'))" in HR
    assert "self.pdf_action.triggered.connect(lambda:self.export_report('PDF'))" in HR
    assert 'self._export_layered_preview_pdf(tmp)' in VIEW
    # PDF draws individual raster images and independent text objects, not full report canvas.
    fn=REPORT.split('def export_pdf_report(',1)[1]
    assert 'render_report_image(' not in fn
    assert '_draw_image(painter,item,image_box)' in fn
    assert 'painter.drawText(' in fn


def test_roi_fiji_and_toolbar_contracts():
    assert 'self.record_annotation_change(target,key,before,after' in GUI
    assert 'selection=QtWidgets.QListWidget()' in GUI
    assert 'self.export_menu_button.setMenu(em)' in GUI
    assert 'self.link_toolbar_row.addWidget(checkbox)' in GUI
    assert 'self.roi_edit = QtWidgets.QPushButton' not in GUI
    assert 'converted_img_file(source,um)' in GUI
    assert 'converted_img_file(original,spacing)' in GUI
    assert 'def fiji_relay_setup(self)' in GUI


def _create_img(path, array):
    h,w=array.shape
    header=bytearray(64)
    header[:4]=b'IM\x00\x00'
    struct.pack_into('<HH',header,4,w,h)
    struct.pack_into('<I',header,12,2)
    path.write_bytes(header+array.astype('<u2').tobytes())


def test_img_conversion_lossless_and_calibrated(tmp_path):
    src=tmp_path/'q00001.img'
    a=np.array([[0,100,65535],[7,11,999]],dtype='uint16')
    _create_img(src,a)
    dst=converted_img_file(src,pixel_size_um=.65,cache_dir=tmp_path/'cache')
    assert np.array_equal(tifffile.imread(dst),a)
    assert src.read_bytes()[0:4]==b'IM\x00\x00'
    with tifffile.TiffFile(dst) as t:
        tags=t.pages[0].tags
        assert int(tags['ResolutionUnit'].value)==3
        xnum,xden=tags['XResolution'].value
        assert (10000*xden/xnum)==pytest.approx(.65)
        assert 'unit=um' in t.pages[0].description
    assert clean_old_temporary_imports(tmp_path/'cache',max_age_days=10)==0


def test_img_conversion_no_invented_calibration(tmp_path):
    src=tmp_path/'q00002.img'
    _create_img(src,np.arange(20,dtype=np.uint16).reshape(4,5))
    out=converted_img_file(src,cache_dir=tmp_path/'cache')
    with tifffile.TiffFile(out) as t:
        assert 'unit=um' not in t.pages[0].description
        assert np.array_equal(t.asarray(),np.arange(20,dtype=np.uint16).reshape(4,5))
