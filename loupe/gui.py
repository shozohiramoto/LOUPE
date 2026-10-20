from pathlib import Path
import copy
import math
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from PySide6 import QtCore, QtWidgets, QtGui
import pyqtgraph as pg
from .io import discover, load_frame, display_limits, resolve_image_levels, estimate_frame_bytes
from .profiles import roi_endpoints, sample_thick_line
from .exports import write_csv, write_session, read_session, imagej_macro
from .measurements import (create_annotation, validate_annotation, caption, measurement,
    rect_mean_profile, rotated_rect_mean_profile, annotation_key, measurement_row,
    write_measurement_csv, adjust_annotation, snap_endpoint, frame, from_frame, physical_dimensions)
from .diagnostics import logger, log_action, create_bug_report, SESSION, VERSION
from .version import APP_STATUS, UI_STANDARD_VERSION, build_info
from .app_icon import icon_path
from .calibration_spin import CalibrationSpinBox
from .img_to_fiji import converted_img_file, clean_old_temporary_imports
from .fiji_bridge import (send_to_running_fiji, receiver_status, create_open_request,
                          read_job_status, runtime_receiver_macro)
from .ui_theme import theme
PROFILE_HEX = theme()["palette"]["profile"]
from .comparison import (MAX_PANELS, panel_indices_for_drop,
                         paths_from_mime, is_supported_drop_path)
from .calibration import normalize_calibration, scale_bar_for_span
from .tiff_metadata import read_reconstruction_metadata
from .report import export_png_report, export_pdf_report, render_report_image
from .output_paths import suggested_path, reserve_unique_path, rollback_empty
from .imagej_bridge import (heap_from_cfg, physical_available, inspect_sequence,
                           stack_preflight, imagej_stack_macro, imagej_current_macro,
                           launch_imagej_macro, detect_running_fiji, recent_fiji_launch,
                           recommended_stack_count, MIB)
from .fiji_rmi import send_macro_to_existing_fiji
from .layout import density_for_window, horizontal_cells
from .cache import FrameCache
import numpy as np

class Signals(QtCore.QObject):
    ready = QtCore.Signal(int, object, object)
    error = QtCore.Signal(int, str)

