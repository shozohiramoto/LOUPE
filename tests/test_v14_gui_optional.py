"""Optional headless Qt smoke tests (run when PySide6/pyqtgraph are installed)."""
import os
import pytest
import numpy as np
import tifffile

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')
QtCore = pytest.importorskip('PySide6.QtCore')
pytest.importorskip('pyqtgraph')
from loupe.gui import MainWindow


@pytest.fixture()
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_qt_four_panes_calibration_and_slider(app, tmp_path):
    window = MainWindow()
    try:
        assert window.panel_count == 2
        window.left.cal_size.setValue(0.52)
        window.left.cal_enabled.setChecked(True)
        window.right.cal_size.setValue(0.21)
        window.right.cal_enabled.setChecked(True)
        assert window.left.calibration()['pixel_size'] == 0.52
        assert window.right.calibration()['pixel_size'] == 0.21
        assert window.left.calibration()['x'] == window.left.calibration()['y']
        assert window.right.calibration()['x'] == window.right.calibration()['y']
        for count in (1, 3, 4, 2):
            window.view_count.setCurrentIndex(count-1)
            assert window.panel_count == count
            assert len(window.state()['panels']) == count
        stack = tmp_path / 'stack'
        stack.mkdir()
        for i in range(5):
            tifffile.imwrite(stack / f'rec{i:05d}.tif', np.full((48, 64), i, dtype=np.uint16))
        window.left.open_path(stack)
        assert window.left.slice_slider.isEnabled()
        assert window.left.slice_slider.maximum() == 5
        window.left.slice_slider.setValue(3)
        assert window.left.index.value() == 3
    finally:
        window.close()


def test_qt_drag_and_drop_fills_views(app, tmp_path):
    window = MainWindow()
    try:
        paths=[]
        for i in range(4):
            path=tmp_path/f'test{i}.tif'
            tifffile.imwrite(path,np.full((24,24),i,dtype=np.uint8))
            paths.append(path)
        mime=QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(str(p)) for p in paths])
        assert window.left.accepts_drop(mime)
        window.left.handle_drop(mime)
        assert window.panel_count == 4
        assert all(panel.files for panel in window.visible_panels())
    finally:
        window.close()


def test_qt_per_view_scale_bar_and_png_report(app,tmp_path):
    """Real Qt smoke on Windows/offscreen if PySide6 and pyqtgraph exist."""
    import time
    from loupe.report import export_png_report
    window = MainWindow()
    try:
        a=tmp_path/'a.tif';b=tmp_path/'b.tif'
        tifffile.imwrite(a,np.arange(96*128,dtype=np.uint16).reshape(96,128))
        tifffile.imwrite(b,np.arange(96*128,dtype=np.uint16).reshape(96,128)[::-1])
        window.left.open_path(a)
        window.right.open_path(b)
        for _ in range(300):
            app.processEvents()
            if not window.left.loading and not window.right.loading:break
            time.sleep(.01)
        assert window.left.current is not None
        assert window.right.current is not None
        window.left.cal_enabled.setChecked(True)
        window.left.cal_size.setValue(.5)
        window.right.cal_enabled.setChecked(True)
        window.right.cal_size.setValue(1.2)
        assert window.left.scale_bar_line.isVisible()
        assert window.right.scale_bar_line.isVisible()
        assert window.left.scale_bar_label.textItem.toPlainText()!=window.right.scale_bar_label.textItem.toPlainText()
        png=tmp_path/'report.png'
        export_png_report(png,[window.left.report_payload(),window.right.report_payload()],
                          title='Test 2 panel report',comment='Test comment with TIFF data')
        assert png.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
        assert png.stat().st_size>10000
    finally:
        window.close()


def test_qt_float32_image_render_requires_levels(app,tmp_path):
    """Regression against the actual float TIFF/QGraphicsObject paint failure."""
    import time
    window=MainWindow()
    try:
        a=tmp_path/'float32.tif'
        image=np.linspace(-1,2,96*128,dtype=np.float32).reshape(96,128)
        tifffile.imwrite(a,image)
        window.left.open_path(a)
        for _ in range(300):
            app.processEvents()
            if not window.left.loading:break
            time.sleep(.01)
        assert window.left.current is not None
        assert window.left.current.dtype == np.float32
        assert window.left.image.getLevels() is not None
        low,high=window.left.image.getLevels()
        assert high>low
        # ImageItem.render() calls pyqtgraph's conversion path even in Qt offscreen.
        window.left.image.render()
        window.left.auto.setChecked(False)
        window.left.lo.setValue(-.5)
        window.left.hi.setValue(1.5)
        window.left.image.render()
        assert np.allclose(window.left.image.getLevels(),(-.5,1.5))
        window.left.restore({'path':None,'annotations_by_image':{}})
        window.left.image.render()
    finally:
        window.close()


def test_qt_four_panels_share_horizontal_row(app):
    window=MainWindow()
    try:
        window.resize(1366,768)
        window.show()
        app.processEvents()
        for count in (1,2,3,4):
            window.view_count.setCurrentIndex(count-1)
            app.processEvents()
            widths=[]
            for col,panel in enumerate(window.visible_panels()):
                index=window.panel_grid.indexOf(panel)
                assert window.panel_grid.getItemPosition(index)[:2] == (0,col)
                assert panel.isVisible()
                widths.append(panel.width())
            assert max(widths)-min(widths) < 8
            if count >= 3:
                assert all(p._compact for p in window.visible_panels())
        assert not window.left.plot.horizontalScrollBar().isVisible()
        assert not window.right.profile_plot.horizontalScrollBar().isVisible()
    finally:
        window.close()
