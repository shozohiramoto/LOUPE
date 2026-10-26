"""v0.6.0 release-level guards, including pure-process Fiji checks.

Qt-dependent smoke tests run on Windows using tests/gui_smoke_v060.py.
"""
from pathlib import Path
from unittest.mock import Mock
import importlib
import pytest
from loupe.version import APP_VERSION
from loupe.app_icon import icon_path, windows_icon_path
from loupe import imagej_bridge

ROOT=Path(__file__).resolve().parents[1]


def test_version_identity():
    assert APP_VERSION == '0.9.8d'
    assert '0.8.2' in (ROOT/'CHANGELOG.md').read_text(encoding='utf-8')


def test_logo_assets():
    png=icon_path(); ico=windows_icon_path()
    assert png.is_file() and png.stat().st_size>500
    assert ico.is_file() and ico.read_bytes()[:4]==b'\x00\x00\x01\x00'
    assert (ROOT/'main.py').read_text().find('setWindowIcon')>0
    assert 'setIconPixmap' in (ROOT/'loupe/gui.py').read_text()


def test_no_shape_algorithm_replaced():
    code=(ROOT/'loupe/gui.py').read_text(encoding='utf-8')
    assert 'QSplitter(QtCore.Qt.Orientation.Vertical)' in code
    assert "self.profile_source.addItem('Line profile','line')" in code
    assert "self.profile_source.addItem('Rectangle mean X','rect_x')" not in code
    assert 'class ContrastDialog' in code
    assert "self.histogram=pg.PlotWidget()" in code
    assert 'Window / Level' in code
    assert "self.setWindowIcon(QtGui.QIcon(str(icon_path())))" in code


def test_report_header_and_curve_color():
    code=(ROOT/'loupe/report.py').read_text(encoding='utf-8')
    assert "painter.drawText(QtCore.QPointF(margin,53),'LOUPE Report')" in code
    assert 'f\'Version {APP_VERSION}\'' in code
    assert "QtGui.QColor(PROFILE_HEX)" in code
    from loupe.report import PROFILE_HEX as report_profile
    from loupe.ui_theme import theme
    assert report_profile == theme()['palette']['profile']
    assert 'render_report_image(panels' in code


def test_detection_existing_windows_fiji(monkeypatch):
    monkeypatch.setattr(imagej_bridge.sys,'platform','win32')
    monkeypatch.setattr(imagej_bridge.subprocess,'run',lambda *a,**kw:Mock(
        returncode=0,stdout='"ImageJ-win64.exe","4567","Console","1","100,000 K"\n'))
    detected=imagej_bridge.detect_running_fiji('C:/Fiji/ImageJ-win64.exe')
    assert ('ImageJ-win64.exe','4567') in detected


def test_detection_fail_closed(monkeypatch):
    monkeypatch.setattr(imagej_bridge.sys,'platform','win32')
    monkeypatch.setattr(imagej_bridge.subprocess,'run',lambda *a,**kw:Mock(returncode=2,stdout=''))
    with pytest.raises(RuntimeError,match='refusing new launch'):
        imagej_bridge.detect_running_fiji('C:/Fiji/ImageJ-win64.exe')


def test_nonwindows_detection_fail_closed(monkeypatch):
    monkeypatch.setattr(imagej_bridge.sys,'platform','linux')
    with pytest.raises(RuntimeError, match='Windows only'):
        imagej_bridge.detect_running_fiji('/opt/fiji/ImageJ')
