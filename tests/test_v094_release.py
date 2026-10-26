"""v0.9.4 report, shared ROI interaction and safe Fiji startup repair."""
import ast
from pathlib import Path
import pytest
from loupe.version import APP_VERSION
from loupe.fiji_bridge import (
    install_fiji_autostart, autostart_status, startup_autorun_supported,
    minimal_autorun_loader,
)
ROOT=Path(__file__).resolve().parents[1]


def test_release_and_shared_editor_contract():
    assert APP_VERSION=='0.9.8d'
    ctrl=(ROOT/'loupe/orthogonal/roi_controller.py').read_text(encoding='utf8')
    hr=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf8')
    for source in (ctrl,hr):ast.parse(source)
    assert 'AnnotationViewBox' in ctrl
    assert 'ImagePanel.__dict__[_name]' in ctrl
    for name in ('annotation_drag','redraw_measurements','preview_geometry_edit',
                 'refresh_edit_handles','add_count','delete_selected_annotation'):
        assert repr(name) in ctrl
    assert 'self.measure_viewbox.owner=self.roi_layer' in hr
    assert 'self.roi_layer.all_items()' in hr
    assert 'self.roi_layer.apply_annotations_from_history' in hr
    assert 'self.image.setRect(QtCore.QRectF(0,0,data.shape[1],data.shape[0]))' in hr
    assert '0<=z_local<h' in hr


def test_report_full_paths_dark_text_single_title():
    s=(ROOT/'loupe/report.py').read_text(encoding='utf8')
    ast.parse(s)
    assert "'LOUPE Report'" in s
    assert 'if _report_header_title(title):' in s
    assert 'REPORT_TEXT' in s
    assert "_report_path_lines(panel.get('path')" in s
    assert "_report_path_lines(item.get('path')" in s
    assert "painter.setPen(QtGui.QColor('#d3e0ee'))" not in s


def test_fiji_custom_startup_is_never_modified(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'Local'))
    from loupe.fiji_bridge import runtime_receiver_macro
    root=tmp_path/'Fiji.app'
    startup=root/'macros'/'StartupMacros.fiji.ijm'
    startup.parent.mkdir(parents=True)
    original=b'// Custom scientific startup\r\nrun("Analyse data");\r\n'
    startup.write_bytes(original)
    exe=root/'ImageJ-win64.exe';exe.write_bytes(b'exe')
    source=tmp_path/'receiver.py';source.write_text('# test receiver\n')
    with pytest.raises(RuntimeError,match='never edits'):
        install_fiji_autostart(exe,source,allow_custom_startup_repair=True)
    assert not list(startup.parent.glob('*.LOUPE_backup_*'))
    macro=runtime_receiver_macro(source)
    assert 'Macro_Runner.runPython' in macro
    assert startup.read_bytes()==original
    assert not (startup.parent/'AutoRun'/'LOUPE_Bridge_AutoRun.ijm').exists()


def test_report_path_wrap_helper():
    from loupe import report
    class Metrics:
        def horizontalAdvance(self,v):return 6*len(v)
    value=r'D:\Very\Long\Folder\name\rec00100.tif'
    lines=report._report_path_lines(value,Metrics(),60)
    assert ''.join(lines)==value
    assert all(len(x)<=11 for x in lines)
    assert report._report_header_title('LOUPE') is None
    assert report._report_header_title('LOUPE · High Resolution')=='High Resolution'
