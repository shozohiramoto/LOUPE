"""Regression for PySide6 QSplitter.addWidget(QVBoxLayout) runtime TypeError.

This static test runs without Qt, so it prevents release builds from skipping
this class of GUI construction bug when PySide6 is unavailable.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_high_resolution_splitter_receives_qwidget():
    path = ROOT / 'loupe' / 'orthogonal' / 'high_resolution_widget.py'
    src = path.read_text(encoding='utf-8')
    tree = ast.parse(src)
    build_ui = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == '_build_ui'
    )
    declared = {}
    # Identify arguments assigned Qt layout constructors and QWidget constructors.
    for node in ast.walk(build_ui):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call) or not isinstance(node.value.func, ast.Attribute):
            continue
        kind = node.value.func.attr
        for target in node.targets:
            if isinstance(target, ast.Name):
                declared[target.id] = kind
    seen_splitter_widgets = []
    for node in ast.walk(build_ui):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not (isinstance(node.func.value, ast.Name) and
                node.func.value.id == 'splitter' and node.func.attr == 'addWidget'):
            continue
        assert len(node.args) == 1
        assert isinstance(node.args[0], ast.Name), 'Unexpected splitter argument form'
        arg = node.args[0].id
        assert declared.get(arg) in ('QWidget','QScrollArea'), (
            f'QSplitter.addWidget({arg}) receives {declared.get(arg)}, not QWidget'
        )
        seen_splitter_widgets.append(arg)
    assert seen_splitter_widgets == ['viewer', 'scroll']
