"""ID098-08a: state cues and editing escape affordance (static fallback)."""
from pathlib import Path
from loupe.version import APP_VERSION


def test_version_and_offset_mode_semantics():
    assert APP_VERSION == '0.9.8d'
    text = (Path(__file__).resolve().parents[1]/'loupe/gui.py').read_text(encoding='utf-8')
    assert "setCheckable(True)" in text
    assert "Adjust Offsets: ON" in text
    assert 'def exit_offset_edit_mode(self):' in text
    assert "QKeySequence(QtCore.Qt.Key.Key_Escape)" in text
    assert "panel.offset_edit_badge.setVisible(enabled)" in text
    assert "panel.plot.setProperty('adjustingOffset', enabled)" in text


def test_stylesheet_has_consistent_edit_state():
    qss=(Path(__file__).resolve().parents[1]/'bl09w_ui/qt_theme.qss').read_text(encoding='utf-8')
    assert 'QPushButton#LOUPE_AdjustOffsets:checked' in qss
    assert 'QGraphicsView#LOUPE_OffsetPlot[adjustingOffset="true"]' in qss
    assert 'QLabel#LOUPE_OffsetEditBadge' in qss
