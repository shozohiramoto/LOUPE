"""v0.8.3 regressions: Explorer false-Fiji, save UI, isotropic scale bars."""
from pathlib import Path
from unittest.mock import Mock
import ctypes
from types import SimpleNamespace

import pytest

from loupe.imagej_bridge import is_fiji_window, detect_running_fiji
from loupe.orthogonal.scalebar import scale_bar_spec, scale_bar_label
from loupe.version import APP_VERSION

ROOT=Path(__file__).resolve().parents[1]


def test_release_number():
    assert APP_VERSION == '0.9.8d'


@pytest.mark.parametrize('title', ['Fiji - エクスプローラー', 'Fiji - File Explorer',
                                    'ImageJ - エクスプローラー', 'Fiji'])
def test_explorer_window_never_counts_as_fiji(title):
    assert not is_fiji_window(title, 'explorer.exe',
                              configured_executable='fiji-windows-x64.exe')


@pytest.mark.parametrize('title,name', [
    ('Fiji', 'javaw.exe'), ('(Just) ImageJ', 'java.exe'),
    ('ImageJ 1.54', 'imagej-win64.exe'), ('Fiji - ImageJ', 'fiji-windows-x64.exe'),
])
def test_true_fiji_windows_detectable(title,name):
    assert is_fiji_window(title, name, configured_executable='fiji-windows-x64.exe')


def test_unrelated_java_app_not_fiji():
    assert not is_fiji_window('Other Java software', 'javaw.exe')
    assert not is_fiji_window('LOUPE Fiji Bridge', 'javaw.exe')


def test_enumeration_window_pid_owner_excludes_explorer(monkeypatch):
    """Reproduce workstation: tasklist no Fiji process; Explorer title Fiji."""
    from loupe import imagej_bridge as bridge
    monkeypatch.setattr(bridge.sys, 'platform', 'win32')
    monkeypatch.setattr(bridge.subprocess, 'run', lambda *a, **k: Mock(
        returncode=0,
        stdout='"explorer.exe","4100","Console","1","120,000 K"\n'
               '"javaw.exe","4200","Console","1","250,000 K"\n'))
    fake_windows={11:('Fiji - エクスプローラー',4100),12:('Fiji',4200)}
    class FakePidFunction:
        argtypes=None
        restype=None
        def __call__(self, hwnd, p):
            ctypes.cast(p, ctypes.POINTER(ctypes.c_ulong))[0]=fake_windows[hwnd][1]
            return 1
    class FakeUser32:
        GetWindowThreadProcessId=FakePidFunction()
        def IsWindowVisible(self, hwnd):return True
        def GetWindowTextLengthW(self, hwnd):return len(fake_windows[hwnd][0])
        def GetWindowTextW(self, hwnd, buf, _):buf.value=fake_windows[hwnd][0]
        def EnumWindows(self, cb, _):
            for hwnd in fake_windows:
                cb(hwnd,0)
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=FakeUser32()), raising=False)
    monkeypatch.setattr(ctypes, 'WINFUNCTYPE', lambda *sig: (lambda fun:fun), raising=False)
    detected=detect_running_fiji('C:/Fiji/fiji-windows-x64.exe')
    assert ('javaw.exe','4200') in detected
    assert not any('explorer' in str(t).lower() for t in detected)
    fake_windows.pop(12)
    assert detect_running_fiji('C:/Fiji/fiji-windows-x64.exe')==[]


def test_scale_bar_true_physical_length_all_views():
    for pixel_size_um in (.1,.65,4.9):
        length_px,length_um=scale_bar_spec((0,2048),pixel_size_um)
        assert length_px*pixel_size_um==pytest.approx(length_um)
        assert 0 < length_px < 2048*.23 + 1e-8
    assert scale_bar_spec((0, 1024), None) is None
    assert scale_bar_spec((2,2), .65) is None


def test_scale_bar_labels():
    assert scale_bar_label(200)=='200 µm'
    assert scale_bar_label(2000)=='2 mm'
    assert scale_bar_label(.05)=='50 nm'


def test_orthogonal_microfixes_wired():
    src=(ROOT/'loupe/orthogonal/viewer.py').read_text(encoding='utf-8')
    gui=(ROOT/'loupe/gui.py').read_text(encoding='utf-8')
    assert "QFileDialog.getSaveFileName" in src
    assert "self._last_report_dir" in src
    assert 'QMessageBox.question(' in src
    assert 'os.replace(tmp, path)' in src
    assert "self._update_scale_bar(plane)" in src
    assert "get('show_scale_bar', False)" in src
    assert "'show_scale_bar':bool(other.show_scale_bar.isChecked())" in gui
    assert 'self.comment_edit.toPlainText()' in src
    assert "self._plots[name].grab()" in src


def test_optional_orthogonal_qt_dialog(monkeypatch, tmp_path):
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6 import QtWidgets
    from loupe.orthogonal.viewer import OrthogonalDialog
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    files=[]
    for i in range(2):
        p=tmp_path/f'rec{i:05d}.tif';p.write_bytes(b'x');files.append(p)
    monkeypatch.setattr(OrthogonalDialog,'_start_preview',lambda self: None)
    dlg=OrthogonalDialog(files,view_sources=[{
        'label':'VIEW 1', 'paths':files, 'pixel_size_um':.65,
        'show_scale_bar':True, 'slice':0, 'current':None}], pixel_size_um=.65)
    try:
        assert dlg._show_scale_bar
        assert set(dlg._scale_bars)=={'XY','YZ','ZX'}
    finally:dlg.close()
