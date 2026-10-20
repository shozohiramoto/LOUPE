"""v0.8.2 contrast toolbar simplification safety checks."""
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / 'loupe' / 'gui.py').read_text(encoding='utf-8')


def test_toolbar_has_single_contrast_button():
    panel = SOURCE.split('class ContrastDialog')[0]
    assert panel.count("QtWidgets.QPushButton('Window / Level…')") == 1
    assert "QtWidgets.QPushButton('Levels…')" not in panel
    # v0.8.5 intentionally exposes the two useful actions next to Window/Level.
    assert "QtWidgets.QPushButton('Auto Contrast')" in panel
    assert "QtWidgets.QPushButton('Reset')" in panel
    assert panel.count("self._place_grid_widgets(self.level_grid, [(self.auto_button,0,0,1,1),") == 3


def test_auto_and_reset_still_available_in_dialog():
    dialog = SOURCE.split('class ContrastDialog')[1]
    assert "QtWidgets.QPushButton('Auto')" in dialog
    assert "QtWidgets.QPushButton('Reset (Full)')" in dialog
    assert 'self.histogram=pg.PlotWidget()' in dialog
    assert 'self.panel.auto.setChecked(True)' in dialog


def test_manual_mode_is_still_persisted():
    assert "'auto_contrast':self.auto.isChecked()" in SOURCE
    assert 'self.auto.setChecked(False)' in SOURCE
