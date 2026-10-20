"""0.8.2 regression: don't use a constructor local inside _build_ui."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'loupe/orthogonal/viewer.py').read_text(encoding='utf-8')


def test_orthogonal_selector_initialization_uses_instance_state():
    module = ast.parse(SOURCE)
    klass = next(x for x in module.body if isinstance(x, ast.ClassDef) and x.name == 'OrthogonalDialog')
    build = next(x for x in klass.body if isinstance(x, ast.FunctionDef) and x.name == '_build_ui')
    # `_build_ui()` has no argument/local called selected_view. The old form
    # raised NameError immediately on opening the window.
    unsafe = [x for x in ast.walk(build) if isinstance(x, ast.Name)
              and isinstance(x.ctx, ast.Load) and x.id == 'selected_view']
    assert not unsafe, '_build_ui uses undefined constructor-only variable selected_view'
    calls = [x for x in ast.walk(build) if isinstance(x, ast.Call)
             and isinstance(x.func, ast.Attribute) and x.func.attr == 'setCurrentIndex']
    assert any(any(isinstance(a, ast.Attribute)
                       and isinstance(a.value, ast.Name) and a.value.id == 'self'
                       and a.attr == '_selected_view' for a in call.args)
               for call in calls)


@pytest.mark.parametrize('initial_selection', [0, 1])
def test_orthogonal_window_initial_selected_view_qt(tmp_path, monkeypatch, initial_selection):
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6 import QtWidgets
    from loupe.orthogonal.viewer import OrthogonalDialog
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dataset = []
    for idx in range(2):
        subdir = tmp_path / f'dataset{idx}'
        subdir.mkdir()
        paths = []
        for i in range(2):
            f = subdir / f'rec{i:05d}.tif'
            f.write_bytes(b'placeholder')  # cache generation is deliberately disabled
            paths.append(f)
        dataset.append({'label': f'VIEW {idx + 1}', 'paths': paths,
                        'slice': 0, 'pixel_size_um': 0.65, 'current': None})
    monkeypatch.setattr(OrthogonalDialog, '_start_preview', lambda self: None)
    selected = dataset[initial_selection]
    dlg = OrthogonalDialog(selected['paths'], view_sources=dataset,
                           selected_view=initial_selection)
    try:
        assert dlg.view_selector.currentIndex() == initial_selection
        assert dlg.view_selector.currentText() == selected['label']
    finally:
        dlg.close()