class AnnotationViewBox(pg.ViewBox):
    """Intercept left-button drags only when a measurement tool is selected."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = None

    def mouseDragEvent(self, event, axis=None):
        owner = self.owner
        if owner is not None and owner.parent_window is not None:
            owner.parent_window.set_active_panel(owner)
            owner.plot.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        if (owner is not None and owner.is_draw_tool() and owner.current is not None
                and not owner.loading and event.button() == QtCore.Qt.MouseButton.LeftButton
                and not owner.parent_window.space_pan_active):
            start = self.mapSceneToView(event.buttonDownScenePos())
            end = self.mapSceneToView(event.scenePos())
            shift = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
            owner.annotation_drag((start.x(), start.y()), (end.x(), end.y()), event.isFinish(), shift)
            event.accept()
            return
        super().mouseDragEvent(event, axis=axis)

    def mouseClickEvent(self, event):
        owner = self.owner
        if owner is not None and owner.parent_window is not None:
            owner.parent_window.set_active_panel(owner)
            owner.plot.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        if (owner is not None and owner.annotation_tool() == 'count'
                and owner.current is not None and not owner.loading
                and event.button() == QtCore.Qt.MouseButton.LeftButton):
            pt = self.mapSceneToView(event.scenePos())
            owner.add_count((pt.x(), pt.y()))
            event.accept()
            return
        super().mouseClickEvent(event)


class MeasurePathItem(QtWidgets.QGraphicsPathItem):
    """Editable ROI itself: click to select; drag its interior/border to move."""
    def __init__(self, panel, annotation_id, path):
        super().__init__(path)
        self.panel=panel
        self.annotation_id=annotation_id
        self.setZValue(14)
        self.setToolTip('Click: select | Drag: move | Handles: resize/rotate')
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self.setBrush(QtGui.QBrush(QtGui.QColor(0,0,0,0)))
        self._origin=None
        self._start=None

    def _point(self,event):
        p=self.panel.plot.getViewBox().mapSceneToView(event.scenePos())
        return (float(p.x()),float(p.y()))

    def mousePressEvent(self,event):
        if (event.button()!=QtCore.Qt.MouseButton.LeftButton or self.panel.loading or
                self.panel.parent_window.space_pan_active):
            event.ignore();return
        self.panel.parent_window.set_active_panel(self.panel)
        self.panel.plot.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        # Selecting does not remove this shape item from scene.
        self.panel.select_annotation(self.annotation_id)
        self._origin=self.panel.get_annotation(self.annotation_id)
        self._start=self._point(event)
        event.accept()

    def mouseMoveEvent(self,event):
        if self._origin is None:event.ignore();return
        self.panel.preview_geometry_edit(self._origin,'move',self._point(event),self._start)
        event.accept()

    def mouseReleaseEvent(self,event):
        if self._origin is None:event.ignore();return
        self.panel.preview_geometry_edit(self._origin,'move',self._point(event),self._start)
        original=self._origin
        self._origin=None
        QtCore.QTimer.singleShot(0,lambda:self.panel.commit_geometry_edit(original))
        event.accept()

class MeasurementHandle(QtWidgets.QGraphicsEllipseItem):
    """Constant-on-screen-size draggable handle for a selected measurement.

    Geometry is previewed while dragging but committed exactly once on release,
    preserving Undo/Redo and JSON persistence.
    """
    def __init__(self, panel, identifier, role, x, y):
        super().__init__(-5, -5, 10, 10)
        self.panel = panel
        self.annotation_id = identifier
        self.role = role
        self.setPos(float(x), float(y))
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setZValue(45)
        self.setBrush(QtGui.QBrush(QtGui.QColor('#ffe17a')))
        self.setPen(QtGui.QPen(QtGui.QColor('#303030'), 1))
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor if role=='rotate' else QtCore.Qt.CursorShape.SizeAllCursor)
        if role=='rotate':self.setBrush(QtGui.QBrush(QtGui.QColor('#ffa744')))
        self.setToolTip('Drag to rotate' if role=='rotate' else 'Drag to edit ROI')
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self._origin = None
        self._start = None

    def _point(self, event):
        p = self.panel.plot.getViewBox().mapSceneToView(event.scenePos())
        return (float(p.x()), float(p.y()))

    def mousePressEvent(self, event):
        if (event.button() != QtCore.Qt.MouseButton.LeftButton or
                self.panel.loading or self.panel.parent_window.space_pan_active):
            event.ignore();return
        self.panel.parent_window.set_active_panel(self.panel)
        self.panel.plot.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        self._origin = self.panel.get_annotation(self.annotation_id)
        self._start = self._point(event)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            self.panel.preview_geometry_edit(self._origin, self.role,
                                             self._point(event), self._start,
                                             constrain=bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier))
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if self._origin is not None:
            self.panel.preview_geometry_edit(self._origin, self.role,
                                             self._point(event), self._start,
                                             constrain=bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier))
            original = self._origin
            self._origin = None
            # Do not remove the active QGraphicsItem while its mouse-release
            # event is still being dispatched by QGraphicsScene.
            QtCore.QTimer.singleShot(0, lambda: self.panel.commit_geometry_edit(original))
            event.accept()
        else:
            event.ignore()


class TiffDropPlotWidget(pg.PlotWidget):
    """Drop target over the image viewport (QGraphicsView owns mouse events)."""
    def __init__(self, panel, **kwargs):
        super().__init__(**kwargs)
        self.panel = panel
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if self.panel.accepts_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.panel.accepts_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self.panel.accepts_drop(event.mimeData()):
            self.panel.handle_drop(event.mimeData())
            event.acceptProposedAction()
        else:
            event.ignore()


class ImagePanel(QtWidgets.QWidget):
    def __init__(self, name, pool, parent=None):
        super().__init__(parent)
        self.pool = pool
        self.cache = FrameCache()
        self.prefetch_pool=ThreadPoolExecutor(max_workers=1)
        self.display_name = name
        self._closing = False
        self.setAcceptDrops(True)
        self.files = []
        self.current = None
        self.current_path = None
        self.loading = False
        self.annotations_by_image = {}
        self.selected_annotation_id = None
        self.measurement_graphics = []
        self.preview_item = None
        self.edit_handles = []
        self.shape_items = {}
        self.caption_items = {}
        self._edit_preview = None
        self._profile_data = None
        self.token = 0
        self.fit_on_next_image = True
        # The calibration belongs to the dataset, not a previously opened TIFF.
        self._header_cal_pending = False
        self._calibration_source = 'manual'
        self._auto_header_um = None
        self._rotation_center_px = None
        self._header_cache = {}
        self.signals = Signals()
        self.signals.ready.connect(self.on_ready)
        self.signals.error.connect(self.on_error)
        outer = QtWidgets.QVBoxLayout(self)
        self.outer_layout = outer
        self._compact = False
        self._ultra = False
        self.setMinimumWidth(0)
        # Ignored horizontal size hints: QGridLayout must share available width
        # equally rather than expanding the main window to accommodate widgets.
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel(f'<b>{name}</b>'))
        btn = QtWidgets.QPushButton('Open Image')
        btn.setToolTip('Open a TIFF or supported BL09W .img image')
        btn.clicked.connect(self.open_dialog)
        top.addWidget(btn)
        outer.addLayout(top)
        self._full_path_text = 'No dataset loaded'
        self.path_label = QtWidgets.QLabel(self._full_path_text)
        self.path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.path_label.setMinimumWidth(0)
        self.path_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                      QtWidgets.QSizePolicy.Policy.Fixed)
        self.path_label.setToolTip(self._full_path_text)
        outer.addWidget(self.path_label)
        # Calibration belongs to this data panel, not to the entire comparison.
        pixel_row=QtWidgets.QGridLayout()
        self.pixel_grid = pixel_row
        self.cal_enabled=QtWidgets.QCheckBox('Pixel size')
        self.cal_enabled.setToolTip('Square-pixel calibration: initialise from reconstruction TIFF header when available; editable manually')
        self.cal_size=CalibrationSpinBox()
        self.cal_size.setDecimals(6)
        self.cal_size.setRange(0.000001,1e9)
        self.cal_size.setSingleStep(0.1)
        self.cal_size.setValue(1.0)
        self.cal_size.setToolTip('Enter a positive pixel size directly; the mouse wheel is disabled')
        self.cal_unit=QtWidgets.QComboBox()
        # Unit selector must preserve a text viewport beside the drop-down at
        # 125–200% Windows scaling. Global combo padding formerly hid 'µm'.
        self.cal_unit.setObjectName('LOUPE_PixelUnit')
        self.cal_unit.setToolTip('Pixel size unit (nm, µm or mm)')
        for unit in ('nm','µm','mm'):self.cal_unit.addItem(unit,unit)
        self.cal_unit.setCurrentIndex(1)
        self.show_scale_bar=QtWidgets.QCheckBox('Scale bar')
        self.show_scale_bar.setChecked(False)
        self.show_scale_bar.setEnabled(False)
        self.show_scale_bar.setToolTip('Show an accurately calibrated scale bar in this panel and its report image')
        # ID047: pixel value and unit are one atomic group; never wrap the
        # unit alone in 3–4 VIEW. Scale bar gets its own full-width row.
        self.calibration_value_group=QtWidgets.QWidget(self)
        self.calibration_value_group.setObjectName('LOUPE_PixelSizeUnitGroup')
        self.calibration_value_group.setMinimumWidth(0)
        self.calibration_value_group.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                                    QtWidgets.QSizePolicy.Policy.Fixed)
        self.calibration_value_layout=QtWidgets.QHBoxLayout(self.calibration_value_group)
        self.calibration_value_layout.setContentsMargins(0,0,0,0)
        self.calibration_value_layout.setSpacing(3)
        # Keep the number and its editable unit adjacent. Stretch *after* the
        # pair, not between the widgets (Qt stretch cells caused a large gap).
        self.calibration_value_layout.addWidget(self.cal_size)
        self.calibration_value_layout.addWidget(self.cal_unit)
        self.calibration_value_layout.addStretch(1)
        self._place_grid_widgets(pixel_row, [
            (self.cal_enabled,0,0,1,1),(self.calibration_value_group,0,1,1,2),
            (self.show_scale_bar,1,0,1,3)])
        outer.addLayout(pixel_row)
        self.cal_enabled.toggled.connect(self._user_calibration_source_changed)
        self.cal_size.valueChanged.connect(self._user_calibration_changed)
        self.cal_unit.currentIndexChanged.connect(self._user_calibration_source_changed)
        self.show_scale_bar.toggled.connect(self.calibration_changed)
        self.measure_viewbox = AnnotationViewBox()
        self.measure_viewbox.owner = self
        self.measure_viewbox.setMouseMode(pg.ViewBox.PanMode)
        self.plot = TiffDropPlotWidget(self, viewBox=self.measure_viewbox)
        self.plot.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        self.plot.setMinimumWidth(0)
        self.plot.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.plot.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.plot.setAspectLocked(True)
        self.plot.invertY(True)
        self.plot.hideAxis('left')
        self.plot.hideAxis('bottom')
        self.image = pg.ImageItem(axisOrder='row-major')
        self.plot.addItem(self.image)
        # Native-coordinate bar geometry is recalculated on every pan/zoom.
        self.scale_bar_line=pg.PlotDataItem(pen=pg.mkPen('#ffffff',width=4))
        self.scale_bar_line.setZValue(51)
        self.scale_bar_line.setVisible(False)
        self.scale_bar_label=pg.TextItem('',color='#ffffff',anchor=(0.5,1),
                                        fill=pg.mkBrush(10,18,30,210))
        self.scale_bar_label.setZValue(52)
        self.scale_bar_label.setVisible(False)
        self.plot.addItem(self.scale_bar_line)
        self.plot.addItem(self.scale_bar_label)
        self.plot.getViewBox().disableAutoRange()
        self.plot.getViewBox().sigRangeChanged.connect(self._view_range_changed)
        self.plot.scene().sigMouseMoved.connect(self._mouse_moved)
        # The in-image FIT affordance replaces the redundant toolbar Fit button.
        self._init_image_fit_button()
        self.image_profile_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.image_profile_splitter.setChildrenCollapsible(False)
        self.plot.setMinimumHeight(160)
        self.image_profile_splitter.addWidget(self.plot)
        outer.addWidget(self.image_profile_splitter, 1)
        self.roi = None
        self.width_overlay = None
        self.profile_active = False
        self.profile_plot = pg.PlotWidget()
        self.profile_plot.setMinimumWidth(0)
        self.profile_plot.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.profile_plot.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.profile_plot.setMinimumHeight(72)
        self.profile_plot.setLabel('bottom', 'Distance', units='px')
        self.profile_plot.setLabel('left', 'Original pixel value')
        self.profile_curve = self.profile_plot.plot(pen=pg.mkPen(PROFILE_HEX, width=2))
        self.image_profile_splitter.addWidget(self.profile_plot)
        self.image_profile_splitter.setStretchFactor(0, 5)
        self.image_profile_splitter.setStretchFactor(1, 1)
        self.profile_plot.hide()
        self.profile_plot.getViewBox().sigRangeChanged.connect(self._profile_range_changed)
        self.on_profile_change = None
        self.parent_window = None
        self._last_profile = None
        self._pending_restore = None
        row = QtWidgets.QHBoxLayout()
        self.nav_row = row
        self.prev = QtWidgets.QPushButton('◀')
        self.prev.clicked.connect(lambda: self.change(-1))
        self.counter = QtWidgets.QLabel('0 / 0')
        self.counter.setFixedWidth(110)
        self.counter.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.counter.setToolTip('Drag slider to preview slice number; release to load. Width remains fixed.')
        self.next = QtWidgets.QPushButton('▶')
        self.next.clicked.connect(lambda: self.change(1))
        self.index = QtWidgets.QSpinBox()
        self.index.setMinimum(1)
        self.index.valueChanged.connect(self.jump)
        self.slice_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slice_slider.setRange(1, 1)
        self.slice_slider.setTracking(False)  # avoid reading dozens of TIFFs during drag
        self.slice_slider.setEnabled(False)
        self.slice_slider.setToolTip('Drag to choose a slice; release to load it. Arrow keys also work.')
        self.slice_slider.valueChanged.connect(self.index.setValue)
        self.slice_slider.sliderMoved.connect(self.slice_slider_preview)
        self.index.valueChanged.connect(self.sync_slice_slider)
        row.addWidget(self.prev)
        row.addWidget(self.slice_slider, 1)
        row.addWidget(self.next)
        row.addWidget(self.index)
        row.addWidget(self.counter)
        outer.addLayout(row)
        levels = QtWidgets.QGridLayout()
        self.level_grid = levels
        # Auto mode is controlled from the Window / Level dialog; keep the
        # underlying per-image auto flag for existing JSON and GUI behavior.
        self.auto = QtWidgets.QCheckBox('Auto', self)
        self.auto.hide()
        self.auto.setChecked(True)
        self.auto.toggled.connect(self.refresh_levels)
        self.lo = QtWidgets.QDoubleSpinBox()
        self.hi = QtWidgets.QDoubleSpinBox()
        for w in (self.lo, self.hi):
            w.setRange(-1e30, 1e30)
            w.setDecimals(4)
            w.valueChanged.connect(self.refresh_levels)
        self.min_label = QtWidgets.QLabel('Min')
        self.max_label = QtWidgets.QLabel('Max')
        self.auto_button=QtWidgets.QPushButton('Auto Contrast')
        self.auto_button.setObjectName('LOUPE_AutoContrast')
        self.auto_button.setCheckable(True)
        self.auto_button.setChecked(True)
        self.auto.toggled.connect(self.auto_button.setChecked)
        self.auto_button.setToolTip('Auto-adjust the visible contrast using the original image intensities')
        self.auto_button.clicked.connect(self.enable_auto_contrast)
        self.wl_button=QtWidgets.QPushButton('Window / Level…')
        self.wl_button.setToolTip('Fine control: Window, Level, histogram and numeric Min / Max')
        self.wl_button.clicked.connect(self.open_levels_dialog)
        self.reset_button=QtWidgets.QPushButton('Reset')
        self.reset_button.setToolTip('Show the full intensity range of this image')
        self.reset_button.clicked.connect(self.reset_contrast)
        for button in (self.auto_button, self.wl_button, self.reset_button):
            button.setMinimumWidth(0)
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                 QtWidgets.QSizePolicy.Policy.Fixed)
        self._place_grid_widgets(levels, [(self.auto_button,0,0,1,1),
                                          (self.wl_button,0,1,1,1),
                                          (self.reset_button,0,2,1,1)])
        outer.addLayout(levels)
        meas_row = QtWidgets.QGridLayout()
        self.measure_grid = meas_row
        self.roi_label = QtWidgets.QLabel('ROI')
        meas_row.addWidget(self.roi_label,0,0)
        self.roi_selector = QtWidgets.QComboBox()
        self.roi_selector.setMinimumWidth(130)
        self.roi_selector.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                        QtWidgets.QSizePolicy.Policy.Fixed)
        self.roi_selector.currentIndexChanged.connect(self.roi_selection_changed)
        meas_row.addWidget(self.roi_selector,0,1)
        self.roi_delete = QtWidgets.QPushButton('Delete ROI')
        self.roi_delete.clicked.connect(self.delete_selected_annotation)
        meas_row.addWidget(self.roi_delete,0,2)
        self.count_total = QtWidgets.QLabel('Count: 0')
        meas_row.addWidget(self.count_total,0,4)
        outer.addLayout(meas_row)
        self.roi_details=QtWidgets.QLabel('')
        self.roi_details.setMinimumWidth(0)
        self.roi_details.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                       QtWidgets.QSizePolicy.Policy.Fixed)
        self.roi_details.setToolTip('Selected ROI measurements; physical values require valid Pixel Size')
        outer.addWidget(self.roi_details)
        self.cursor_label = QtWidgets.QLabel('Cursor: — | Intensity: —')
        self.cursor_label.setMinimumWidth(0)
        self.cursor_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                        QtWidgets.QSizePolicy.Policy.Fixed)
        outer.addWidget(self.cursor_label)
        self._full_status_text = 'Ready'
        self.status = QtWidgets.QLabel('Ready')
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                  QtWidgets.QSizePolicy.Policy.Fixed)
        outer.addWidget(self.status)

    def _init_image_fit_button(self):
        # pyqtgraph's 'A' auto-range glyph is unclear to first-time users.
        auto = getattr(self.plot.plotItem, 'autoBtn', None)
        if auto is not None:
            auto.hide()
        self.image_fit_button = QtWidgets.QPushButton('FIT', self.plot.viewport())
        self.image_fit_button.setToolTip('Fit the entire image to this VIEW')
        self.image_fit_button.setFixedSize(54, 27)
        self.image_fit_button.clicked.connect(self.fit_view)
        self.image_fit_button.hide()
        self.plot.viewport().setMouseTracking(True)
        self.plot.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if hasattr(self, 'image_fit_button') and watched is self.plot.viewport():
            kind=event.type()
            if kind in (QtCore.QEvent.Type.Enter, QtCore.QEvent.Type.MouseMove):
                self.image_fit_button.move(max(0,watched.width()-62),8)
                self.image_fit_button.setVisible(self.current is not None)
            elif kind==QtCore.QEvent.Type.Leave:
                self.image_fit_button.hide()
            elif kind==QtCore.QEvent.Type.Resize:
                self.image_fit_button.move(max(0,watched.width()-62),8)
        return super().eventFilter(watched,event)

    @staticmethod
    def _place_grid_widgets(layout, placements):
        # Reparent positions without recreating controls or losing their signals.
        for widget, *_ in placements:
            layout.removeWidget(widget)
        for widget, row, col, height, width in placements:
            layout.addWidget(widget, row, col, height, width)

    def set_compact_mode(self, compact, ultra=False):
        """Keep 3/4 panels within current window, even when relatively narrow."""
        compact = bool(compact)
        ultra = bool(ultra) and compact
        if compact == self._compact and ultra == self._ultra:
            return
        self._compact = compact
        self._ultra = ultra
        self.outer_layout.setContentsMargins(*(4, 4, 4, 4) if compact else (9, 9, 9, 9))
        self.outer_layout.setSpacing(4 if compact else 6)
        for layout in (self.pixel_grid, self.level_grid, self.measure_grid):
            layout.setHorizontalSpacing(4 if compact else 6)
            layout.setVerticalSpacing(3 if compact else 6)
        if compact:
            self.cal_enabled.setText('Pixel size')
            self.show_scale_bar.setText('Scale bar')
            self.auto.setText('Auto')
            self.roi_delete.setText('Delete')
            self.cal_size.setFixedWidth(72 if ultra else 86)
            # A 48–54 px QComboBox cannot render 'µm' alongside the global
            # drop-down/padding on Windows (all four VIEWs can show a blank).
            # Font metrics keep the full symbol readable with DPI scaling.
            unit_text_px=max(self.cal_unit.fontMetrics().horizontalAdvance(
                self.cal_unit.itemText(i)) for i in range(self.cal_unit.count()))
            self.cal_unit.setFixedWidth(max(78, unit_text_px+48))
            self.lo.setFixedWidth(98)
            self.hi.setFixedWidth(98)
            self.roi_selector.setMinimumWidth(0)
            self.index.setFixedWidth(49 if ultra else 58)
            self.counter.setVisible(not ultra)
            self.counter.setToolTip('Current slice / total slices')
            self.prev.setFixedWidth(29)
            self.next.setFixedWidth(29)
            self.profile_plot.setMinimumHeight(72)
            self.profile_plot.setMaximumHeight(16777215)
            if ultra:
                self._place_grid_widgets(self.pixel_grid, [
                    (self.cal_enabled,0,0,1,1),(self.calibration_value_group,0,1,1,2),
                    (self.show_scale_bar,1,0,1,3)])
                self._place_grid_widgets(self.level_grid, [(self.auto_button,0,0,1,1),
                                                       (self.wl_button,0,1,1,1),
                                                       (self.reset_button,0,2,1,1)])
            else:
                self._place_grid_widgets(self.pixel_grid, [
                    (self.cal_enabled,0,0,1,1),(self.calibration_value_group,0,1,1,2),
                    (self.show_scale_bar,1,0,1,3)])
                self._place_grid_widgets(self.level_grid, [(self.auto_button,0,0,1,1),
                                                       (self.wl_button,0,1,1,1),
                                                       (self.reset_button,0,2,1,1)])
            self._place_grid_widgets(self.measure_grid, [
                (self.roi_label,0,0,1,1),(self.roi_selector,0,1,1,3),
                (self.roi_delete,1,0,1,2),
                (self.count_total,1,2,1,2)])
        else:
            self.counter.show()
            self.cal_enabled.setText('Pixel size')
            self.show_scale_bar.setText('Scale bar')
            self.auto.setText('Auto')
            self.roi_delete.setText('Delete ROI')
            for widget in (self.cal_size,self.cal_unit,self.lo,self.hi,self.index,self.prev,self.next):
                widget.setMinimumWidth(0)
                widget.setMaximumWidth(16777215)
            unit_text_px=max(self.cal_unit.fontMetrics().horizontalAdvance(
                self.cal_unit.itemText(i)) for i in range(self.cal_unit.count()))
            self.cal_unit.setMinimumWidth(max(78, unit_text_px+48))
            self.roi_selector.setMinimumWidth(130)
            self.profile_plot.setMinimumHeight(72)
            self.profile_plot.setMaximumHeight(16777215)
            self._place_grid_widgets(self.pixel_grid, [
                (self.cal_enabled,0,0,1,1),(self.calibration_value_group,0,1,1,2),
                (self.show_scale_bar,1,0,1,3)])
            self._place_grid_widgets(self.level_grid, [(self.auto_button,0,0,1,1),
                                                       (self.wl_button,0,1,1,1),
                                                       (self.reset_button,0,2,1,1)])
            self._place_grid_widgets(self.measure_grid, [
                (self.roi_label,0,0,1,1),(self.roi_selector,0,1,1,1),
                (self.roi_delete,0,2,1,2),
                (self.count_total,0,4,1,1)])
        self._update_path_display()
        self.update_roi_selector()
        self.updateGeometry()

    def _update_path_display(self):
        text = self._full_path_text
        limit = max(55, self.path_label.width()-8)
        self.path_label.setText(self.path_label.fontMetrics().elidedText(
            text, QtCore.Qt.TextElideMode.ElideMiddle, limit))
        self.path_label.setToolTip(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'path_label'):
            self._update_path_display()
        if hasattr(self, 'status'):
            self._update_status_display()

    def _update_status_display(self):
        if not hasattr(self, 'status'):
            return
        full = getattr(self, '_full_status_text', 'Ready')
        self.status.setToolTip(full)
        width = self.status.width() or self.width()
        # Always expose the full metadata in the tooltip, even at 4-view width.
        self.status.setText(self.status.fontMetrics().elidedText(
            full, QtCore.Qt.TextElideMode.ElideMiddle, max(80, width - 4)))

    def accepts_drop(self, mime):
        paths = paths_from_mime(mime)
        return bool(paths and len(paths) <= MAX_PANELS and
                    all(is_supported_drop_path(p) for p in paths))

    def handle_drop(self, mime):
        paths = paths_from_mime(mime)
        if paths and self.parent_window is not None:
            self.parent_window.open_dropped_paths(self, paths)

    def dragEnterEvent(self, event):
        if self.accepts_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.accepts_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self.accepts_drop(event.mimeData()):
            self.handle_drop(event.mimeData())
            event.acceptProposedAction()
        else:
            event.ignore()

    def slice_slider_preview(self, number):
        if self.files:
            self.counter.setText(f'{number} / {len(self.files)}')

    def sync_slice_slider(self, number):
        with QtCore.QSignalBlocker(self.slice_slider):
            self.slice_slider.setValue(number)

    def open_dialog(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Choose image', '', 'Images (*.tif *.tiff *.img);;TIFF (*.tif *.tiff);;BL09W IMG (*.img)')
        if f:
            self.open_path(f)

    def folder_dialog(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose TIFF / IMG folder')
        if folder:
            self.open_path(folder)

    def open_path(self, path):
        self.cache.clear()
        self._header_cache.clear()
        self._rotation_center_px = None
        # Explicit per-view saved calibration wins on session restore.
        if self._pending_restore is None:
            self._header_cal_pending = True
        try:
            self.files, initial = discover(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, 'Cannot open', str(e))
            return
        with QtCore.QSignalBlocker(self.index), QtCore.QSignalBlocker(self.slice_slider):
            self.index.setMaximum(len(self.files))
            self.index.setValue(initial + 1)
            self.slice_slider.setRange(1, len(self.files))
            self.slice_slider.setValue(initial + 1)
        self.slice_slider.setEnabled(len(self.files) > 1)
        self.fit_on_next_image = True
        if self.roi is not None:
            self.plot.removeItem(self.roi)
            self.roi = None
        if self.width_overlay is not None:
            self.plot.removeItem(self.width_overlay)
            self.width_overlay = None
        log_action('Dataset opened',panel=self.display_name,file=Path(path).name,frames=len(self.files))
        self.request(initial)

    def jump(self, val):
        if self.files:
            self.request(val - 1)

    def change(self, d):
        if self.files:
            self.index.setValue(max(1, min(len(self.files), self.index.value()+d)))

    def request(self, i):
        if not 0 <= i < len(self.files):
            return
        self.token += 1
        self.loading = True
        token = self.token
        path = self.files[i]
        self.counter.setText(f'{i+1} / {len(self.files)}')
        self._full_path_text = str(path)
        self._update_path_display()
        self.status.setText('Loading…')
        cached=self.cache.get(path)
        if cached is not None:
            QtCore.QTimer.singleShot(0,lambda:self.signals.ready.emit(token,path,cached))
            return
        future = self.pool.submit(load_frame, path)
        def done(f):
            try:
                arr = f.result()
                self.signals.ready.emit(token, path, arr)
            except Exception as e:
                self.signals.error.emit(token, str(e))
        future.add_done_callback(done)

    @QtCore.Slot(int, object, object)
    def on_ready(self, token, path, arr):
        if token != self.token:
            return
        view_box = self.plot.getViewBox()
        keep_view = not self.fit_on_next_image
        old_range = view_box.viewRange() if keep_view else None
        self.current = arr
        self.cache.put(path,arr)
        self.current_path = annotation_key(path)
        # This header read is image-data-free; do it for every selected slice
        # to display the current slice's rotation center accurately.
        if path not in self._header_cache:
            try:
                self._header_cache[path] = (read_reconstruction_metadata(path)
                                            if Path(path).suffix.lower() in ('.tif', '.tiff') else None)
            except Exception as exc:
                logger().warning('TIFF metadata unavailable: %s (%s)', Path(path).name, exc)
                self._header_cache[path] = None
        metadata = self._header_cache[path]
        if metadata:
            self._auto_header_um=float(metadata['pixel_size_um'])
        # When a previous invalid session corrupted calibration by orders of
        # magnitude, recover only the obviously invalid unit-scale mismatch.
        if metadata and self.cal_enabled.isChecked():
            try:
                unit_factor={'nm':0.001,'µm':1.,'mm':1000.}[self.cal_unit.currentData()]
                shown_um=float(self.calibration()['pixel_size'])*unit_factor
                header_um=float(metadata['pixel_size_um'])
                if shown_um/header_um >= 1000 or shown_um/header_um <= 0.001:
                    self.set_calibration({'enabled':True,'pixel_size':header_um,
                        'unit':'µm','source':'tiff_header'},
                        show_bar=self.show_scale_bar.isChecked())
                    log_action('Invalid pixel calibration recovered from TIFF header',
                               panel=self.display_name,invalid_um=shown_um,verified_um=header_um)
            except (ValueError,KeyError,ZeroDivisionError,OverflowError):
                pass
        self._rotation_center_px = (metadata['rotation_center_px'] if metadata else None)
        if self._header_cal_pending:
            self._header_cal_pending = False
            if metadata:
                self.set_calibration({'enabled': True,
                                      'pixel_size': metadata['pixel_size_um'],
                                      'unit': 'µm', 'source': 'tiff_header'},
                                     show_bar=False)
                log_action('Calibration imported from TIFF header',
                           panel=self.display_name,file=Path(path).name,
                           pixel_size_um=metadata['pixel_size_um'],
                           rotation_center_px=metadata['rotation_center_px'])
            else:
                # An uncalibrated TIFF must not inherit another dataset's scale.
                self.set_calibration({'enabled': False, 'pixel_size': 1.0,
                                      'unit': 'µm', 'source': 'manual'},
                                     show_bar=False)
        self.loading = False
        # Establish levels atomically with image assignment.  Without explicit
        # levels, ImageItem.paint() can fail for float32/float64 TIFF arrays
        # before the subsequent refresh_levels() has a chance to run.
        self._auto_levels = display_limits(arr)
        levels = resolve_image_levels(
            arr, auto=self.auto.isChecked(),
            manual=(self.lo.value(), self.hi.value()),
            auto_levels=self._auto_levels)
        self.image.setImage(arr, autoLevels=False, levels=levels)
        if self.auto.isChecked() or self.hi.value() <= self.lo.value():
            # Keep visible controls consistent with the effective levels.
            for spin, value in zip((self.lo, self.hi), levels):
                with QtCore.QSignalBlocker(spin):
                    spin.setValue(value)
        self.redraw_measurements()
        self.update_scale_bar()
        self.refresh_levels()
        if self.profile_active:
            self.ensure_roi()
            self.update_profile()
        if keep_view and old_range is not None:
            # Preserve zoom and pan in source-image pixel coordinates.
            view_box.setRange(xRange=old_range[0], yRange=old_range[1], padding=0)
        else:
            self.fit_view()
        view_box.disableAutoRange()
        self.fit_on_next_image = False
        label = f'{arr.shape[1]} × {arr.shape[0]} | {arr.dtype} | {Path(path).name}'
        if self._rotation_center_px is not None:
            label += f' | Rotation center: {self._rotation_center_px:g} px'
        self._full_status_text = label
        self._update_status_display()
        log_action('Image loaded',panel=self.display_name,file=Path(path).name,shape=f'{arr.shape[1]}x{arr.shape[0]}',dtype=arr.dtype)
        # Low-priority prefetch of adjacent slices, preserving a 128-MiB LRU limit.
        # Deferred to prioritize rapid manual navigation over background I/O.
        current_token=self.token
        def queue_neighbors():
            if self._closing or current_token!=self.token or not self.files:return
            i=self.index.value()-1
            for k in (i-1,i+1):
                if 0<=k<len(self.files):
                    self.prefetch_pool.submit(self.cache.prefetch,self.files[k],load_frame,estimate_frame_bytes)
        QtCore.QTimer.singleShot(180,queue_neighbors)
        if self._pending_restore is not None:
            state=self._pending_restore
            self._pending_restore=None
            self.apply_restored_view(state)

    def snapshot(self):
        vr=self.plot.getViewBox().viewRange()
        return {'side': self.objectName(),
                'path':str(self.files[self.index.value()-1]) if self.files else None,
                'slice':self.index.value() if self.files else None,
                'line':self.get_line() if self.roi else None,
                'view_range': [[float(v) for v in axis] for axis in vr],
                'auto_contrast':self.auto.isChecked(),
                'levels':[float(self.lo.value()),float(self.hi.value())],
                'annotations_by_image': copy.deepcopy(self.annotations_by_image),
                'calibration':self.calibration(),
                'show_scale_bar':self.show_scale_bar.isChecked()}

    def restore(self, state, calibration_default=None):
        self.set_calibration(normalize_calibration(state.get('calibration'),calibration_default),
                             bool(state.get('show_scale_bar',False)))
        # Old JSONs with no calibration can still auto-detect TIFF metadata.
        self._header_cal_pending = ('calibration' not in state and calibration_default is None)
        groups = state.get('annotations_by_image', {})
        if not isinstance(groups, dict):
            raise ValueError('Malformed ROI groups in comparison JSON')
        normalized = {}
        for file_path, items in groups.items():
            if not isinstance(file_path, str) or not isinstance(items, list):
                raise ValueError('Malformed ROI groups in comparison JSON')
            if len(items) > 10000:
                raise ValueError('Too many ROIs in a single image')
            normalized[annotation_key(file_path)] = [validate_annotation(x) for x in items]
        self.annotations_by_image = normalized
        self.selected_annotation_id = None
        self.redraw_measurements()
        path=state.get('path')
        if not path:
            # A comparison can legitimately have only one side populated.
            self.token += 1  # invalidate a still-running TIFF read
            self.loading = False
            self.files = []
            self.current = None
            self.current_path = None
            self._profile_data = None
            if self.roi is not None:
                self.plot.removeItem(self.roi)
                self.roi = None
            if self.width_overlay is not None:
                self.plot.removeItem(self.width_overlay)
                self.width_overlay = None
            self._auto_levels=(0.0,1.0)
            self.image.setImage(np.zeros((1,1),dtype=np.uint8),
                                autoLevels=False, levels=(0.0,1.0))
            self.update_scale_bar()
            self.counter.setText('0 / 0')
            self._full_path_text = 'No dataset loaded'
            self._update_path_display()
            self._rotation_center_px = None
            self._full_status_text = 'Ready'
            self._update_status_display()
            self._header_cal_pending = False
            self.index.blockSignals(True)
            self.index.setValue(1)
            self.index.setMaximum(1)
            self.index.blockSignals(False)
            with QtCore.QSignalBlocker(self.slice_slider):
                self.slice_slider.setRange(1,1)
                self.slice_slider.setValue(1)
            self.slice_slider.setEnabled(False)
            self.profile_curve.setData([], [])
            self.redraw_measurements()
            return
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        self._pending_restore=state
        self.open_path(path)
        slice_number=int(state.get('slice') or 1)
        if slice_number<1 or slice_number>len(self.files):
            raise ValueError(f'Slice {slice_number} is not present in {path}')
        self.index.setValue(slice_number)

    def apply_restored_view(self,state):
        self.auto.blockSignals(True)
        self.auto.setChecked(bool(state.get('auto_contrast',True)))
        self.auto.blockSignals(False)
        self.auto_button.setChecked(self.auto.isChecked())
        for spin,value in zip((self.lo,self.hi),state.get('levels',[0,1])):
            spin.blockSignals(True);spin.setValue(float(value));spin.blockSignals(False)
        if not self.auto.isChecked(): self.refresh_levels()
        if self.profile_active:
            self.ensure_roi()
            if state.get('line') is not None: self.set_line(state['line'])
        ranges=state.get('view_range')
        if ranges and len(ranges)==2:
            self.plot.getViewBox().setRange(xRange=ranges[0],yRange=ranges[1],padding=0)
            self.plot.getViewBox().disableAutoRange()
        self.update_profile()

    def annotation_tool(self):
        return self.parent_window.annotation_tool.currentData() if self.parent_window else 'pan'

    def is_draw_tool(self):
        return self.annotation_tool() in ('line', 'rect', 'ellipse')

    def calibration(self):
        size=getattr(self,'_precise_cal_size',self.cal_size.value())
        return normalize_calibration({'enabled':self.cal_enabled.isChecked(),
                                      'pixel_size':size,'unit':self.cal_unit.currentData(),
                                      'source':self._calibration_source})

    def set_calibration(self, cal, show_bar=False):
        cal=normalize_calibration(cal)
        widgets=(self.cal_enabled,self.cal_size,self.cal_unit,self.show_scale_bar)
        blockers=[QtCore.QSignalBlocker(w) for w in widgets]
        try:
            self.cal_enabled.setChecked(cal['enabled'])
            self._precise_cal_size=cal['pixel_size']
            self._calibration_source=cal['source']
            self.cal_size.setValue(cal['pixel_size'])
            idx=self.cal_unit.findData(cal['unit'])
            self.cal_unit.setCurrentIndex(idx if idx>=0 else 1)
            self.show_scale_bar.setChecked(bool(show_bar))
        finally:
            del blockers
        self.calibration_changed(log=False)

    def _user_calibration_changed(self, *args):
        self._precise_cal_size = self.cal_size.value()
        self._user_calibration_source_changed()

    def _user_calibration_source_changed(self, *args):
        self._calibration_source = 'manual'
        self._header_cal_pending = False
        self.calibration_changed()

    def calibration_changed(self,*_,log=True):
        self.show_scale_bar.setEnabled(self.cal_enabled.isChecked())
        src = ('TIFF ImageDescription' if self._calibration_source == 'tiff_header'
               else 'session metadata' if self._calibration_source == 'dataset_json'
               else 'manual entry')
        self.cal_size.setToolTip(f'Pixel size ({src}): {self._precise_cal_size:.10g} {self.cal_unit.currentData()}/px')
        # Keep the displayed text consistent with the numeric model, including
        # after asynchronous TIFF loads and changes to VIEW count.
        if not self.cal_size.hasFocus() and self.cal_size.text().strip() != format(self._precise_cal_size,'.10g'):
            with QtCore.QSignalBlocker(self.cal_size):
                self.cal_size.setValue(self._precise_cal_size)
        self.update_scale_bar()
        self.redraw_measurements()  # includes ROI selector/physical captions
        if log and self.parent_window:
            log_action('Panel pixel calibration changed',panel=self.display_name,
                       enabled=self.cal_enabled.isChecked(),
                       pixel_size=self.calibration()["pixel_size"],unit=self.cal_unit.currentData(),
                       bar=self.show_scale_bar.isChecked())

    def update_scale_bar(self):
        if not hasattr(self,'scale_bar_line'):return
        if self.current is None or not self.cal_enabled.isChecked() or not self.show_scale_bar.isChecked():
            self.scale_bar_line.hide();self.scale_bar_label.hide();return
        vr=self.plot.getViewBox().viewRange()
        x0,x1=sorted(vr[0]);y0,y1=sorted(vr[1])
        span=x1-x0
        if span<=0 or y1<=y0:return
        item=scale_bar_for_span(span,self.calibration())
        if item is None:return
        # Image y grows down: show near lower-left of current native view.
        x=x0+span*0.055
        y=y1-(y1-y0)*0.075
        length=item['pixels']
        # No image-level resampling: bar length is measured in TIFF pixels.
        self.scale_bar_line.setData([x,x,x+length,x+length],
                                   [y-(y1-y0)*0.012,y,y,y-(y1-y0)*0.012],
                                   connect='all')
        self.scale_bar_label.setText(item['label'])
        self.scale_bar_label.setPos(x+length/2,y-(y1-y0)*0.014)
        self.scale_bar_line.show();self.scale_bar_label.show()

    def report_payload(self):
        if self.current is None or self.loading:return None
        profile = self.profile_export_record() if self.profile_active else None
        return {'side':self.display_name,
                'path':str(self.files[self.index.value()-1]) if self.files else '',
                'slice':self.index.value(), 'image':self.current,
                'levels':(self.lo.value(),self.hi.value()),
                'view_range':self.plot.getViewBox().viewRange(),
                'annotations':copy.deepcopy(self.visible_annotations()),
                'calibration':self.calibration(),
                'show_scale_bar':self.show_scale_bar.isChecked(),
                'profile':profile,
                'profile_line':self.get_line() if (self.profile_active and
                  self.parent_window.profile_source.currentData()=='line' and self.roi is not None) else None}

    def active_annotation_key(self):
        return self.current_path

    def visible_annotations(self):
        return self.annotations_by_image.get(self.active_annotation_key(), [])

    def select_annotation(self, identifier):
        self.selected_annotation_id = identifier
        self.update_roi_selector()
        self.update_annotation_styles()
        if self.profile_active:
            self.update_profile()

    def roi_selection_changed(self, index):
        self.selected_annotation_id = self.roi_selector.itemData(index) if index >= 0 else None
        self.update_annotation_styles()
        if hasattr(self,'roi_details'):
            obj=self.get_annotation(self.selected_annotation_id)
            self.roi_details.setText(caption(obj,self.calibration()) if obj else '')
        if self.profile_active:
            self.update_profile()

    def update_roi_selector(self):
        self.roi_selector.blockSignals(True)
        self.roi_selector.clear()
        for i, item in enumerate(self.visible_annotations(), start=1):
            display={'rect':'Rectangle','ellipse':'Ellipse','circle':'Circle',
                     'line':'Line','count':'Count'}.get(item['type'],item['type'])
            self.roi_selector.addItem(f'{i} — {display}',item['id'])
        ids = [item['id'] for item in self.visible_annotations()]
        if self.selected_annotation_id not in ids:
            self.selected_annotation_id = ids[-1] if ids else None
        if self.selected_annotation_id:
            self.roi_selector.setCurrentIndex(ids.index(self.selected_annotation_id))
        self.roi_delete.setEnabled(bool(ids))
        if hasattr(self,'roi_details'):
            self.roi_details.setText(caption(self.get_annotation(self.selected_annotation_id),
                self.calibration()) if self.get_annotation(self.selected_annotation_id) else '')
        count = sum(item['type']=='count' for item in self.visible_annotations())
        self.count_total.setText(f'{"#" if self._compact else "Count:"} {count}')
        selected = self.get_annotation(self.selected_annotation_id)
        self.roi_selector.blockSignals(False)

    def get_annotation(self, identifier):
        return next((copy.deepcopy(a) for a in self.visible_annotations()
                     if a['id'] == identifier), None)

    def edit_annotation_dialog(self):
        selected=self.get_annotation(self.selected_annotation_id)
        if selected is None or selected['type'] not in ('line','rect','ellipse','circle'):
            return
        kind=selected['type']
        if kind=='line':
            labels=('Start X','Start Y','End X','End Y')
            values=selected['start']+selected['end']
        else:
            cx,cy,w,h,angle=frame(selected)
            labels=('Center X','Center Y','Width','Height','Angle')
            values=(cx,cy,w,h,angle)
        dialog=QtWidgets.QDialog(self)
        dialog.setWindowTitle('Edit '+kind+' (native pixels)')
        layout=QtWidgets.QFormLayout(dialog)
        spins=[]
        for label,value in zip(labels,values):
            spin=QtWidgets.QDoubleSpinBox(dialog)
            spin.setDecimals(2);spin.setSingleStep(0.1)
            spin.setRange(0.5 if label in ('Width','Height') else -1e7,1e7)
            spin.setValue(float(value))
            layout.addRow(label+(' (°)' if label=='Angle' else ' (px)'),spin)
            spins.append(spin)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                    QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        layout.addRow(buttons)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()!=QtWidgets.QDialog.DialogCode.Accepted:return
        v=[x.value() for x in spins]
        try:
            if kind=='line':
                new=create_annotation('line',v[:2],v[2:],identifier=selected['id'])
            elif kind=='circle':
                # Legacy v1.2 circle can become a freely editable ellipse.
                new=from_frame('ellipse',v[0],v[1],v[2],v[3],v[4],selected['id'])
            else:
                new=from_frame(kind,*v,selected['id'])
            self.replace_annotation(new)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self,'Invalid ROI',str(e))

    @staticmethod
    def shape_path(item):
        path=QtGui.QPainterPath()
        kind=item['type']
        if kind=='line':
            (x0,y0),(x1,y1)=item['start'],item['end']
            path.moveTo(x0,y0);path.lineTo(x1,y1)
            label=(x1,y1)
        elif kind in ('rect','ellipse','circle'):
            cx,cy,w,h,angle=frame(item)
            bounds=QtCore.QRectF(cx-w/2,cy-h/2,w,h)
            if kind=='rect':path.addRect(bounds)
            else:path.addEllipse(bounds)
            if angle:
                tr=QtGui.QTransform()
                tr.translate(cx,cy);tr.rotate(angle);tr.translate(-cx,-cy)
                path=tr.map(path)
            dx,dy=math.cos(math.radians(angle))*w/2,math.sin(math.radians(angle))*w/2
            label=(cx+dx,cy+dy)
        else:
            x,y=item['point']
            path.moveTo(x-1,y);path.lineTo(x+1,y)
            path.moveTo(x,y-1);path.lineTo(x,y+1)
            label=(x,y)
        return path,label

    def clear_edit_handles(self):
        for obj in self.edit_handles:
            try: self.plot.removeItem(obj)
            except (RuntimeError, ValueError): pass
        self.edit_handles.clear()

    def edit_handle_positions(self,item):
        if item['type']=='line':
            x0,y0=item['start'];x1,y1=item['end']
            return {'start':(x0,y0),'end':(x1,y1),'move':((x0+x1)/2,(y0+y1)/2)}
        if item['type'] in ('rect','ellipse'):
            cx,cy,w,h,angle=frame(item)
            def world(u,v):
                rad=math.radians(angle)
                return cx+u*math.cos(rad)-v*math.sin(rad),cy+u*math.sin(rad)+v*math.cos(rad)
            offsets={'nw':(-w/2,-h/2),'n':(0,-h/2),'ne':(w/2,-h/2),
                     'w':(-w/2,0),'move':(0,0),'e':(w/2,0),
                     'sw':(-w/2,h/2),'s':(0,h/2),'se':(w/2,h/2),
                     'rotate':(0,-h/2-max(8,h*0.2))}
            return {key:world(*pt) for key,pt in offsets.items()}
        if item['type']=='circle':
            x,y=item['center'];r=item['radius']
            return {'move':(x,y),'radius':(x+r,y)}
        return {}

    def refresh_edit_handles(self):
        self.clear_edit_handles()
        if self.current is None:
            return
        item = self.get_annotation(self.selected_annotation_id)
        if item is None or item['type'] not in ('line','rect','ellipse','circle'):
            return
        for role,(x,y) in self.edit_handle_positions(item).items():
            handle = MeasurementHandle(self,item['id'],role,x,y)
            self.plot.addItem(handle)
            self.edit_handles.append(handle)

    def preview_geometry_edit(self, original, role, point, start, constrain=False):
        if self.current is None or self.loading:
            return
        try:
            item = adjust_annotation(original,role,point,drag_start=start,
                                     image_shape=self.current.shape, constrain=constrain)
        except ValueError:
            return
        self._edit_preview=item
        shape = self.shape_items.get(original['id'])
        label = self.caption_items.get(original['id'])
        if shape is not None:
            path,label_xy = self.shape_path(item)
            shape.setPath(path)
            if label is not None:
                label.setPos(*label_xy)
                label.setText(caption(item,self.calibration()))
        for handle in self.edit_handles:
            if handle.annotation_id == item['id']:
                pos = self.edit_handle_positions(item).get(handle.role)
                if pos is not None: handle.setPos(*pos)

    def commit_geometry_edit(self, original):
        updated = self._edit_preview
        self._edit_preview = None
        if updated is not None and updated != original:
            self.replace_annotation(updated)
        else:
            self.redraw_measurements()

    def replace_annotation(self, new):
        new = validate_annotation(new)
        key = self.active_annotation_key()
        if key is None:
            return
        before = copy.deepcopy(self.visible_annotations())
        if not any(a['id']==new['id'] for a in before):
            return
        after = [new if a['id']==new['id'] else a for a in before]
        if before==after:
            return
        self.annotations_by_image[key]=after
        self.selected_annotation_id=new['id']
        self.redraw_measurements()
        self.update_profile()
        if self.parent_window:
            self.parent_window.record_annotation_change(self,key,before,after,action='Edited',item=new)

    def redraw_measurements(self):
        self.clear_edit_handles()
        self.shape_items.clear();self.caption_items.clear()
        for obj in self.measurement_graphics:
            try: self.plot.removeItem(obj)
            except (RuntimeError, ValueError): pass
        self.measurement_graphics = []
        if self.preview_item is not None:
            try: self.plot.removeItem(self.preview_item)
            except (RuntimeError, ValueError): pass
            self.preview_item=None
        if self.current is None:
            self.update_roi_selector()
            return
        for item in self.visible_annotations():
            path,label = self.shape_path(item)
            shape = MeasurePathItem(self,item['id'],path)
            # Cosmetic pen stays visibly thin even when image zoom changes.
            shape.setPen(pg.mkPen('#35e2ff' if item['type']!='count' else '#ff6f69',width=2))
            shape.setZValue(20)
            shape.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
            self.plot.addItem(shape)
            self.measurement_graphics.append(shape)
            self.shape_items[item['id']] = shape
            text = pg.TextItem(caption(item,self.calibration()),color='#ffffff' if item['type']!='count' else '#ff6f69',anchor=(0,1))
            text.setPos(*label)
            text.setZValue(21)
            text.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
            self.plot.addItem(text)
            self.measurement_graphics.append(text)
            self.caption_items[item['id']] = text
        self.update_roi_selector()
        self.update_annotation_styles()

    def update_annotation_styles(self):
        for obj in self.measurement_graphics:
            if isinstance(obj, MeasurePathItem):
                selected = obj.annotation_id == self.selected_annotation_id
                pen = pg.mkPen('#ffcf44' if selected else '#ff6f69' if
                               any(x['id']==obj.annotation_id and x['type']=='count'
                                   for x in self.visible_annotations()) else '#35e2ff',
                               width=3 if selected else 2)
                obj.setPen(pen)
                obj.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.refresh_edit_handles()

    def tool_changed(self):
        self.update_annotation_styles()
        self.update_profile_roi_visibility()

    def update_profile_roi_visibility(self):
        active = (self.profile_active and self.parent_window is not None and
                  self.parent_window.profile_source.currentData() == 'line' and
                  self.annotation_tool() == 'pan')
        if self.roi is not None:
            self.roi.setVisible(active)
        if self.width_overlay is not None:
            self.width_overlay.setVisible(active and self.parent_window.profile_width.value()>1)

    def update_preview(self, kind, start, end):
        if self.preview_item is None:
            self.preview_item=QtWidgets.QGraphicsPathItem()
            pen=pg.mkPen('#ffdb78',width=2,style=QtCore.Qt.PenStyle.DashLine)
            self.preview_item.setPen(pen)
            self.preview_item.setZValue(30)
            self.preview_item.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
            self.plot.addItem(self.preview_item)
        try:
            data=create_annotation(kind,start,end,identifier='preview')
            path,_=self.shape_path(data)
        except ValueError:
            path=QtGui.QPainterPath()
        self.preview_item.setPath(path)

    def annotation_drag(self, start, end, finished, constrain=False):
        kind=self.annotation_tool()
        if self.current is None or self.loading:return
        h,w=self.current.shape
        if not (0 <= start[0] < w and 0 <= start[1] < h):
            return
        end=(min(max(end[0],0),w-1),min(max(end[1],0),h-1))
        if constrain:
            if kind=='line':
                end=tuple(snap_endpoint(start,end,self.current.shape))
            elif kind in ('rect','ellipse'):
                dx,dy=end[0]-start[0],end[1]-start[1]
                side=min(abs(dx),abs(dy))
                end=(start[0]+math.copysign(side,dx),start[1]+math.copysign(side,dy))
        if not finished:
            self.update_preview(kind,start,end)
            return
        if self.preview_item is not None:
            self.plot.removeItem(self.preview_item)
            self.preview_item=None
        if self.current is None or self.loading:
            return
        try:
            item=create_annotation(kind,start,end,identifier=uuid.uuid4().hex)
        except ValueError:
            return
        self.add_annotation(item)

    def add_count(self, point):
        if self.current is None or self.loading:
            return
        x,y=point;h,w=self.current.shape
        if not (0 <= x < w and 0 <= y < h):
            return
        nums=[item['number'] for item in self.visible_annotations() if item['type']=='count']
        number=max(nums,default=0)+1
        self.add_annotation(create_annotation('count',point,number=number,identifier=uuid.uuid4().hex))

    def add_annotation(self, item):
        key=self.active_annotation_key()
        if key is None:return
        before=copy.deepcopy(self.visible_annotations())
        after=before+[validate_annotation(item)]
        if len(after)>2000:
            self.status.setText('Too many ROIs on this slice (2000 limit)')
            return
        self.annotations_by_image[key]=after
        self.selected_annotation_id=item['id']
        self.redraw_measurements()
        self.update_profile()
        if self.parent_window:
            self.parent_window.record_annotation_change(self,key,before,after,action='Created',item=item)

    def delete_selected_annotation(self):
        key=self.active_annotation_key()
        if key is None or self.selected_annotation_id is None:return
        before=copy.deepcopy(self.visible_annotations())
        after=[a for a in before if a['id']!=self.selected_annotation_id]
        if len(after)==len(before):return
        self.annotations_by_image[key]=after
        self.selected_annotation_id=None
        self.redraw_measurements()
        self.update_profile()
        if self.parent_window:self.parent_window.record_annotation_change(self,key,before,after)

    def clear_visible_annotations(self):
        key=self.active_annotation_key()
        if key is None or not self.visible_annotations():return
        before=copy.deepcopy(self.visible_annotations())
        self.annotations_by_image[key]=[]
        self.selected_annotation_id=None
        self.redraw_measurements()
        self.update_profile()
        if self.parent_window:self.parent_window.record_annotation_change(self,key,before,[])

    def apply_annotations_from_history(self,key,items):
        self.annotations_by_image[key]=copy.deepcopy(items)
        if key==self.active_annotation_key():
            self.selected_annotation_id=None
            self.redraw_measurements()
            self.update_profile()

    def selected_rectangle(self):
        entries=self.visible_annotations()
        for item in entries:
            if item['id']==self.selected_annotation_id and item['type']=='rect':return item
        # If nothing is selected, default to the last rectangle in this slice.
        return next((x for x in reversed(entries) if x['type']=='rect'),None)

    def profile_export_record(self):
        if self._profile_data is None or self.current is None or self.current_path is None:
            return None
        d,v,x,y,kind,width,line=self._profile_data
        return {'side':self.display_name,'path':self.current_path,
                'slice':self.index.value(),'width':width,'line':line,
                'profile':(d,v),'coords':(x,y),'kind':kind}

    def ensure_roi(self):
        if self.roi is not None or self.current is None:
            return
        h, w = self.current.shape
        self.roi = pg.LineSegmentROI([[w*0.25, h*0.5], [w*0.75, h*0.5]],
                                     pen=pg.mkPen('#ffb200', width=2))
        self._previous_profile_line = ((w*0.25,h*0.5),(w*0.75,h*0.5))
        self.width_overlay = QtWidgets.QGraphicsPolygonItem()
        self.width_overlay.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.width_overlay.setBrush(QtGui.QBrush(QtGui.QColor(255, 185, 0, 90)))
        self.roi.setZValue(11)
        self.width_overlay.setZValue(10)
        self.plot.addItem(self.width_overlay)
        self.plot.addItem(self.roi)
        self.roi.setVisible(self.profile_active)
        self.update_width_overlay()
        self.roi.sigRegionChanged.connect(self.roi_changed)

    def roi_changed(self, *_):
        # Existing LineSegmentROI is independent of the measurement Line tool.
        # Apply Shift snapping to whichever endpoint moved, in TIFF coordinates.
        current=self.get_line()
        previous=getattr(self,'_previous_profile_line',None)
        if (current and previous and self.current is not None and
                QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier):
            d0=math.dist(current[0],previous[0]);d1=math.dist(current[1],previous[1])
            if d0>1e-8 or d1>1e-8:
                moved=0 if d0>=d1 else 1
                stable=1-moved
                snapped=snap_endpoint(current[stable],current[moved],self.current.shape)
                changed=list(current);changed[moved]=snapped
                self.set_line(changed)
                current=self.get_line()
        self._previous_profile_line=current
        self.update_width_overlay()
        self.update_profile()
        if self.on_profile_change is not None and self.roi is not None:
            self.on_profile_change(self)

    def update_width_overlay(self):
        """Show the actual sampled strip in source-image pixel coordinates."""
        if self.width_overlay is None or self.roi is None:
            return
        (x0, y0), (x1, y1) = self.get_line()
        dx, dy = x1-x0, y1-y0
        length = float(np.hypot(dx, dy))
        nx, ny = (-dy/length, dx/length) if length else (0.0, 1.0)
        width = self.parent_window.profile_width.value() if self.parent_window else 1
        # The sampling centers span width-1 px; give them half-pixel outer edges.
        half = width / 2.0
        points = [(x0 + nx*half, y0 + ny*half),
                  (x1 + nx*half, y1 + ny*half),
                  (x1 - nx*half, y1 - ny*half),
                  (x0 - nx*half, y0 - ny*half)]
        polygon = QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in points])
        self.width_overlay.setPolygon(polygon)
        self.width_overlay.setVisible(self.profile_active and width > 1 and
            self.parent_window.profile_source.currentData() == 'line' and self.annotation_tool() == 'pan')

    def get_line(self):
        return roi_endpoints(self.roi) if self.roi is not None else None

    def set_line(self, endpoints):
        if self.roi is None or endpoints is None:
            return
        # LineSegmentROI has no portable setPoints() API in pyqtgraph 0.13.
        # Set handle positions in the image's parent coordinates instead.
        self.roi.blockSignals(True)
        try:
            handles = self.roi.getHandles()
            for handle, xy in zip(handles[:2], endpoints):
                self.roi.movePoint(handle, pg.Point(float(xy[0]), float(xy[1])),
                                   coords='parent')
        finally:
            self.roi.blockSignals(False)
        self._previous_profile_line=self.get_line()
        self.update_width_overlay()
        self.update_profile()

    def update_profile(self):
        if not self.profile_active or self.current is None or self.parent_window is None:
            self._profile_data=None
            return
        try:
            kind=self.parent_window.profile_source.currentData()
            if kind=='line':
                if self.roi is None:return
                start,end=self.get_line()
                dist, vals=sample_thick_line(self.current,start,end,
                    width=self.parent_window.profile_width.value(),aggregation='mean')
                n=len(dist)
                xx=np.linspace(start[0],end[0],n)
                yy=np.linspace(start[1],end[1],n)
                self._profile_data=(dist,vals,xx,yy,'mean',
                                    self.parent_window.profile_width.value(),(start,end))
                self.profile_plot.setLabel('left','Mean intensity')
            else:
                rect=self.selected_rectangle()
                if rect is None:
                    self._profile_data=None
                    self._last_profile=None
                    self.profile_curve.setData([],[])
                    self.status.setText('Draw a rectangle (Rectangle tool) to calculate mean profile')
                    return
                axis='x' if kind=='rect_x' else 'y'
                dist,vals,xx,yy=rotated_rect_mean_profile(self.current,rect,axis)
                thickness=rect['rect'][3] if axis=='x' else rect['rect'][2]
                self._profile_data=(dist,vals,xx,yy,'rect_mean_'+axis,thickness,None)
                self.profile_plot.setLabel('left','Rectangle mean intensity')
            self.profile_curve.setData(dist, vals)
            finite=vals[np.isfinite(vals)]
            self._last_profile=(float(finite.min()),float(finite.max())) if finite.size else None
            self.parent_window.refresh_y_axes()
        except Exception as e:
            self.status.setText('Profile error: '+str(e))

    def set_profile_active(self, active):
        self.profile_active = active
        self.profile_plot.setVisible(active)
        if active:
            QtCore.QTimer.singleShot(0, lambda: self.image_profile_splitter.setSizes(
                [max(260, self.image_profile_splitter.height()-120), 120]))
            self.ensure_roi()
            self.update_profile()
        self.update_profile_roi_visibility()

    def _profile_range_changed(self, viewbox, ranges):
        if self.parent_window is not None:
            self.parent_window.profile_range_changed(self, ranges)

    def _view_range_changed(self, viewbox, ranges):
        self.update_scale_bar()
        if self.parent_window is not None:
            self.parent_window.view_changed(self, ranges)

    def _mouse_moved(self, scene_pos):
        if self.parent_window is not None and self.plot.sceneBoundingRect().contains(scene_pos):
            self.parent_window.set_active_panel(self)
        if self.current is None or not self.plot.sceneBoundingRect().contains(scene_pos):
            self.cursor_label.setText('Cursor: — | Intensity: —')
            return
        xy = self.plot.getViewBox().mapSceneToView(scene_pos)
        x, y = int(np.floor(xy.x())), int(np.floor(xy.y()))
        h, w = self.current.shape
        if 0 <= x < w and 0 <= y < h:
            val = self.current[y, x]
            intensity = str(int(val)) if np.issubdtype(self.current.dtype, np.integer) else f'{float(val):.7g}'
            self.cursor_label.setText(f'X: {x} px   Y: {y} px   Intensity: {intensity} ({self.current.dtype})')
        else:
            self.cursor_label.setText('Cursor: outside image | Intensity: —')

    def fit_view(self):
        if self.current is not None:
            h,w=self.current.shape
            self.plot.getViewBox().setRange(xRange=(0,w),yRange=(0,h),padding=0.02)
            self.plot.getViewBox().disableAutoRange()

    @QtCore.Slot(int, str)
    def on_error(self, token, message):
        if token == self.token:
            self.loading=False
            self._pending_restore=None
            logger().error('Image load failed | panel=%s error=%s',self.objectName(),message)
            self.status.setText('Error: ' + message)

    def set_manual_levels(self, low, high):
        if self.current is None or not (math.isfinite(low) and math.isfinite(high) and high>low):
            return
        for control,val in ((self.lo,low),(self.hi,high)):
            control.blockSignals(True);control.setValue(float(val));control.blockSignals(False)
        self.auto.blockSignals(True);self.auto.setChecked(False);self.auto.blockSignals(False)
        self.auto_button.setChecked(False)
        self.refresh_levels()

    def enable_auto_contrast(self):
        """One-click automatic contrast; also keeps auto mode for subsequent slices."""
        if self.current is None:
            return
        self.auto.setChecked(True)
        self.auto_button.setChecked(True)
        self.refresh_levels()
        log_action('Auto Contrast', view=self.display_name,
                   file=Path(self.current_path).name if self.current_path else '')

    def reset_contrast(self):
        if self.current is None:return
        data=np.asarray(self.current)
        finite=data[np.isfinite(data)]
        if finite.size:
            lo=float(finite.min());hi=float(finite.max())
            if hi <= lo:hi=lo+1.0
            self.set_manual_levels(lo,hi)

    def open_levels_dialog(self):
        if self.current is None:
            QtWidgets.QMessageBox.information(self,'Levels','Open a TIFF image first.')
            return
        dialog=ContrastDialog(self,self)
        dialog.exec()

    def refresh_levels(self, *_):
        if self.current is None:
            return
        if self.auto.isChecked():
            # The cached percentile limits are per-TIFF and are reused on zoom,
            # slice redraw, and UI signals (large 4k float TIFFs are expensive).
            low, high = getattr(self, '_auto_levels', None) or display_limits(self.current)
            for spin, value in ((self.lo, low), (self.hi, high)):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
        else:
            low, high = self.lo.value(), self.hi.value()
        if high > low:
            self.image.setLevels((low, high))

class ContrastDialog(QtWidgets.QDialog):
    """Live contrast editor; modifies ONLY ImageItem levels, never TIFF intensities."""
    def __init__(self, panel, parent):
        super().__init__(parent)
        self.panel=panel
        self.setWindowTitle(f'{panel.display_name} — Window / Level')
        self.resize(550,430)
        self._changing=False
        samples=np.asarray(panel.current).ravel()[::max(1,panel.current.size//200000)]
        finite=samples[np.isfinite(samples)]
        if not finite.size: finite=np.array([0.,1.])
        self.raw_min=float(np.min(finite));self.raw_max=float(np.max(finite))
        if not self.raw_max>self.raw_min:self.raw_max=self.raw_min+1.
        self.span=self.raw_max-self.raw_min
        root=QtWidgets.QVBoxLayout(self)
        hint=QtWidgets.QLabel('Drag the histogram handles or change Window (contrast) and Level (brightness).')
        hint.setWordWrap(True);root.addWidget(hint)
        self.histogram=pg.PlotWidget()
        self.histogram.setMinimumHeight(170)
        data, edges=np.histogram(finite.astype(float),bins=160,range=(self.raw_min,self.raw_max))
        self.histogram.plot(edges[:-1], data, stepMode='left', fillLevel=0,
                            brush=pg.mkBrush('#36536e88'),pen=pg.mkPen('#87a5c0'))
        self.region=pg.LinearRegionItem(values=(float(panel.lo.value()),float(panel.hi.value())),
                         brush=pg.mkBrush('#518dbb44'), pen=pg.mkPen('#d6e7fa'))
        self.histogram.addItem(self.region)
        self.region.sigRegionChanged.connect(self._from_region)
        root.addWidget(self.histogram)
        rows=QtWidgets.QFormLayout()
        self.window=QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.window.setRange(1,1000)
        self.level=QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.level.setRange(0,1000)
        rows.addRow('Window',self.window);rows.addRow('Level',self.level)
        root.addLayout(rows)
        numerical=QtWidgets.QHBoxLayout()
        self.minbox=QtWidgets.QDoubleSpinBox();self.maxbox=QtWidgets.QDoubleSpinBox()
        for box in (self.minbox,self.maxbox):
            box.setDecimals(6);box.setRange(-1e30,1e30)
        numerical.addWidget(QtWidgets.QLabel('Min'));numerical.addWidget(self.minbox)
        numerical.addWidget(QtWidgets.QLabel('Max'));numerical.addWidget(self.maxbox)
        root.addLayout(numerical)
        btns=QtWidgets.QHBoxLayout()
        auto=QtWidgets.QPushButton('Auto');auto.clicked.connect(self._auto)
        full=QtWidgets.QPushButton('Reset (Full)');full.clicked.connect(self._full)
        close=QtWidgets.QPushButton('Close');close.clicked.connect(self.accept)
        btns.addWidget(auto);btns.addWidget(full);btns.addStretch(1);btns.addWidget(close)
        root.addLayout(btns)
        self.window.valueChanged.connect(self._from_sliders)
        self.level.valueChanged.connect(self._from_sliders)
        self.minbox.valueChanged.connect(self._from_numbers)
        self.maxbox.valueChanged.connect(self._from_numbers)
        self._set(float(panel.lo.value()),float(panel.hi.value()),emit=False)

    def _set(self,lo,hi,emit=True):
        if self._changing or not (math.isfinite(lo) and math.isfinite(hi)):return
        self._changing=True
        try:
            lo=max(-1e30,min(1e30,lo));hi=max(-1e30,min(1e30,hi))
            if hi<=lo:hi=lo+max(1e-10,self.span*1e-6)
            for box,val in ((self.minbox,lo),(self.maxbox,hi)):
                with QtCore.QSignalBlocker(box):box.setValue(val)
            center=(lo+hi)/2
            w=max(1,min(1000,round((hi-lo)/self.span*1000)))
            lv=max(0,min(1000,round((center-self.raw_min)/self.span*1000)))
            for slider,val in ((self.window,w),(self.level,lv)):
                with QtCore.QSignalBlocker(slider):slider.setValue(val)
            self.region.setRegion((lo,hi))
            if emit:self.panel.set_manual_levels(lo,hi)
        finally:self._changing=False

    def _from_region(self):
        if not self._changing:self._set(*self.region.getRegion())

    def _from_sliders(self):
        if self._changing:return
        width=self.span*self.window.value()/1000
        center=self.raw_min+self.span*self.level.value()/1000
        self._set(center-width/2,center+width/2)

    def _from_numbers(self):
        if not self._changing:self._set(self.minbox.value(),self.maxbox.value())

    def _auto(self):
        # Unlike a one-time numerical preset, Auto should continue to apply
        # to subsequent slices until the user adjusts Window/Level manually.
        self.panel.auto.setChecked(True)
        self.panel.refresh_levels()
        self._set(float(self.panel.lo.value()),float(self.panel.hi.value()),emit=False)

    def _full(self):
        self._set(self.raw_min,self.raw_max)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, instance_number=1, new_window_callback=None):
        super().__init__()
        self.instance_number=instance_number
        self.window_session_id=uuid.uuid4().hex[:12]
        self._new_window_callback=new_window_callback
        self.setWindowTitle(f'LOUPE v{VERSION} ({APP_STATUS}) — Multi-view comparison')
        self.setWindowIcon(QtGui.QIcon(str(icon_path())))
        self.resize(1440, 970)
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.panels = [ImagePanel(name, self.pool) for name in
                       ('VIEW 1', 'VIEW 2', 'VIEW 3', 'VIEW 4')]
        self.left, self.right = self.panels[:2]  # preserve v1.2/v1.3 aliases
        for panel in self.panels:
            panel.parent_window = self
            panel.setObjectName(('LEFT','RIGHT','THIRD','FOURTH')[self.panels.index(panel)])
            panel.on_profile_change = self.line_changed
        self.panel_count = 2
        self.panel_grid = QtWidgets.QGridLayout()
        self.panel_grid.setSpacing(5)
        self.panel_grid.setContentsMargins(3,3,3,3)
        self.panel_container = QtWidgets.QWidget()
        self.panel_container.setLayout(self.panel_grid)
        self._syncing = False
        self._syncing_view = False
        self._syncing_profile_y = False
        self._setting_profile_ranges = False
        self._syncing_slices = False
        self._active_panel = self.left
        self._keyboard_shortcuts = []
        self.space_pan_active = False
        self.undo_stack = []
        self.redo_stack = []
        self.last_report_title = 'LOUPE'
        self.last_report_comment = ''
        self.bookmarks = []
        self._imagej_child = None
        self.profile_mode = QtWidgets.QCheckBox('Profile mode')
        self.profile_mode.setChecked(False)
        self.profile_mode.toggled.connect(self.toggle_profile)
        self.link_view = QtWidgets.QCheckBox('Linked view (zoom / pan)')
        self.link_view.setChecked(False)
        self.link_view.toggled.connect(self.link_view_toggled)
        self.link_line = QtWidgets.QCheckBox('Linked line position')
        self.link_line.setChecked(False)
        self.link_line.toggled.connect(self.link_line_toggled)
        self.link_y = QtWidgets.QCheckBox('Linked profiles')
        self.link_y.setChecked(False)
        self.link_y.toggled.connect(self.link_y_toggled)
        self.link_slices = QtWidgets.QCheckBox('Linked slices')
        self.link_slices.setToolTip('Keep the same 1-based slice number across loaded visible image sequences')
        self.link_slices.toggled.connect(self.link_slices_toggled)
        for panel in self.panels:
            panel.index.valueChanged.connect(lambda number, p=panel:self.slice_index_changed(p, number))
        # Compact responsive toolbar. Primary and export actions occupy the same
        # row, avoiding the unused tall space that displaced image panels.
        central = QtWidgets.QWidget()
        central_layout = QtWidgets.QVBoxLayout(central)
        central_layout.setContentsMargins(5, 2, 5, 2)
        central_layout.setSpacing(2)
        toolbar = QtWidgets.QWidget()
        toolbar_layout = QtWidgets.QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(3, 0, 3, 0)
        toolbar_layout.setSpacing(2)
        self.primary_toolbar_row = QtWidgets.QHBoxLayout()
        self.primary_toolbar_row.setSpacing(5)
        toolbar_layout.addLayout(self.primary_toolbar_row)
        self.primary_toolbar_row.addWidget(QtWidgets.QLabel('Measure / Count'))
        self.annotation_tool=QtWidgets.QComboBox()
        for label,data in [('Line (px)','line'),('Rectangle (px)','rect'),
                           ('Ellipse / Circle (px)','ellipse'),('Count 1, 2, 3…','count')]:
            self.annotation_tool.addItem(label,data)
        self.annotation_tool.setToolTip('Draw on empty image; drag existing shape or yellow handles to edit. Shift: constrain. Space+drag: pan.')
        self.annotation_tool.insertItem(0,'Select ROI tool…','pan')
        self.annotation_tool.setCurrentIndex(0)
        self.pan_button=QtWidgets.QPushButton('Pan / Zoom')
        self.pan_button.setCheckable(True)
        self.pan_button.setChecked(True)
        self.pan_button.clicked.connect(self.select_pan_tool)
        self.primary_toolbar_row.addWidget(self.pan_button)
        self.annotation_tool.currentIndexChanged.connect(self.annotation_tool_changed)
        self.annotation_tool.setMinimumWidth(max(160,
            max(self.annotation_tool.fontMetrics().horizontalAdvance(self.annotation_tool.itemText(i))
                for i in range(self.annotation_tool.count())) + 44))
        self.primary_toolbar_row.addWidget(self.annotation_tool)
        self.primary_toolbar_row.addSpacing(5)
        self.primary_toolbar_row.addWidget(QtWidgets.QLabel('Views'))
        self.view_count=QtWidgets.QComboBox()
        for count in range(1,MAX_PANELS+1):
            self.view_count.addItem(str(count),count)
        self.view_count.setCurrentIndex(1)
        self.view_count.setToolTip('Show 1, 2, 3 or 4 independent image comparison panels')
        self.view_count.currentIndexChanged.connect(self.change_panel_count)
        self.primary_toolbar_row.addWidget(self.view_count)
        self.primary_toolbar_row.addSpacing(5)
        self.primary_toolbar_row.addStretch(1)

        # Actions remain ordinary methods; group them by user purpose.
        self.session_button=QtWidgets.QToolButton()
        self.session_button.setText('Session ▾')
        self.session_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        sm=QtWidgets.QMenu(self.session_button)
        sm.addAction('Save Session…').triggered.connect(self.save_json)
        sm.addAction('Open Session…').triggered.connect(self.load_json)
        self.session_button.setMenu(sm)
        self.session_button.setToolTip('Save/open view layout, source image references and ROI settings (not image pixels)')
        self.report_button=QtWidgets.QToolButton()
        self.report_button.setText('Report ▾')
        self.report_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        rm=QtWidgets.QMenu(self.report_button)
        rm.addAction('PNG…').triggered.connect(self.export_report_png)
        rm.addAction('PDF…').triggered.connect(self.export_report_pdf)
        self.report_button.setMenu(rm)
        self.export_menu_button=QtWidgets.QToolButton()
        self.export_menu_button.setText('Export ▾')
        self.export_menu_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        em=QtWidgets.QMenu(self.export_menu_button)
        em.addAction('Profile Data (CSV)…').triggered.connect(self.export_csv)
        em.addAction('ROI Measurements (CSV)…').triggered.connect(self.export_measurements)
        self.export_menu_button.setMenu(em)
        for button in (self.session_button,self.report_button,self.export_menu_button):
            self.primary_toolbar_row.addWidget(button)

        # Second compact row contains editing, profile controls and linked
        # actions. At narrow window sizes only the links wrap onto a third row.
        self.secondary_toolbar_row=QtWidgets.QHBoxLayout()
        self.secondary_toolbar_row.setSpacing(4)
        toolbar_layout.addLayout(self.secondary_toolbar_row)
        self.undo_button=QtWidgets.QPushButton('Undo')
        self.redo_button=QtWidgets.QPushButton('Redo')
        self.undo_button.clicked.connect(self.undo_measurement)
        self.redo_button.clicked.connect(self.redo_measurement)
        self.secondary_toolbar_row.addWidget(self.undo_button)
        self.secondary_toolbar_row.addWidget(self.redo_button)
        self.clear_slice_button=QtWidgets.QPushButton('Clear current slice…')
        self.clear_slice_button.setToolTip('Clear only annotations of the currently selected image panel and slice')
        self.clear_slice_button.clicked.connect(self.clear_current_slice)
        self.secondary_toolbar_row.addWidget(self.clear_slice_button)
        self.secondary_toolbar_row.addSpacing(8)
        self.secondary_toolbar_row.addWidget(self.profile_mode)
        self.width_label=QtWidgets.QLabel('Line width (px)')
        self.profile_width=QtWidgets.QSpinBox()
        self.profile_width.setRange(1,101)
        self.profile_width.setValue(1)
        self.profile_width.setToolTip('Width in original pixels; 1 = centerline intensity')
        self.secondary_toolbar_row.addWidget(self.width_label)
        self.secondary_toolbar_row.addWidget(self.profile_width)
        self.profile_source=QtWidgets.QComboBox()
        self.profile_source.addItem('Line profile','line')
        self.profile_source.setToolTip('Line profile from native image intensity values')
        self.profile_source.currentIndexChanged.connect(self.profile_settings_changed)
        self.profile_width.valueChanged.connect(self.profile_settings_changed)
        self.width_label.setVisible(False)
        self.profile_width.setVisible(False)
        # No selector UI: only Line profile exists. Keep model object for
        # older saved session compatibility without a redundant dropdown.
        self.secondary_toolbar_row.addStretch(1)
        self.link_toolbar_row=QtWidgets.QHBoxLayout()
        self.link_toolbar_row.setSpacing(6)
        toolbar_layout.addLayout(self.link_toolbar_row)
        for checkbox in (self.link_slices,self.link_view,self.link_line,self.link_y):
            self.link_toolbar_row.addWidget(checkbox)
        self.link_toolbar_row.addStretch(1)
        self._links_wrapped=True
        central_layout.addWidget(toolbar)
        self.update_undo_buttons()
        central_layout.addWidget(self.panel_container, 1)
        self.apply_panel_layout()
        self.setCentralWidget(central)
        self.statusBar().showMessage(f'LOUPE v{VERSION} — {APP_STATUS} | 1–4 horizontal views')
        file_menu=self.menuBar().addMenu('File')
        self.new_window_action=file_menu.addAction('New Window')
        self.new_window_action.setShortcut(QtGui.QKeySequence('Ctrl+N'))
        self.new_window_action.triggered.connect(self.open_new_window)
        # Native shortcut rendering reserves its own column; enforce enough
        # width even under Windows 125–150% text scaling.
        fm=file_menu.fontMetrics()
        file_menu.setMinimumWidth(max(255, fm.horizontalAdvance('New Window')
                                      +fm.horizontalAdvance('Ctrl+N')+100))
        file_menu.addSeparator()
        file_menu.addAction('Close Window').triggered.connect(self.close)
        imagej_menu=self.menuBar().addMenu('ImageJ/Fiji')
        imagej_menu.addAction('Configure ImageJ/Fiji…').triggered.connect(self.configure_imagej)
        imagej_menu.addAction('ImageJ/Fiji Connection Check…').triggered.connect(self.fiji_relay_setup)
        imagej_menu.addAction('Open Current Image in ImageJ/Fiji…').triggered.connect(self.open_imagej_current)
        imagej_stack_action=imagej_menu.addAction('Open Stack in ImageJ/Fiji…')
        imagej_stack_action.setStatusTip('TIFF/IMG stack with slice-range and RAM preflight')
        imagej_stack_action.triggered.connect(self.open_imagej_stack)
        actions=self.menuBar().addMenu('Compare / Tools')
        actions.addAction('Copy Comparison Image').triggered.connect(self.copy_comparison)
        actions.addAction('Overlay Profiles…').triggered.connect(self.overlay_profiles)
        actions.addAction('Copy Selected ROI to Another View…').triggered.connect(self.copy_roi_to_view)
        actions.addAction('Orthogonal View (Preview)…').triggered.connect(self.open_orthogonal_view)
        marks=self.menuBar().addMenu('Bookmarks')
        marks.addAction('Add Current Slice…').triggered.connect(self.add_bookmark)
        marks.addAction('Go to Bookmark…').triggered.connect(self.goto_bookmark)
        menu=self.menuBar().addMenu('Help')
        report_action=menu.addAction('Export Bug Report…')
        report_action.triggered.connect(self.export_bug_report)
        menu.addAction('Open Log Folder…').triggered.connect(self.open_log_folder)
        menu.addSeparator()
        menu.addAction('About LOUPE…').triggered.connect(self.show_about_dialog)
        QtWidgets.QApplication.instance().installEventFilter(self)
        for key,step in ((QtCore.Qt.Key.Key_Left,-1),(QtCore.Qt.Key.Key_Right,1)):
            shortcut=QtGui.QShortcut(QtGui.QKeySequence(key),self)
            shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda step=step:self.keyboard_step_slice(step))
            self._keyboard_shortcuts.append(shortcut)
        QtWidgets.QApplication.instance().focusChanged.connect(self._shortcut_focus_changed)
        self._shortcut_focus_changed(None, QtWidgets.QApplication.focusWidget())

    def open_new_window(self):
        if self._new_window_callback is None:
            QtWidgets.QMessageBox.warning(self,'New Window unavailable',
                'Please start LOUPE using main.py or run.bat to enable multiple windows.')
            return
        self._new_window_callback()

    @staticmethod
    def _build_jst(value):
        from datetime import datetime, timedelta, timezone
        try:
            dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
            if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S JST')
        except (ValueError, TypeError):return 'unrecorded'

    def show_about_dialog(self):
        """Show software and display theme versions without affecting image state."""
        build = build_info()
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle('About LOUPE')
        msg.setWindowIcon(QtGui.QIcon(str(icon_path())))
        msg.setIconPixmap(QtGui.QPixmap(str(icon_path())).scaled(
            128,128, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.FastTransformation))
        msg.setText(f'<b>LOUPE</b><br><span style="color:#9aa8b8">Version {VERSION} · {APP_STATUS}</span>')
        msg.setInformativeText(
            'Photon Science Innovation Center (PhoSIC)\n'
            f'UI Standard v{UI_STANDARD_VERSION}\n'
            f'Build JST: {self._build_jst(build["build_utc"])}\n'
            f'Git Commit: {build["git_commit"]}\n\n'
            '1–4 VIEW image comparison · TIFF / IMG\n'
            'ROI measurements, line profiles and counting\n'
            'Orthogonal Preview / Native Section · Fiji integration\n'
            'PNG / PDF reports and quantitative TIFF export')
        msg.exec()

    def eventFilter(self, watched, event):
        # With multiple windows the Qt application sends events to every
        # installed filter. A background comparison must never consume an
        # active window's keyboard/Pan events.
        active=QtWidgets.QApplication.activeWindow()
        if active is not self:
            return super().eventFilter(watched,event)
        # Space is a temporary Pan modifier; leave focused text/spin controls alone.
        t=event.type()
        if t in (QtCore.QEvent.Type.KeyPress,QtCore.QEvent.Type.KeyRelease):
            if event.key()==QtCore.Qt.Key.Key_Space and not event.isAutoRepeat():
                focus=QtWidgets.QApplication.focusWidget()
                editing=isinstance(focus,(QtWidgets.QAbstractSpinBox,QtWidgets.QComboBox,
                    QtWidgets.QLineEdit,QtWidgets.QTextEdit,QtWidgets.QPlainTextEdit,
                    QtWidgets.QPushButton,QtWidgets.QCheckBox))
                if not editing:
                    self.space_pan_active=t==QtCore.QEvent.Type.KeyPress
                    return True
                if t==QtCore.QEvent.Type.KeyRelease:self.space_pan_active=False
        return super().eventFilter(watched,event)

    def visible_panels(self):
        return self.panels[:self.panel_count]

    def _update_panel_density(self):
        density = density_for_window(self.panel_count, max(1, self.width()))
        for panel in self.panels:
            panel.set_compact_mode(density != 'normal', density == 'ultra')

    def _set_toolbar_compact(self, wrapped):
        """All linked controls stay together in a single row at any width."""
        self._links_wrapped=True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'panels') and hasattr(self, 'panel_container'):
            self._update_panel_density()
            self._set_toolbar_compact(event.size().width() < 1450)

    def apply_panel_layout(self):
        # All 1–4 images occupy a single horizontal row. Each column has the
        # same stretch, so no horizontal QScrollArea is needed/created.
        for panel in self.panels:
            self.panel_grid.removeWidget(panel)
            panel.hide()
        self._update_panel_density()
        for (row,col),panel in zip(horizontal_cells(self.panel_count),self.visible_panels()):
            self.panel_grid.addWidget(panel,row,col)
            panel.show()
        for col in range(MAX_PANELS):
            self.panel_grid.setColumnStretch(col,1 if col < self.panel_count else 0)
            self.panel_grid.setColumnMinimumWidth(col,0)
        self.panel_grid.setRowStretch(0,1)
        self.panel_grid.setRowStretch(1,0)
        if self._active_panel not in self.visible_panels():
            self._active_panel=self.visible_panels()[0]

    def change_panel_count(self, *_):
        count=int(self.view_count.currentData())
        if count==self.panel_count:return
        # Hidden panels preserve loaded data and annotations, including Undo/Redo.
        self.panel_count=count
        self.apply_panel_layout()
        for panel in self.visible_panels():
            panel.redraw_measurements()
            panel.update_profile()
        self.refresh_y_axes()
        log_action('Comparison panel count changed',count=count)

    def open_dropped_paths(self, start_panel, paths):
        try:
            target_indices=panel_indices_for_drop(self.panels.index(start_panel), len(paths), MAX_PANELS)
            required=max(self.panel_count,max(target_indices)+1)
            if required>self.panel_count:
                self.view_count.setCurrentIndex(required-1)
            for i,path in zip(target_indices,paths):
                self.panels[i].open_path(path)
            self.set_active_panel(start_panel)
            self.statusBar().showMessage(f'Opened {len(paths)} dropped image dataset(s)',7000)
            log_action('Image drag-and-drop',datasets=len(paths),panels=','.join(self.panels[i].objectName() for i in target_indices))
        except (ValueError,IndexError) as exc:
            self.report_error('Image drop failed',exc)

    def calibration(self, panel=None):
        # Compatibility for external integrations; the authoritative data
        # live in each ImagePanel.snapshot()['calibration'].
        return (panel or self._active_panel).calibration()

    def _shortcut_focus_changed(self, old, new):
        # Keep normal arrow-key editing in spin boxes, text fields and combos.
        editing=isinstance(new,(QtWidgets.QAbstractSpinBox,QtWidgets.QComboBox,
                   QtWidgets.QLineEdit,QtWidgets.QTextEdit,QtWidgets.QPlainTextEdit))
        owns_focus=(new is None or new.window() is self)
        for shortcut in self._keyboard_shortcuts:
            shortcut.setEnabled(owns_focus and not editing)

    def state(self):
        return {'settings':{'profile_mode':self.profile_mode.isChecked(),
                            'width_px':self.profile_width.value(),
                            'linked_view':self.link_view.isChecked(),
                            'linked_line':self.link_line.isChecked(),
                            'linked_profile_y':self.link_y.isChecked(),
                            'linked_slices':self.link_slices.isChecked(),
                            'profile_source':self.profile_source.currentData(),
                            # Do not write a global calibration: v1.4 would misapply it to all views.
                            'calibration_mode':'per_panel',
                            'report_title':self.last_report_title,
                            'report_comment':self.last_report_comment,
                            'panel_count':self.panel_count,
                            'bookmarks':copy.deepcopy(self.bookmarks)},
                'panels':[panel.snapshot() for panel in self.visible_panels()]}

    def report_error(self,title,err):
        logger().error('%s: %s',title,err,exc_info=sys.exc_info()[0] is not None)
        QtWidgets.QMessageBox.warning(self,title,str(err))

    def _loaded_sources(self):
        return [str(p.files[p.index.value()-1]) for p in self.visible_panels()
                if p.files and 1 <= p.index.value() <= len(p.files)]

    def _export_name(self, kind, ext):
        """Suggest sample-level exports, with fallback for read-only datasets."""
        name=suggested_path(self._loaded_sources(),kind,ext)
        try:
            name.parent.mkdir(parents=True,exist_ok=True)
        except OSError:
            name=suggested_path(self._loaded_sources(),kind,ext,
                folder=Path.home()/'Documents'/'LOUPE_Exports')
            name.parent.mkdir(parents=True,exist_ok=True)
        return str(name)

    def _export_with_reservation(self, selected, exporter):
        """Reserve a unique destination even if user selected an existing path."""
        path=reserve_unique_path(selected)
        try:
            exporter(path)
            if not path.exists() or path.stat().st_size==0:
                raise OSError('Export produced an empty file')
        except Exception:
            rollback_empty(path)
            raise
        return path

    def export_csv(self):
        if any(p.loading for p in self.visible_panels()):
            self.report_error('Export CSV','Wait for the TIFF images to finish loading.')
            return
        panels=[]
        for panel in self.visible_panels():
            if panel.current is None or not self.profile_mode.isChecked():continue
            panel.update_profile()
            rec=panel.profile_export_record()
            if rec is not None:panels.append(rec)
        if not panels:
            self.report_error('Export CSV','Enable Profile mode and load a TIFF first.');return
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export profile CSV',self._export_name('Profile','csv'),'CSV (*.csv)')
        if not path:return
        try:
            path=self._export_with_reservation(path,lambda p:write_csv(p,panels))
            self.statusBar().showMessage(f'CSV saved: {path}',12000)
            log_action('Profile CSV exported',file=Path(path).name)
        except Exception as e:self.report_error('CSV export failed',e)

    def save_json(self):
        if any(p.loading for p in self.visible_panels()):
            self.report_error('Save Session','Wait for the current TIFF to finish loading, then save again.')
            return
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save Session',self._export_name('Session','json'),'JSON (*.json)')
        if not path:return
        try:
            path=self._export_with_reservation(path,lambda p:write_session(p,self.state()))
            self.statusBar().showMessage(f'Comparison saved: {path}',12000)
            log_action('Comparison JSON saved',file=Path(path).name)
        except Exception as e:self.report_error('Save Session failed',e)

    def load_json(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Open Session','','JSON (*.json)')
        if not path:return
        try:
            state=read_session(path)
            missing=[p.get('path') for p in state['panels'] if p.get('path') and not Path(p['path']).is_file()]
            if missing:raise FileNotFoundError('Missing image file(s):\n'+'\n'.join(missing))
            settings=state['settings']
            self.last_report_title=str(settings.get('report_title','LOUPE'))
            self.last_report_comment=str(settings.get('report_comment',''))
            self.bookmarks=[b for b in settings.get('bookmarks',[]) if isinstance(b,dict)][:1000]
            legacy_cal=settings.get('calibration')
            # Disable links during asynchronous restore so each panel gets its own state.
            for control in (self.link_view,self.link_line,self.link_y,self.link_slices):control.setChecked(False)
            self.profile_width.setValue(int(settings.get('width_px',1)))
            source=settings.get('profile_source','line')
            ix=self.profile_source.findData(source)
            self.profile_source.setCurrentIndex(ix if ix>=0 else 0)
            self.undo_stack.clear();self.redo_stack.clear();self.update_undo_buttons()
            self.profile_mode.setChecked(bool(settings.get('profile_mode',False)))
            self.view_count.setCurrentIndex(len(state['panels'])-1)
            for panel, pstate in zip(self.panels,state['panels']):
                panel.restore(pstate,calibration_default=legacy_cal)
            # A shorter saved comparison replaces (rather than merely hides) old panels.
            for panel in self.panels[len(state['panels']):]:
                panel.restore({'path':None, 'annotations_by_image':{}})
            # Re-enable after all visible images are ready; callbacks queued by Qt.
            self._restore_link_settings=settings
            QtCore.QTimer.singleShot(100,self._finish_restore_links)
            self.statusBar().showMessage(f'Loading comparison: {path}',12000)
            log_action('Comparison JSON loaded',file=Path(path).name)
        except Exception as e:self.report_error('Open Session failed',e)

    def _finish_restore_links(self):
        if any(p._pending_restore is not None for p in self.visible_panels()):
            QtCore.QTimer.singleShot(100,self._finish_restore_links)
            return
        settings=getattr(self,'_restore_link_settings',None)
        if settings is None:return
        self._restore_link_settings=None
        for control,key in ((self.link_view,'linked_view'),(self.link_line,'linked_line'),
                            (self.link_y,'linked_profile_y'),(self.link_slices,'linked_slices')):
            control.blockSignals(True);control.setChecked(bool(settings.get(key,False)));control.blockSignals(False)
        self.statusBar().showMessage('Comparison restored',12000)

    def _report_inputs(self, kind):
        if any(p.loading for p in self.visible_panels()):
            self.report_error('Report '+kind,'Wait for TIFF images to finish loading.')
            return None
        panels=[p.report_payload() for p in self.visible_panels() if p.current is not None]
        if not panels:
            self.report_error('Report '+kind,'Load a TIFF in a visible view first.')
            return None
        dialog=QtWidgets.QDialog(self)
        dialog.setWindowTitle('LOUPE '+kind+' report')
        form=QtWidgets.QFormLayout(dialog)
        title=QtWidgets.QLineEdit(self.last_report_title,dialog)
        comments=QtWidgets.QPlainTextEdit(dialog)
        comments.setPlaceholderText('Comparison notes, interpretation, sample information…')
        comments.setPlainText(self.last_report_comment)
        comments.setMinimumHeight(110)
        form.addRow('Report title',title)
        form.addRow('Comments',comments)
        form.addRow(QtWidgets.QLabel('Includes currently displayed TIFFs, ROI, scale bars and enabled profiles.'))
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok|
                                           QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()!=QtWidgets.QDialog.DialogCode.Accepted:return None
        return panels,title.text(),comments.toPlainText()

    def _export_report(self,kind):
        data=self._report_inputs(kind)
        if data is None:return
        panels,title,comment=data
        ext=kind.lower()
        filename=self._export_name('Report',ext)
        filt='PNG Image (*.png)' if kind=='PNG' else 'PDF Document (*.pdf)'
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export comparison '+kind,
                                                    filename,filt)
        if not path:return
        try:
            export=export_png_report if kind=='PNG' else export_pdf_report
            path=self._export_with_reservation(path,lambda p:export(p,panels,comment=comment,title=title))
            self.last_report_title=title
            self.last_report_comment=comment
            self.statusBar().showMessage(f'{kind} report saved: {path}',12000)
            log_action('Comparison report exported',format=kind,file=path.name,views=len(panels))
        except Exception as e:self.report_error(kind+' report export failed',e)

    def export_report_png(self):
        self._export_report('PNG')

    def export_report_pdf(self):
        self._export_report('PDF')

    def export_macro(self):
        state=self.state()
        if not any(p.get('path') for p in state['panels']):
            self.report_error('ImageJ macro','Load a TIFF first.');return
        if any(Path(p['path']).suffix.lower() == '.img' for p in state['panels'] if p.get('path')):
            self.report_error('ImageJ macro',
                'The ImageJ macro exporter currently supports TIFF datasets only. '
                'Convert IMG to TIFF before exporting an ImageJ macro.')
            return
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export ImageJ/Fiji macro',self._export_name('ImageJ','ijm'),'ImageJ Macro (*.ijm)')
        if not path:return
        try:
            path=self._export_with_reservation(path,lambda p:p.write_text(imagej_macro(state),encoding='utf-8'))
            self.statusBar().showMessage(f'Macro saved: {path}',12000)
            log_action('ImageJ macro exported',file=Path(path).name)
        except Exception as e:self.report_error('ImageJ macro export failed',e)

    def profile_settings_changed(self, *_):
        for panel in self.visible_panels():
            panel.update_width_overlay()
            panel.update_profile_roi_visibility()
            panel.update_profile()

    def toggle_profile(self, active):
        self.width_label.setVisible(active)
        self.profile_width.setVisible(active)
        for panel in self.panels:
            panel.set_profile_active(active)
        if active:
            self.refresh_y_axes()

    def link_view_toggled(self, linked):
        if linked:
            source=next((p for p in self.visible_panels() if p.current is not None),None)
            if source:
                self.view_changed(source,source.plot.getViewBox().viewRange())

    def view_changed(self, source, ranges):
        if self._syncing_view or not self.link_view.isChecked():
            return
        if source not in self.visible_panels() or source.current is None:return
        self._syncing_view = True
        try:
            # Linked views share exact source-pixel ranges.
            for target in self.visible_panels():
                if target is source or target.current is None:continue
                target.plot.getViewBox().setRange(xRange=ranges[0], yRange=ranges[1], padding=0)
                target.plot.getViewBox().disableAutoRange()
        finally:
            self._syncing_view = False

    def line_changed(self, source):
        if self._syncing or not self.profile_mode.isChecked() or not self.link_line.isChecked():
            return
        if source not in self.visible_panels() or source.roi is None:return
        self._syncing = True
        try:
            for target in self.visible_panels():
                if target is not source and target.roi is not None:
                    target.set_line(source.get_line())
        finally:
            self._syncing = False

    def link_line_toggled(self, linked):
        if linked and self.profile_mode.isChecked():
            source=next((p for p in self.visible_panels() if p.roi is not None),None)
            if source:self.line_changed(source)

    def _profile_distance_factor(self,panel):
        """Native px -> physical micrometres, None if uncalibrated."""
        cal=panel.calibration()
        if not cal['enabled']:
            return None
        from math import isfinite
        v=float(cal['pixel_size'])*{'nm':.001,'µm':1.,'mm':1000.}[cal['unit']]
        return v if isfinite(v) and v>0 else None

    def _profile_link_compatible(self):
        panels=[p for p in self.visible_panels() if p.current is not None]
        factors=[self._profile_distance_factor(p) for p in panels]
        return bool(panels) and (all(v is not None for v in factors) or
                                 all(v is None for v in factors))

    def link_y_toggled(self, linked):
        if linked:
            if not self._profile_link_compatible():
                self.link_y.setChecked(False)
                self.statusBar().showMessage('Linked profiles requires compatible pixel calibrations in all views',9000)
                return
            self.refresh_y_axes()
        else:
            for panel in self.visible_panels():
                panel.profile_plot.enableAutoRange(axis='x')
                panel.profile_plot.enableAutoRange(axis='y')

    def profile_range_changed(self, source, ranges):
        if (self._syncing_profile_y or self._setting_profile_ranges
                or not self.link_y.isChecked() or not self.profile_mode.isChecked()):
            return
        if source not in self.visible_panels():return
        source_factor=self._profile_distance_factor(source)
        if not self._profile_link_compatible():return
        self._syncing_profile_y=True
        try:
            for target in self.visible_panels():
                if target is source or target.current is None:continue
                target_factor=self._profile_distance_factor(target)
                factor=source_factor/target_factor if source_factor and target_factor else 1.
                target.profile_plot.getViewBox().setRange(
                    xRange=(ranges[0][0]*factor,ranges[0][1]*factor),
                    yRange=ranges[1],padding=0)
        finally:
            self._syncing_profile_y=False

    def refresh_y_axes(self, *_):
        if not self.link_y.isChecked() or not self.profile_mode.isChecked():return
        if not self._profile_link_compatible():return
        loaded=[p for p in self.visible_panels() if p.current is not None]
        bounds=[p._last_profile for p in loaded if p._last_profile]
        if not bounds:return
        lo=min(v[0] for v in bounds);hi=max(v[1] for v in bounds)
        margin=max((hi-lo)*.04,1e-9)
        # Establish a shared X range in physical units when calibrated.
        all_x=[]
        for p in loaded:
            rec=p.profile_export_record() if p.profile_active else None
            if rec:
                # Sample locations are native pixel distances, not display px.
                try:
                    extent=max(map(float,rec['profile'][0]))
                except (KeyError,TypeError,ValueError):
                    extent=0.
                all_x.append(extent*(self._profile_distance_factor(p) or 1.))
        extent=max(all_x,default=None)
        self._setting_profile_ranges=True
        try:
            for panel in loaded:
                vb=panel.profile_plot.getViewBox()
                vb.setYRange(lo-margin,hi+margin,padding=0)
                if extent is not None and extent>0:
                    factor=self._profile_distance_factor(panel) or 1.
                    vb.setXRange(0,extent/factor,padding=0)
        finally:
            self._setting_profile_ranges=False

    def select_pan_tool(self):
        if self.annotation_tool.currentData()!='pan':
            self.annotation_tool.setCurrentIndex(0)
        self.pan_button.setChecked(True)
        for panel in self.panels:panel.tool_changed()

    def annotation_tool_changed(self, *_):
        self.pan_button.setChecked(self.annotation_tool.currentData()=='pan')
        for panel in self.panels:panel.tool_changed()
        tool=self.annotation_tool.currentData()
        log_action('Tool selected',tool=tool)
        self.statusBar().showMessage('Pan / Zoom: drag to pan; wheel to zoom; choose a tool to measure.'
            if tool=='pan' else ('Count: click image to place numbered marker.'
            if tool=='count' else 'Draw '+tool+'; edit handles immediately; Shift constrains; Space pans.'),10000)

    def set_active_panel(self, panel):
        if panel in self.visible_panels():
            self._active_panel=panel

    def keyboard_step_slice(self, step):
        # Do not steal keyboard arrows from spin boxes (contrast, ROI width,
        # slice number), combo-boxes, or text editing widgets.
        focus=QtWidgets.QApplication.focusWidget()
        if isinstance(focus,(QtWidgets.QAbstractSpinBox,QtWidgets.QComboBox,
                             QtWidgets.QLineEdit,QtWidgets.QTextEdit,
                             QtWidgets.QPlainTextEdit)):
            return
        panel=self._active_panel
        if not panel.files:
            panel=next((p for p in self.visible_panels() if p.files),panel)
        if panel.files:
            old=panel.index.value()
            panel.change(step)
            if old!=panel.index.value():
                name=panel.objectName()
                self.statusBar().showMessage(
                    f'{name} slice {panel.index.value()} / {len(panel.files)}'
                    + (' | Linked slices' if self.link_slices.isChecked() else ''),4000)

    def link_slices_toggled(self, active):
        if active:
            source=next((p for p in self.visible_panels() if p.files),None)
            if source:self.slice_index_changed(source,source.index.value())

    def slice_index_changed(self, source, number):
        if self._syncing_slices or not self.link_slices.isChecked():return
        if source not in self.visible_panels():return
        self._syncing_slices=True
        try:
            skipped=[]
            for target in self.visible_panels():
                if target is source or not target.files:continue
                if number>len(target.files):
                    skipped.append(target.objectName())
                    continue
                target.index.setValue(number)
            if skipped:
                self.statusBar().showMessage(f'Slice {number} unavailable in: {", ".join(skipped)}',9000)
        finally:self._syncing_slices=False

    def update_undo_buttons(self):
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.redo_button.setEnabled(bool(self.redo_stack))

    def record_annotation_change(self,panel,path_key,before,after,action='Changed',item=None):
        self.undo_stack.append((panel,path_key,copy.deepcopy(before),copy.deepcopy(after)))
        info=caption(item) if item else f'{len(before)} -> {len(after)} ROIs'
        log_action('ROI '+action,panel=panel.display_name,type=item['type'] if item else 'mixed',detail=info)
        if len(self.undo_stack)>150:self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.update_undo_buttons()

    def undo_measurement(self):
        if not self.undo_stack:return
        entry=self.undo_stack.pop()
        panel,path,before,after=entry
        panel.apply_annotations_from_history(path,before)
        self.redo_stack.append(entry)
        log_action('Undo ROI',panel=panel.objectName())
        self.update_undo_buttons()

    def redo_measurement(self):
        if not self.redo_stack:return
        entry=self.redo_stack.pop()
        panel,path,before,after=entry
        panel.apply_annotations_from_history(path,after)
        self.undo_stack.append(entry)
        log_action('Redo ROI',panel=panel.objectName())
        self.update_undo_buttons()

    def clear_current_slice(self):
        # Prefer whichever panel has keyboard focus; ask which when ambiguous.
        options=[p.objectName() for p in self.visible_panels()]
        side,ok=QtWidgets.QInputDialog.getItem(self,'Clear annotations',
            'Select panel (current slice only):',options,0,False)
        if not ok:return
        panel=next(p for p in self.visible_panels() if p.objectName()==side)
        if not panel.visible_annotations():
            self.statusBar().showMessage('No annotations to clear on selected panel/slice',6000)
            return
        confirm=QtWidgets.QMessageBox.question(self,'Confirm clear',
            f'Delete all {len(panel.visible_annotations())} annotations from {side} current slice?\n'
            'Undo is available after clearing.')
        if confirm==QtWidgets.QMessageBox.StandardButton.Yes:panel.clear_visible_annotations()

    def export_measurements(self):
        rows=[]
        for panel in self.visible_panels():
            index_by_path={annotation_key(p):i+1 for i,p in enumerate(panel.files)}
            for file_key, items in panel.annotations_by_image.items():
                for a in items:
                    rows.append(measurement_row(panel.objectName(),file_key,
                                                index_by_path.get(file_key,''),a))
        if not rows:
            self.report_error('ROI CSV','Draw a measurement or place a count marker first.')
            return
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export ROI measurements',
                                                      self._export_name('ROI','csv'),'CSV (*.csv)')
        if not path:return
        try:
            path=self._export_with_reservation(path,lambda p:write_measurement_csv(p,rows))
            self.statusBar().showMessage(f'Exported {len(rows)} ROI/count records: {path}',12000)
            log_action('ROI CSV exported',file=Path(path).name,records=len(rows))
        except Exception as e:self.report_error('ROI CSV export failed',e)

    def _imagej_settings(self):
        settings=QtCore.QSettings('LOUPE','LOUPE')
        executable=str(settings.value('imagej/executable','') or '')
        heap=int(settings.value('imagej/heap_mib',0) or 0)
        return executable,heap

    def configure_imagej(self):
        previous,old_heap=self._imagej_settings()
        exe,_=QtWidgets.QFileDialog.getOpenFileName(self,'Locate ImageJ/Fiji executable',
            previous or str(Path.home()),'Executables (*.exe);;All files (*)')
        if not exe:return
        detected=heap_from_cfg(exe)
        heap_gib,ok=QtWidgets.QInputDialog.getDouble(self,'Fiji Java Heap setting',
            'Maximum Java heap (GiB, not installed RAM).\n'
            'Use the value set in Fiji: Edit → Options → Memory & Threads.\n'
            'Cancel if unknown; do not guess from the PC RAM:',
            (detected or old_heap or 4096)/1024.0,0.25,1024.0,2)
        if not ok:return
        heap=int(round(heap_gib*1024))
        settings=QtCore.QSettings('LOUPE','LOUPE')
        settings.setValue('imagej/executable',exe)
        settings.setValue('imagej/heap_mib',heap)
        log_action('ImageJ configured',executable=Path(exe).name,heap_mib=heap)
        self.statusBar().showMessage('ImageJ/Fiji configuration saved',7000)

    def _imagej_executable(self):
        executable,heap=self._imagej_settings()
        if not executable or not Path(executable).is_file():
            QtWidgets.QMessageBox.information(self,'ImageJ/Fiji not configured',
                'First use ImageJ/Fiji → Configure ImageJ/Fiji… and choose the installed executable.')
            return None
        return executable,heap

    def fiji_relay_setup(self):
        """Connect to an existing Fiji session; do not install startup hooks."""
        configured=self._imagej_executable()
        if configured is None:return
        executable=configured[0]
        if receiver_status()=='READY':
            QtWidgets.QMessageBox.information(self,'ImageJ/Fiji connection',
                'Fiji receiver is READY. Consecutive TIFF transfers are available.')
            return
        try:
            active=detect_running_fiji(executable)
        except Exception as exc:
            self.report_error('ImageJ/Fiji process check',str(exc));return
        if not active:
            QtWidgets.QMessageBox.information(self,'ImageJ/Fiji connection',
                'Fiji is not running. Open a TIFF from LOUPE to launch it.\n'
                'LOUPE will initialize a receiver in that Fiji session when possible.\n'
                'Your Fiji StartupMacros will NEVER be changed.')
            return
        import tempfile
        try:
            macro=runtime_receiver_macro()
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.ijm',
                                             prefix='LOUPE_Receiver_',delete=False) as f:
                f.write(macro)
                path=Path(f.name)
            status,detail=send_macro_to_existing_fiji(executable,path)
            state=receiver_status() if status=='DELIVERED' else 'OFFLINE'
            log_action('ImageJ1 receiver handshake',ipc=status,receiver=state)
            if state=='READY':
                QtWidgets.QMessageBox.information(self,'ImageJ/Fiji connection',
                    'Receiver is READY in the existing Fiji process.\n'
                    'Fiji StartupMacros have not been changed.')
            else:
                QtWidgets.QMessageBox.warning(self,'ImageJ/Fiji connection',
                    f'Runtime receiver not READY (IPC: {status}).\n{detail}\n\n'
                    'ImageJ1 IPC may be disabled, or this Fiji installation lacks '
                    'the Jython receiver runtime. Fiji StartupMacros remain unchanged.\n'
                    'Use the fallback macro via Fiji: Plugins → Macros → Run…')
        except Exception as exc:
            self.report_error('ImageJ/Fiji connection',str(exc))

    def _fiji_prelaunch_setup(self, executable):
        """v0.9.5 never modifies Fiji startup files prior to launch."""
        return True

    def _check_fiji_receiver_after_launch(self, retries=0):
        """Check READY, never claim that merely launching proves connectivity."""
        if not self.isVisible():return
        state=receiver_status()
        if state in ('READY','BUSY'):
            self.statusBar().showMessage('Fiji receiver connected — repeat transfers ready',12000)
            log_action('Fiji receiver active after launch',receiver_state=state)
            return
        if retries<24:
            QtCore.QTimer.singleShot(1500,lambda:self._check_fiji_receiver_after_launch(retries+1))
        else:
            self.statusBar().showMessage(
                'Fiji receiver not READY; ImageJ1 IPC will be attempted on next transfer',20000)
            log_action('Fiji receiver startup not confirmed',state=state)

    def _poll_fiji_job(self):
        """Non-blocking status; acceptance != successful Fiji image import."""
        pending=getattr(self,'_pending_fiji_job',None)
        if not pending:
            if hasattr(self,'_fiji_job_timer'):self._fiji_job_timer.stop()
            return
        import time as _time
        job,started=pending
        status=read_job_status(job)
        state=status.get('status','QUEUED')
        count=int(status.get('count',0))
        requested=int(status.get('requested',0))
        if state in ('COMPLETED','FAILED'):
            self._fiji_job_timer.stop()
            self._pending_fiji_job=None
            if state=='COMPLETED':
                warnings=status.get('warnings') or []
                text=f'Fiji import completed: {count} / {requested} slices'
                if warnings:
                    text+=f' · {len(warnings)} ROI warning(s) (see Fiji Log)'
                    QtWidgets.QMessageBox.warning(self,'Fiji ROI transfer warnings','\n'.join(warnings))
                self.statusBar().showMessage(text,16000)
                log_action('Fiji image import completed',frames=count)
            else:
                message=status.get('error','Unknown Fiji error')
                log_action('Fiji image import failed',details=str(message)[:120])
                QtWidgets.QMessageBox.warning(self,'Fiji import failed',str(message))
        elif state=='LOADING':
            self.statusBar().showMessage(f'Fiji importing: {count} / {requested} slices')
        else:
            self.statusBar().showMessage('Fiji accepted import request; waiting for processing…')
        if _time.monotonic()-started > 600 and state not in ('COMPLETED','FAILED'):
            self._fiji_job_timer.stop()
            self._pending_fiji_job=None
            self.statusBar().showMessage('Fiji completion not confirmed (timed out). Check Fiji.',20000)

    def _launch_imagej(self,executable,macro,source_paths=None,transfer=None):
        """Receiver -> ImageJ1 RMI -> launch only when no Fiji exists.

        Crucially, INCOMPATIBLE (old receiver) falls back to RMI instead of
        forcing the user to replace scientific Fiji StartupMacros. If both
        IPC transports fail for existing Fiji, NO SECOND Fiji is launched.
        """
        import tempfile
        import time as _time
        if getattr(self,'_pending_fiji_job',None):
            self.report_error('Fiji busy','Wait until the previous Fiji import has completed.')
            return
        if source_paths:
            state=receiver_status()
            if state=='READY':
                reply,job=create_open_request(source_paths,transfer=transfer)
                if reply=='QUEUED' and job is not None:
                    self._pending_fiji_job=(job,_time.monotonic())
                    if not hasattr(self,'_fiji_job_timer'):
                        self._fiji_job_timer=QtCore.QTimer(self)
                        self._fiji_job_timer.setInterval(450)
                        self._fiji_job_timer.timeout.connect(self._poll_fiji_job)
                    self._fiji_job_timer.start()
                    self.statusBar().showMessage('Fiji accepted image import request',7000)
                    log_action('Fiji structured import queued',frames=len(source_paths))
                    return
                if reply not in ('INCOMPATIBLE','OFFLINE'):
                    self.report_error('Fiji bridge refused import',
                                      'Receiver reply: '+str(reply)+'. No import was started.')
                    return
                log_action('Fiji receiver incompatible; try ImageJ1 RMI',reply=reply)
            elif state=='BUSY':
                self.report_error('Fiji busy','Fiji is still processing a previous import.')
                return
        if transfer is not None and source_paths and len(source_paths)==1:
            from .imagej_bridge import imagej_current_with_transfer_macro
            macro=imagej_current_with_transfer_macro(source_paths[0],transfer)
        # Runtime bootstrap is appended *after* image import, never touches Fiji
        # installation files, and avoids a second import of the same image.
        bootstrap=''
        try:
            bootstrap=runtime_receiver_macro()
        except Exception as exc:
            log_action('Fiji runtime bootstrap unavailable',error=str(exc)[:150])
        combined=macro+'\n'+bootstrap
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.ijm',
                                          prefix='LOUPE_ImageJ_',delete=False) as f:
            f.write(combined)
            macro_path=Path(f.name)
        try:
            # Positive process detection comes from tasklist + owner PID,
            # never from Explorer titles alone.
            active=detect_running_fiji(executable)
            if self._imagej_child is not None and self._imagej_child.poll() is None:
                active.append(('LOUPE launched Fiji','running'))
            if recent_fiji_launch():active.append(('LOUPE recently launched Fiji','pending'))
            if active:
                reply,detail=send_macro_to_existing_fiji(executable,macro_path)
                if reply=='DELIVERED':
                    log_action('ImageJ1 IPC macro delivered',frames=len(source_paths or []))
                    self.statusBar().showMessage(
                        'Existing Fiji received image command via ImageJ1 IPC; check Fiji import',14000)
                    QtCore.QTimer.singleShot(1800,lambda:self._check_fiji_receiver_after_launch())
                    return
                # Fail closed: no guessing that this Java helper can reach Fiji.
                QtWidgets.QApplication.clipboard().setText(macro)
                log_action('Existing Fiji IPC unavailable',detail=detail[:180])
                QtWidgets.QMessageBox.warning(self,'ImageJ/Fiji IPC unavailable',
                    'Fiji is already running. No second Fiji process was started.\n\n'
                    f'ImageJ1 IPC: {detail}\n\n'
                    'The import macro is on your clipboard. In Fiji open '
                    'Plugins → Macros → New, paste it and choose Run.\n'
                    'Alternatively use ImageJ/Fiji → ImageJ/Fiji Connection Check…\n\n'
                    'Fiji StartupMacros were not changed.')
                return
            if not self._fiji_prelaunch_setup(executable):return
            child=launch_imagej_macro(executable,macro_path)
            self._imagej_child=child
            QtCore.QTimer.singleShot(4000,lambda:self._check_fiji_receiver_after_launch())
            log_action('Fiji start requested',exe=Path(executable).name,pid=child.pid)
            self.statusBar().showMessage('Fiji start requested; receiver handshake pending',10000)
        except Exception:
            macro_path.unlink(missing_ok=True)
            raise

    def _choose_imagej_view(self, title, *, sequence=False):
        """Explicitly select the source VIEW; never use last mouse-hover state."""
        candidates=[p for p in self.visible_panels() if p.current is not None and p.files]
        supported=[p for p in candidates if p.current_path and
                   Path(p.current_path).suffix.lower() in ('.tif','.tiff','.img')]
        if not supported:
            self.report_error(title,'No TIFF or supported IMG series is loaded in visible VIEW panels.')
            return None
        dlg=QtWidgets.QDialog(self)
        dlg.setWindowTitle(title+' — Select VIEW')
        dlg.setMinimumWidth(500)
        layout=QtWidgets.QVBoxLayout(dlg)
        layout.addWidget(QtWidgets.QLabel('Select the VIEW to open in ImageJ/Fiji:'))
        combo=QtWidgets.QComboBox(dlg)
        for panel in supported:
            label=(f'{panel.display_name}  |  {Path(panel.current_path).name}  |  '
                   f'{panel.index.value()} / {len(panel.files)}')
            combo.addItem(label,self.panels.index(panel))
        default=self._active_panel
        if default in supported:
            combo.setCurrentIndex(supported.index(default))
        combo.setMinimumWidth(350)
        layout.addWidget(combo)
        file_info=QtWidgets.QLabel(dlg)
        file_info.setWordWrap(True)
        layout.addWidget(file_info)
        def update_info(_=None):
            panel=self.panels[int(combo.currentData())]
            file_info.setText(f'Full image: {panel.current_path}\n'
                              f'Sequence: {len(panel.files)} slices'
                              + ('\nNext: choose the start and end slices.' if sequence else
                                 '\nOnly the currently displayed image will be opened.'))
        combo.currentIndexChanged.connect(update_info)
        update_info()
        buttons=QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText(
            'Next…' if sequence else 'Open in Fiji')
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec()!=QtWidgets.QDialog.DialogCode.Accepted:
            return None
        return self.panels[int(combo.currentData())]

    def open_imagej_current(self):
        panel=self._choose_imagej_view('Open Current Image')
        if panel is None:return
        if panel.current is None:
            self.report_error('Open Current TIFF','Select a view with a loaded TIFF or IMG image.')
            return
        configured=self._imagej_executable()
        if configured is None:return
        try:
            source=panel.current_path
            if Path(source).suffix.lower()=='.img':
                cal=panel.calibration()
                factor={'nm':0.001,'µm':1.0,'mm':1000.0}
                um=float(cal['pixel_size'])*factor[cal['unit']] if cal['enabled'] else None
                clean_old_temporary_imports()
                source=str(converted_img_file(source,um))
            from .fiji_transfer import make_transfer
            # Share the current image's ROI, display Min/Max and per-view scale.
            # An IMG is converted losslessly before it reaches the Fiji bridge.
            levels=panel.image.levels if panel.current is not None else None
            cal=panel.calibration()
            if getattr(panel,'_auto_header_um',None) and cal['enabled']:
                micron=cal['pixel_size']*{'nm':.001,'µm':1.,'mm':1000.}[cal['unit']]
                if micron/panel._auto_header_um>=1000 or micron/panel._auto_header_um<=0.001:
                    cal={'enabled':False}
            annotations=list(panel.visible_annotations())
            if self.profile_mode.isChecked() and panel.roi is not None:
                from .measurements import create_annotation
                endpoints=panel.get_line()
                if endpoints:
                    annotations.append(create_annotation('line',endpoints[0],endpoints[1],
                                    identifier='loupe_profile_line'))
            transfer=make_transfer(annotations=annotations,
                selected_id=panel.selected_annotation_id,
                width_px=self.profile_width.value(), display_limits=levels,
                calibration=cal)
            self._launch_imagej(configured[0],imagej_current_macro(source),
                                source_paths=[source],transfer=transfer)
        except Exception as e:self.report_error('Open Current TIFF failed',e)

    def open_imagej_stack(self):
        panel=self._choose_imagej_view('Open Stack',sequence=True)
        if panel is None:return
        if not panel.files or panel.current is None:
            self.report_error('Open Stack','Select a view containing a TIFF sequence.')
            return
        # Select a contiguous subset BEFORE checking RAM. Full 2048-slice
        # float32 CT stacks cannot fit in the typical 16-GiB analysis laptop.
        range_dialog=QtWidgets.QDialog(self)
        range_dialog.setWindowTitle('Open Stack — Select slice range')
        range_layout=QtWidgets.QFormLayout(range_dialog)
        start_box=QtWidgets.QSpinBox();start_box.setRange(1,len(panel.files))
        end_box=QtWidgets.QSpinBox();end_box.setRange(1,len(panel.files))
        start_box.setValue(panel.index.value())
        end_box.setValue(min(len(panel.files), start_box.value()+99))
        start_box.valueChanged.connect(lambda n:end_box.setMinimum(n))
        range_layout.addRow('First slice (1-based):',start_box)
        range_layout.addRow('Last slice (inclusive):',end_box)
        all_button=QtWidgets.QPushButton('Select all')
        all_button.clicked.connect(lambda: (start_box.setValue(1),end_box.setValue(len(panel.files))))
        range_layout.addRow(all_button)
        range_layout.addRow(QtWidgets.QLabel('Only the selected images are loaded. No Virtual Stack.'))
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok|
                                           QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(range_dialog.accept);buttons.rejected.connect(range_dialog.reject)
        range_layout.addRow(buttons)
        if range_dialog.exec()!=QtWidgets.QDialog.DialogCode.Accepted:return
        selected=panel.files[start_box.value()-1:end_box.value()]
        configured=self._imagej_executable()
        if configured is None:return
        exe,heap=configured
        if heap<=0:
            self.report_error('Open Stack','Java heap is not configured. Use ImageJ settings first.')
            return
        # Convert only a chosen IMG subset, never the entire sequence implicitly.
        # Keep converted TIFFs long enough for Fiji to load asynchronously.
        if selected and Path(selected[0]).suffix.lower()=='.img':
            cal=panel.calibration()
            factor={'nm':0.001,'µm':1.0,'mm':1000.0}
            spacing=float(cal['pixel_size'])*factor[cal['unit']] if cal['enabled'] else None
            conversion=QtWidgets.QProgressDialog('Converting IMG files to temporary lossless TIFFs…',
                'Cancel',0,len(selected),self)
            conversion.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
            conversion.setMinimumDuration(0)
            new_files=[]
            try:
                clean_old_temporary_imports()
                for i,original in enumerate(selected):
                    QtWidgets.QApplication.processEvents()
                    if conversion.wasCanceled():raise InterruptedError('IMG conversion cancelled')
                    new_files.append(str(converted_img_file(original,spacing)))
                    conversion.setValue(i+1)
                selected=new_files
            except (OSError,ValueError,InterruptedError) as exc:
                for created in new_files:Path(created).unlink(missing_ok=True)
                self.report_error('IMG conversion',str(exc))
                return
            finally:
                conversion.close()
        dialog=QtWidgets.QProgressDialog('Inspecting selected TIFF headers…','Cancel',0,len(selected),self)
        dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        def progress(i,n):
            if i%32==0:
                dialog.setValue(i)
                QtWidgets.QApplication.processEvents()
            return dialog.wasCanceled()
        try:
            info=inspect_sequence(selected,cancellation=progress,allow_subset=True)
            dialog.setValue(len(selected))
            available=physical_available()
            required=stack_preflight(info,available,heap)
            est_seconds=info['bytes']/(150*MIB)+20 # illustrative transfer+startup, not a promise
            answer=QtWidgets.QMessageBox.question(self,'Confirm non-virtual ImageJ Stack',
                f'VIEW: {panel.display_name}\n'
                f'Slices: {start_box.value()}–{end_box.value()} | Images: {info["count"]}\n'
                f'Shape: {info["shape"]} | {info["dtype"]}\n'
                f'Original volume: {info["bytes"]/MIB/1024:.2f} GiB\n'
                f'Conservative working-memory budget: {required/MIB/1024:.2f} GiB\n'
                f'Available physical RAM: {available/MIB/1024:.2f} GiB\n'
                f'Configured Java heap: {heap/1024:.2f} GiB\n'
                f'Rough transfer/startup estimate: ~{est_seconds/60:.1f} min\n'
                'Actual time varies greatly by disk and hardware.\n\n'
                'Import as a normal in-RAM Stack? (NOT Virtual Stack)',
                QtWidgets.QMessageBox.StandardButton.Yes|
                QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No)
            if answer!=QtWidgets.QMessageBox.StandardButton.Yes:return
            self._launch_imagej(exe,imagej_stack_macro(info),source_paths=selected)
        except InterruptedError:
            self.statusBar().showMessage('Stack preflight cancelled',6000)
        except Exception as e:
            if isinstance(e,MemoryError) and 'info' in locals():
                suggested=recommended_stack_count(info['shape'],info['dtype'],
                                                   physical_available(),heap,len(selected))
                self.report_error('Open Stack blocked',
                    str(e)+f'\n\nEstimated safe subset: up to {suggested} slices at the moment. '
                    'This depends on changing free RAM and requires another preflight.')
            else:
                self.report_error('Open Stack blocked',e)
        finally:
            dialog.close()

    def copy_comparison(self):
        if any(p.loading for p in self.visible_panels()):
            self.report_error('Copy Comparison','Wait for the images to finish loading.')
            return
        items=[p.report_payload() for p in self.visible_panels() if p.current is not None]
        if not items:return
        try:
            canvas=render_report_image(items,comment=self.last_report_comment,
                                       title=self.last_report_title)
            QtWidgets.QApplication.clipboard().setPixmap(QtGui.QPixmap.fromImage(canvas))
            self.statusBar().showMessage('Comparison image copied to clipboard',6000)
        except Exception as e:self.report_error('Copy Comparison failed',e)

    def copy_profile(self):
        panel=self._active_panel
        if not panel.profile_active or panel._profile_data is None:
            self.report_error('Copy Profile','Enable Profile mode in the active view first.')
            return
        QtWidgets.QApplication.clipboard().setPixmap(panel.profile_plot.grab())
        self.statusBar().showMessage(f'{panel.display_name} profile copied',6000)

    def overlay_profiles(self):
        loaded=[]
        for panel in self.visible_panels():
            if panel.current is not None and panel.profile_active and not panel.loading:
                panel.update_profile()
                record=panel.profile_export_record()
                if record is not None: loaded.append((panel,record))
        if len(loaded)<2:
            self.report_error('Overlay Profiles','Enable Profile mode with two or more loaded views.')
            return
        dlg=QtWidgets.QDialog(self)
        dlg.setWindowTitle('LOUPE — overlay profiles (comparison)')
        dlg.resize(950,550)
        layout=QtWidgets.QVBoxLayout(dlg)
        plot=pg.PlotWidget()
        plot.addLegend()
        plot.setLabel('left','Native TIFF intensity')
        # Only convert distance to physical units if every view is calibrated.
        calibrated=all(p.calibration()['enabled'] for p,_ in loaded)
        plot.setLabel('bottom','Distance',units='µm' if calibrated else 'px')
        palette=('#2196d2','#db6c39','#2aa568','#8f63cf')
        factors={'nm':1e-3,'µm':1,'mm':1e3}
        for i,(panel,rec) in enumerate(loaded):
            d,v=rec['profile']
            if calibrated:
                cal=panel.calibration()
                d=np.asarray(d)*float(cal['pixel_size'])*factors[cal['unit']]
            plot.plot(d,v,pen=pg.mkPen(palette[i%4],width=2),name=panel.display_name)
        layout.addWidget(plot)
        help_text=('Physical distance µm (per-view calibration applied)' if calibrated else
                   'Uncalibrated distance in pixels. Different magnifications may not align.')
        layout.addWidget(QtWidgets.QLabel(help_text))
        buttons=QtWidgets.QHBoxLayout()
        copy_btn=QtWidgets.QPushButton('Copy Graph')
        copy_btn.clicked.connect(lambda:QtWidgets.QApplication.clipboard().setPixmap(plot.grab()))
        close_btn=QtWidgets.QPushButton('Close')
        close_btn.clicked.connect(dlg.accept)
        buttons.addWidget(copy_btn);buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        dlg.exec()

    def copy_roi_to_view(self):
        """Copy any selection of ROIs in one transaction and one Undo step."""
        candidates={p:[a for a in p.visible_annotations()
                         if a.get('type') in ('line','rect','ellipse','circle')]
                    for p in self.visible_panels() if p.current is not None}
        sources=[p for p,items in candidates.items() if items]
        if not sources:
            self.report_error('Copy ROI','Draw or load a Line, Rectangle or Ellipse first.')
            return
        if len(candidates)<2:
            self.report_error('Copy ROI','Load another comparison VIEW first.')
            return
        dialog=QtWidgets.QDialog(self)
        dialog.setWindowTitle('Copy ROI · multiple selection')
        dialog.setMinimumWidth(540)
        form=QtWidgets.QFormLayout(dialog)
        source_combo=QtWidgets.QComboBox()
        for source in sources:source_combo.addItem(source.display_name,self.panels.index(source))
        if self._active_panel in sources:source_combo.setCurrentIndex(sources.index(self._active_panel))
        form.addRow('Source VIEW:',source_combo)
        selection=QtWidgets.QListWidget()
        selection.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        selection.setMinimumHeight(175)
        form.addRow('Source ROIs:',selection)
        actions=QtWidgets.QHBoxLayout()
        select_all=QtWidgets.QPushButton('Select All')
        clear=QtWidgets.QPushButton('Clear')
        actions.addWidget(select_all); actions.addWidget(clear);actions.addStretch(1)
        form.addRow(actions)
        target_combo=QtWidgets.QComboBox()
        form.addRow('Target VIEW:',target_combo)
        def source_changed(*_):
            source=self.panels[int(source_combo.currentData())]
            selection.clear()
            for idx,item in enumerate(candidates[source]):
                entry=QtWidgets.QListWidgetItem(f'{item["type"]} · {caption(item)}')
                entry.setFlags(entry.flags()|QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                entry.setCheckState(QtCore.Qt.CheckState.Checked if (
                    item.get('id')==source.selected_annotation_id or
                    source.selected_annotation_id is None) else QtCore.Qt.CheckState.Unchecked)
                selection.addItem(entry)
            target_combo.clear()
            for target in self.visible_panels():
                if target is not source and target.current is not None:
                    target_combo.addItem(target.display_name,self.panels.index(target))
        source_combo.currentIndexChanged.connect(source_changed)
        source_changed()
        select_all.clicked.connect(lambda: [selection.item(i).setCheckState(QtCore.Qt.CheckState.Checked)
                                           for i in range(selection.count())])
        clear.clicked.connect(lambda: [selection.item(i).setCheckState(QtCore.Qt.CheckState.Unchecked)
                                      for i in range(selection.count())])
        note=QtWidgets.QLabel('Native source-image pixel coordinates are preserved. Different\n'
                              'pixel sizes do not imply matching physical locations.')
        form.addRow(note)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok|
                                           QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec()!=QtWidgets.QDialog.DialogCode.Accepted or target_combo.currentData() is None:
            return
        origin=self.panels[int(source_combo.currentData())]
        targets=[candidates[origin][i] for i in range(selection.count())
                 if selection.item(i).checkState()==QtCore.Qt.CheckState.Checked]
        if not targets:
            self.statusBar().showMessage('Copy ROI: no ROIs selected',5000)
            return
        target=self.panels[int(target_combo.currentData())]
        origin_cal=origin.calibration();target_cal=target.calibration()
        if origin_cal['enabled'] and target_cal['enabled'] and (
            origin_cal['pixel_size']!=target_cal['pixel_size'] or
            origin_cal['unit']!=target_cal['unit']):
            answer=QtWidgets.QMessageBox.question(self,'Different image scales',
                'Pixel sizes differ between views. Copy unchanged native pixel coordinates?\n'
                'This does not match physical positions or dimensions.',
                QtWidgets.QMessageBox.StandardButton.Yes|QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No)
            if answer!=QtWidgets.QMessageBox.StandardButton.Yes:return
        key=target.active_annotation_key()
        if key is None:return
        before=copy.deepcopy(target.visible_annotations())
        after=copy.deepcopy(before)
        if len(after)+len(targets)>2000:
            self.report_error('Copy ROI','Target would exceed 2000 ROI limit.')
            return
        for item in targets:
            clone=copy.deepcopy(item)
            clone['id']=uuid.uuid4().hex
            after.append(validate_annotation(clone))
        target.annotations_by_image[key]=after
        target.selected_annotation_id=after[-1]['id']
        target.redraw_measurements()
        target.update_profile()
        self.record_annotation_change(target,key,before,after,action='Batch copied')
        log_action('ROI batch copied',source=origin.display_name,target=target.display_name,count=len(targets))
        self.statusBar().showMessage(f'Copied {len(targets)} ROIs: {origin.display_name} → {target.display_name}',7000)

    def open_orthogonal_view(self):
        """Open lazy CT-only workspace without changing any comparison state."""
        panel=self._active_panel
        if not panel.files or panel.current is None:
            self.report_error('Orthogonal View', 'Select a loaded CT reconstruction VIEW first.')
            return
        try:
            from .orthogonal.cache import validate_ct_series
            from .orthogonal.viewer import OrthogonalDialog
            paths=validate_ct_series(panel.files)
            cal=panel.calibration()
            scales={'nm':.001,'µm':1.,'mm':1000.}
            px=float(cal['pixel_size'])*scales[cal['unit']] if cal['enabled'] else None
            options=[]
            from .tiff_metadata import read_reconstruction_metadata
            for i,other in enumerate(self.visible_panels()):
                if not other.files or other.current is None:continue
                try:valid=validate_ct_series(other.files)
                except (ValueError,OSError):continue
                other_cal=other.calibration()
                verified=read_reconstruction_metadata(valid[0])
                other_px=(float(other_cal['pixel_size'])*scales[other_cal['unit']]
                    if other_cal['enabled'] else float(verified['pixel_size_um']) if verified else None)
                options.append({'label':other.display_name,'paths':valid,
                    'slice':other.index.value()-1,'pixel_size_um':other_px,
                    'current':other.current,
                    'show_scale_bar':bool(other.show_scale_bar.isChecked())})
            verified=read_reconstruction_metadata(paths[0])
            if verified and not cal['enabled']: px=float(verified['pixel_size_um'])
            selected=next((i for i,v in enumerate(options)
                           if v['label']==panel.display_name),0)
            dialog=OrthogonalDialog(paths, initial_slice=panel.index.value()-1,
                                   initial_xy=panel.current,pixel_size_um=px,parent=self,
                                   view_sources=options,selected_view=selected)
            if not hasattr(self,'_orthogonal_windows'):
                self._orthogonal_windows=[]
            dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose,True)
            self._orthogonal_windows.append(dialog)
            dialog.destroyed.connect(lambda _=None,d=dialog:self._orthogonal_windows.remove(d)
                                     if d in self._orthogonal_windows else None)
            dialog.show()
            log_action('Orthogonal view opened',panel=panel.display_name,
                       frames=len(paths),calibrated=bool(cal['enabled']))
        except Exception as exc:
            self.report_error('Orthogonal View',str(exc))

    def add_bookmark(self):
        panel=self._active_panel
        if not panel.files:return
        if len(self.bookmarks)>=1000:
            self.report_error('Bookmarks','The 1000-bookmark limit has been reached.')
            return
        note,ok=QtWidgets.QInputDialog.getText(self,'Bookmark Slice','Comment (optional):')
        if not ok:return
        self.bookmarks.append({'view':self.panels.index(panel),
             'path':str(panel.files[panel.index.value()-1]),
             'slice':panel.index.value(),'comment':note[:500]})
        self.statusBar().showMessage(f'Bookmarked {panel.display_name}: slice {panel.index.value()}',6000)

    def goto_bookmark(self):
        if not self.bookmarks:
            self.statusBar().showMessage('No saved bookmarks',5000)
            return
        labels=[f'{i+1}. VIEW {b.get("view",0)+1} | slice {b.get("slice",1)} | {b.get("comment","")}'
                for i,b in enumerate(self.bookmarks)]
        chosen,ok=QtWidgets.QInputDialog.getItem(self,'Go to Bookmark','Select:',labels,0,False)
        if not ok:return
        b=self.bookmarks[labels.index(chosen)]
        ix=int(b.get('view',0))
        if not 0<=ix<4:return
        if ix>=self.panel_count:self.view_count.setCurrentIndex(ix)
        panel=self.panels[ix]
        target=Path(b.get('path',''))
        if not target.is_file():
            self.report_error('Bookmark','Source TIFF not found: '+str(target))
            return
        if not panel.files or target not in panel.files:
            panel.open_path(target)
        if panel.files and 1<=b.get('slice',0)<=len(panel.files):
            panel.index.setValue(int(b['slice']))
        self.set_active_panel(panel)

    def open_log_folder(self):
        from .diagnostics import log_root
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(log_root())))

    def export_bug_report(self):
        dialog=QtWidgets.QDialog(self)
        dialog.setWindowTitle('Export LOUPE Bug Report')
        layout=QtWidgets.QFormLayout(dialog)
        description=QtWidgets.QPlainTextEdit(dialog)
        description.setPlaceholderText('What did you do, and what happened?')
        description.setMaximumHeight(95)
        expected=QtWidgets.QPlainTextEdit(dialog)
        expected.setPlaceholderText('What did you expect? (optional)')
        expected.setMaximumHeight(65)
        layout.addRow('What happened?',description)
        layout.addRow('Expected behavior',expected)
        logs=QtWidgets.QCheckBox('Include action and error logs')
        logs.setChecked(True)
        env=QtWidgets.QCheckBox('Include version and environment information')
        env.setChecked(True)
        layout.addRow(logs);layout.addRow(env)
        layout.addRow(QtWidgets.QLabel('No original TIFF will be included. No automatic upload.'))
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
              QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        layout.addRow(buttons)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if dialog.exec()!=QtWidgets.QDialog.DialogCode.Accepted:return
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save Bug Report',
              self._export_name('BugReport','zip'),'ZIP archive (*.zip)')
        if not path:return
        try:
            log_action('Bug report requested')
            path=self._export_with_reservation(path,lambda p:create_bug_report(
                p,description.toPlainText(),expected.toPlainText(),
                include_logs=logs.isChecked(),include_environment=env.isChecked()))
            self.statusBar().showMessage('Bug report saved: '+Path(path).name,12000)
        except Exception as exc:self.report_error('Bug report export failed',exc)

    def closeEvent(self, event):
        for p in self.panels:
            p._closing=True
            p.prefetch_pool.shutdown(wait=False,cancel_futures=True)
        self.pool.shutdown(wait=False, cancel_futures=True)
        log_action('LOUPE window closed',window=self.instance_number,session=self.window_session_id)
        super().closeEvent(event)
