"""LOUPE adapter for the UI Standard 1.0.0; cosmetic only.

This module never touches image values, acquisition logic or measurement geometry.
"""
from __future__ import annotations
import json
from pathlib import Path

ASSET_ROOT = Path(__file__).resolve().parent.parent / 'bl09w_ui'

def theme():
    data=json.loads((ASSET_ROOT/'theme.json').read_text(encoding='utf-8'))
    if data.get('schema')!='bl09w.ui.theme' or data.get('version')!='1.0.0':
        raise ValueError('Incompatible BL09W UI theme')
    return data

def apply_qt_theme(app):
    """Apply colors and widget styling before MainWindow is constructed."""
    from PySide6 import QtGui
    import pyqtgraph as pg
    values=theme()
    app.setFont(QtGui.QFont(values['typography']['ui_font'], values['typography']['base_pt']))
    app.setStyleSheet((ASSET_ROOT/'qt_theme.qss').read_text(encoding='utf-8'))
    pal=values['palette']
    pg.setConfigOptions(background=pal['canvas'], foreground=pal['text_secondary'])
    return values['version']
