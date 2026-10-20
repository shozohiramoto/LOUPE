"""BL09W UI Standard v1.0 regression checks (no Qt installation required)."""
from pathlib import Path
import json
import re
import sys
import types

ROOT = Path(__file__).resolve().parents[1]


def test_theme_is_installed_inside_standalone_loupe_package():
    from loupe.ui_theme import ASSET_ROOT
    assert ASSET_ROOT.resolve() == (ROOT / 'bl09w_ui').resolve()
    assert (ASSET_ROOT / 'theme.json').is_file()
    assert (ASSET_ROOT / 'qt_theme.qss').is_file()


def test_schema_and_consistent_palette():
    from loupe.ui_theme import theme
    t = theme()
    assert t['version'] == '1.0.0'
    assert t['schema'] == 'bl09w.ui.theme'
    assert t['palette']['canvas'] == '#0B111A'
    assert t['palette']['accent'] == '#518DBB'
    assert t['palette']['stop'] == '#D64444'
    assert t['interaction']['stop_is_reserved_for_hardware'] is True
    assert t['typography']['base_pt'] >= 9


def test_qss_excludes_unsafe_override_of_stop_semantics():
    text = (ROOT / 'bl09w_ui' / 'qt_theme.qss').read_text(encoding='utf8')
    assert '#BL09W_HardwareStop' in text
    assert 'QPushButton#BL09W_HardwareStop' in text
    assert 'QPushButton#BL09W_HardwareStart' in text
    assert re.search(r'QPushButton\s*\{', text)
    assert 'color: #F2F5FA' in text
    assert text.count('{') == text.count('}')


def test_entrypoint_applies_theme_before_window_construction():
    text = (ROOT / 'main.py').read_text(encoding='utf8')
    assert text.index('apply_qt_theme(app)') < text.index('manager.new_window()')
    assert 'window.showMaximized()' in text


def test_ui_theme_adapter_sets_qt_and_pyqtgraph(monkeypatch):
    import loupe.ui_theme as adapter
    fake_pyside = types.ModuleType('PySide6')
    fake_qtgui = types.ModuleType('PySide6.QtGui')
    fake_qtgui.QFont = lambda family, size: (family, size)
    fake_pyside.QtGui = fake_qtgui
    got = {}
    fake_pyqtgraph = types.ModuleType('pyqtgraph')
    fake_pyqtgraph.setConfigOptions = lambda **kw: got.update(kw)
    monkeypatch.setitem(sys.modules, 'PySide6', fake_pyside)
    monkeypatch.setitem(sys.modules, 'PySide6.QtGui', fake_qtgui)
    monkeypatch.setitem(sys.modules, 'pyqtgraph', fake_pyqtgraph)

    class FakeApp:
        def setFont(self, font): self.font = font
        def setStyleSheet(self, css): self.stylesheet = css

    app = FakeApp()
    version = adapter.apply_qt_theme(app)
    assert version == '1.0.0'
    assert app.font == ('Segoe UI', 10)
    assert 'QSlider::handle:horizontal' in app.stylesheet
    assert got['background'] == '#0B111A'
    assert got['foreground'] == '#C5D0DE'


def test_help_about_displays_integrated_theme_version():
    text = (ROOT / 'loupe' / 'gui.py').read_text(encoding='utf8')
    assert 'About LOUPE' in text
    assert 'UI Standard v{UI_STANDARD_VERSION}' in text
    assert 'VIEW 1' in text


def test_no_install_time_iq_hardware_dependencies():
    assert not (ROOT / 'IQ_Radiography_v5_6.py').exists()
    requirements = (ROOT / 'requirements.txt').read_text(encoding='utf8').lower()
    assert 'pyside6' in requirements
    assert 'pyqtgraph' in requirements
    assert 'opencv' not in requirements
    assert 'pyserial' not in requirements


def test_json_cannot_contain_external_absolute_paths():
    theme_text = (ROOT / 'bl09w_ui' / 'theme.json').read_text(encoding='utf8')
    data = json.loads(theme_text)
    assert data['name']
    assert 'C:\\' not in theme_text
    assert '/mnt/data' not in theme_text
