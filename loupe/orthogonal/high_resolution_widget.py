"""Opt-in native-pixel orthogonal workspace with shared native-pixel ROI editing.

Does not load the 3D stack; leaves regular 1-4 VIEW and 256^3 preview alone.
GUI coordinates are shown 1-based; arrays and stored sidecar are 0-based.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import copy
import math
import os
import shutil
import tempfile
import threading
import uuid

import numpy as np
import tifffile
from PySide6 import QtCore, QtWidgets, QtGui
import pyqtgraph as pg

from ..io import display_limits
from ..profiles import sample_thick_line
from ..calibration_spin import CalibrationSpinBox
from ..diagnostics import log_action, logger
from .high_resolution import scan_series, extract_plane, ExtractionCancelled
from .scalebar import scale_bar_spec, scale_bar_label
from .report_provenance import orthogonal_provenance_lines
from .roi_controller import HighResROIController, AnnotationViewBox
from ..measurements import caption, physical_dimensions


class _Signals(QtCore.QObject):
    progress = QtCore.Signal(int, str, int, int)
    completed = QtCore.Signal(int, object, object)
    failed = QtCore.Signal(int, str, bool)


class HighResolutionWidget(QtWidgets.QWidget):
    """Standalone tab controller; all Qt methods run on the GUI thread."""
    busy_changed = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='LOUPE-HighRes')
        self._signals = _Signals(self)
        self._signals.progress.connect(self._on_progress)
        self._signals.completed.connect(self._on_complete)
        self._signals.failed.connect(self._on_failed)
        self._job_id = 0
        self._cancel = None
        self._busy = False
        self._closed = False
        self._temp = tempfile.TemporaryDirectory(prefix='LOUPE_Orthogonal_HR_')
        self._paths = ()
        self._pixel_size_um = None
        self._result = None
        self._image_data = None
        self._exported_path = None
        self._last_profile = None
        self._undo_stack=[]
        self._redo_stack=[]
        self._restoring=False
        self._scale = (None, None)
        self._profile_dialog = None
        self._build_ui()

    @property
    def busy(self):
        return self._busy

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.addWidget(QtWidgets.QLabel('<b>NATIVE SECTION</b>  ·  Native CT pixels  ·  Quantitative TIFF (no interpolation)'))
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(QtWidgets.QLabel('Plane'))
        self.plane = QtWidgets.QComboBox()
        self.plane.addItems(('YZ · X fixed', 'ZX · Y fixed'))
        self.plane.currentIndexChanged.connect(self._axis_changed)
        toolbar.addWidget(self.plane)
        self.index_label = QtWidgets.QLabel('X (1-based)')
        toolbar.addWidget(self.index_label)
        self.index = QtWidgets.QSpinBox()
        self.index.setRange(1, 1)
        self.index.setToolTip('Native source pixel position, displayed 1-based. No preview decimation.')
        toolbar.addWidget(self.index)
        self.generate = QtWidgets.QPushButton('Generate NATIVE SECTION')
        self.generate.clicked.connect(self.start)
        toolbar.addWidget(self.generate)
        self.stop_button = QtWidgets.QPushButton('STOP')
        self.stop_button.setToolTip('Cancel native-pixel extraction only; existing preview is unaffected.')
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        toolbar.addWidget(self.stop_button)
        outer.addLayout(toolbar)
        options = QtWidgets.QHBoxLayout()
        self.all_z = QtWidgets.QCheckBox('All Z slices')
        self.all_z.setChecked(True)
        self.all_z.toggled.connect(self._range_changed)
        options.addWidget(self.all_z)
        options.addWidget(QtWidgets.QLabel('Z start'))
        self.z_start = QtWidgets.QSpinBox(); self.z_start.setRange(1, 1)
        options.addWidget(self.z_start)
        options.addWidget(QtWidgets.QLabel('Z end (inclusive)'))
        self.z_end = QtWidgets.QSpinBox(); self.z_end.setRange(1, 1)
        options.addWidget(self.z_end)
        self.z_start.valueChanged.connect(self._range_changed)
        self.z_end.valueChanged.connect(self._range_changed)
        options.addStretch(1)
        outer.addLayout(options)
        xy_row=QtWidgets.QHBoxLayout()
        self.custom_xy=QtWidgets.QCheckBox('Override XY pixel size')
        self.custom_xy.setToolTip('Use a manually verified XY pixel size instead of the TIFF header when generating Native Section.')
        xy_row.addWidget(self.custom_xy)
        self.xy_spacing=CalibrationSpinBox()
        self.xy_spacing.setRange(0.000001,1000000)
        self.xy_spacing.setDecimals(6)
        self.xy_spacing.setToolTip('Verified source XY pixel size (µm/px); overrides TIFF metadata in Native Section output.')
        self.xy_spacing.setEnabled(False)
        self.custom_xy.toggled.connect(self.xy_spacing.setEnabled)
        xy_row.addWidget(self.xy_spacing)
        xy_row.addWidget(QtWidgets.QLabel('µm/px'))
        self.xy_source=QtWidgets.QLabel('Source: TIFF header')
        xy_row.addWidget(self.xy_source,1)
        outer.addLayout(xy_row)
        opts2=QtWidgets.QHBoxLayout()
        self.custom_z = QtWidgets.QCheckBox('Custom verified Z spacing')
        opts2.addWidget(self.custom_z)
        self.z_spacing = CalibrationSpinBox()
        self.z_spacing.setRange(0.000001, 1000000)
        self.z_spacing.setDecimals(6)
        self.z_spacing.setToolTip('Z spacing in µm per source slice; enter directly')
        self.z_spacing.setEnabled(False)
        self.custom_z.toggled.connect(self.z_spacing.setEnabled)
        opts2.addWidget(self.z_spacing)
        opts2.addWidget(QtWidgets.QLabel('µm'))
        self.orientation = QtWidgets.QLabel('Image top = lowest numeric slice index; physical up/down NOT verified.')
        self.orientation.setWordWrap(True)
        opts2.addWidget(self.orientation, 1)
        outer.addLayout(opts2)
        self.source_label=QtWidgets.QLabel('Waiting for CT preview…')
        self.source_label.setWordWrap(True)
        outer.addWidget(self.source_label)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        viewer=QtWidgets.QWidget()
        viewer_layout=QtWidgets.QVBoxLayout(viewer)
        viewer_layout.setContentsMargins(0,0,0,0)
        self.measure_viewbox=AnnotationViewBox()
        self.plot = pg.PlotWidget(viewBox=self.measure_viewbox)
        self.plot.setBackground('#101820')
        self.plot.setAspectLocked(True)
        self.plot.invertY(True)  # native increasing Z goes down, no flip
        self.plot.setLabel('bottom', 'Native horizontal coordinate', units='px')
        self.plot.setLabel('left', 'Z slice offset (0-based)')
        self.image = pg.ImageItem(axisOrder='row-major')
        self.plot.addItem(self.image)
        self.plot.setMinimumSize(220, 230)
        self.plot.setToolTip('Mouse wheel: zoom  |  Middle-button drag: pan  |  Left drag: ROI tool / pan')
        self.plot.scene().sigMouseMoved.connect(self._mouse_moved)
        self.plot.getViewBox().sigRangeChanged.connect(self._update_scale_bar)
        self.bar = pg.PlotCurveItem(pen=pg.mkPen('#ffffff', width=3))
        self.bar_label = pg.TextItem(color='#ffffff', anchor=(0,1), fill=pg.mkBrush(8,16,27,210))
        self.plot.addItem(self.bar, ignoreBounds=True)
        self.plot.addItem(self.bar_label, ignoreBounds=True)
        self.bar.hide(); self.bar_label.hide()
        viewer_layout.addWidget(self.plot,1)
        self.pixel_label = QtWidgets.QLabel('No native-pixel image. Preview images must not be measured.')
        viewer_layout.addWidget(self.pixel_label)
        splitter.addWidget(viewer)
        sidebar=QtWidgets.QWidget()
        side=QtWidgets.QVBoxLayout(sidebar)
        side.setContentsMargins(6,0,0,0)
        side.addWidget(QtWidgets.QLabel('<b>Native Section data</b>'))
        self.details=QtWidgets.QLabel('Generate YZ or ZX from the original recNNNNN TIFF sequence.')
        self.details.setWordWrap(True)
        side.addWidget(self.details)
        self.profile_mode=QtWidgets.QComboBox()
        self.profile_mode.addItems(('Select ROI tool…', 'Line (px)', 'Rectangle (px)',
                                    'Ellipse / Circle (px)', 'Count 1, 2, 3…'))
        self.profile_mode.currentIndexChanged.connect(self._mode_changed)
        self.pan_button=QtWidgets.QPushButton('Pan / Zoom')
        self.pan_button.setToolTip('Middle-button drag pans the image in any ROI mode')
        self.pan_button.setCheckable(True);self.pan_button.setChecked(True)
        self.pan_button.clicked.connect(self._select_pan)
        self.return_to_pan=QtGui.QShortcut(QtGui.QKeySequence('Esc'),self)
        self.return_to_pan.activated.connect(self._select_pan)
        side.addWidget(self.pan_button)
        side.addWidget(self.profile_mode)
        selection=QtWidgets.QHBoxLayout()
        selection.addWidget(QtWidgets.QLabel('ROI'))
        self.roi_selector=QtWidgets.QComboBox()
        selection.addWidget(self.roi_selector,1)
        self.roi_delete=QtWidgets.QPushButton('Delete ROI')
        selection.addWidget(self.roi_delete)
        side.addLayout(selection)
        self.roi_details=QtWidgets.QLabel('')
        self.roi_details.setWordWrap(True)
        side.addWidget(self.roi_details)
        self.count_total=QtWidgets.QLabel('Count: 0')
        side.addWidget(self.count_total)
        # AnnotationViewBox, graphics handles, and ROI editor come from the
        # same ImagePanel machinery as the ordinary VIEWs.
        self.roi_layer=HighResROIController(self)
        self.measure_viewbox.owner=self.roi_layer
        self.roi_selector.currentIndexChanged.connect(self._roi_selection_changed)
        self.roi_delete.clicked.connect(self._delete_roi)
        edit_row=QtWidgets.QHBoxLayout()
        self.undo_button=QtWidgets.QPushButton('Undo')
        self.redo_button=QtWidgets.QPushButton('Redo')
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        edit_row.addWidget(self.undo_button);edit_row.addWidget(self.redo_button)
        side.addLayout(edit_row)
        width_row=QtWidgets.QHBoxLayout()
        self.width_label=QtWidgets.QLabel('Line width (px)')
        self.line_width=QtWidgets.QSpinBox()
        self.line_width.setRange(1,101)
        self.line_width.setValue(1)
        self.line_width.valueChanged.connect(self._update_measurement)
        width_row.addWidget(self.width_label);width_row.addWidget(self.line_width)
        side.addLayout(width_row)
        self.measurement=QtWidgets.QLabel('Native float32 / uint16, no 8-bit conversion.')
        self.measurement.setWordWrap(True)
        side.addWidget(self.measurement)
        self.profile_plot = pg.PlotWidget()
        self.profile_plot.setBackground('#101820')
        self.profile_plot.setLabel('left','Original value')
        self.profile_plot.setLabel('bottom','Distance',units='px')
        self.profile_curve = self.profile_plot.plot(pen=pg.mkPen('#ffbf47', width=2))
        # No permanently docked narrow plot. Display a resizable graph only on
        # explicit request; its curve still updates as ROI or width changes.
        self.show_profile_button=QtWidgets.QPushButton('Show Line Profile…')
        self.show_profile_button.clicked.connect(self.show_line_profile)
        side.addWidget(self.show_profile_button)
        self.show_profile_button.setVisible(False)
        # ID054: Match the standard VIEW toolbar; Report, TIFF and ImageJ
        # are kept together in the upper-right of the Orthogonal dialog.
        # The buttons can also live in this widget's own upper toolbar when
        # instantiated without an OrthogonalDialog parent.
        self.report_menu=QtWidgets.QToolButton()
        self.report_menu.setObjectName('LOUPE_OrthogonalReport')
        self.report_menu.setText('Report ▾')
        self.report_menu.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.report_menu.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.report_menu.setToolTip('Export a PNG or PDF native-pixel report')
        self.report_menu.setAccessibleName('Report: choose PNG or PDF')
        report_menu=QtWidgets.QMenu(self.report_menu)
        self.png_action=report_menu.addAction('PNG…')
        self.pdf_action=report_menu.addAction('PDF…')
        self.png_action.triggered.connect(lambda:self.export_report('PNG'))
        self.pdf_action.triggered.connect(lambda:self.export_report('PDF'))
        self.png_action.setEnabled(False);self.pdf_action.setEnabled(False)
        self.report_menu.setMenu(report_menu)
        self.report_menu.setEnabled(False)
        self.save_button=QtWidgets.QPushButton('Export TIFF…')
        self.save_button.setObjectName('LOUPE_OrthogonalOutputButton')
        self.save_button.setToolTip('Export the native TIFF and its accompanying JSON metadata')
        self.save_button.setAccessibleName('Export TIFF and JSON metadata')
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.export)
        self.fiji_button=QtWidgets.QPushButton('Open in ImageJ')
        self.fiji_button.setObjectName('LOUPE_OrthogonalOutputButton')
        self.fiji_button.setToolTip('Open the quantitative TIFF in ImageJ/Fiji; TIFF + JSON are exported if required')
        self.fiji_button.setAccessibleName('Open in ImageJ/Fiji')
        self.fiji_button.setEnabled(False)
        self.fiji_button.clicked.connect(self.open_fiji)
        for action_button in (self.report_menu,self.save_button,self.fiji_button):
            action_button.setFixedHeight(40)
            action_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred,
                                        QtWidgets.QSizePolicy.Policy.Fixed)
            action_button.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._native_output_controls=(self.report_menu,self.save_button,self.fiji_button)
        self._output_row=QtWidgets.QHBoxLayout()
        self._output_row.setSpacing(8)
        self._output_row.addStretch(1)
        for action_button in self._native_output_controls:
            self._output_row.addWidget(action_button)
        outer.insertLayout(1,self._output_row)
        side.addStretch(1)
        scroll=QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(sidebar)
        scroll.setMinimumWidth(290)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0,5)
        splitter.setStretchFactor(1,2)
        outer.addWidget(splitter,1)
        footer=QtWidgets.QHBoxLayout()
        self.status=QtWidgets.QLabel('Ready to select a CT dataset')
        footer.addWidget(self.status,1)
        self.progress=QtWidgets.QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(180)
        footer.addWidget(self.progress)
        outer.addLayout(footer)
        self._range_changed()
        self._update_history_buttons()

    def move_output_controls_to(self, target_layout):
        """Mount report / native TIFF / ImageJ in OrthogonalDialog top row.

        Reparent existing controls rather than creating duplicate actions, so
        enabled state, save semantics, and menu signals remain identical.
        """
        for action in self._native_output_controls:
            self._output_row.removeWidget(action)
            target_layout.addWidget(action)
        self._output_row.setEnabled(False)
        self.fiji_button.setText('Open in ImageJ')

    def show_line_profile(self):
        if (self._image_data is None or self._last_profile is None):
            return
        if self._profile_dialog is None:
            dlg=QtWidgets.QDialog(self)
            dlg.setWindowTitle('LOUPE — Native Section Line Profile')
            dlg.resize(920,500)
            dlg.setMinimumSize(520,300)
            layout=QtWidgets.QVBoxLayout(dlg)
            layout.addWidget(self.profile_plot,1)
            self._profile_dialog=dlg
        self._update_measurement()
        self._profile_dialog.show()
        self._profile_dialog.raise_()
        self._profile_dialog.activateWindow()

    def set_source(self, paths, pixel_size_um, x, y, shape_yx=None):
        """Called by OrthogonalDialog only when a preview is ready/changed."""
        if self._busy:
            raise RuntimeError('Cannot change dataset during native-pixel extraction')
        self._paths = tuple(Path(p) for p in paths)
        self._pixel_size_um = pixel_size_um
        self._discard_image()
        self.z_start.setRange(1, len(paths)); self.z_end.setRange(1, len(paths))
        self.z_start.setValue(1); self.z_end.setValue(len(paths))
        from ..tiff_metadata import read_reconstruction_metadata
        verified=read_reconstruction_metadata(self._paths[0])
        native_size=float(verified['pixel_size_um']) if verified is not None else None
        self.z_spacing.setValue(float(pixel_size_um or native_size or 1))
        self.xy_spacing.setValue(float(pixel_size_um or native_size or 1))
        # A calibration explicitly supplied by the parent VIEW wins over a
        # potentially incorrect TIFF header; the user can still revert.
        use_override = pixel_size_um is not None and (native_size is None or
            not math.isclose(float(pixel_size_um), native_size, rel_tol=1e-7, abs_tol=1e-10))
        self.custom_xy.setChecked(use_override)
        self.xy_source.setText('Source: manual / parent VIEW' if use_override else 'Source: TIFF header')
        self._verified_pixel_um=native_size
        if shape_yx is None:
            with tifffile.TiffFile(self._paths[0]) as tif:
                shape_yx = tuple(tif.pages[0].shape)
        self._bounds = {'X':int(shape_yx[1]), 'Y':int(shape_yx[0])}
        self.sync_coordinates(x,y)
        label=(f'Header-verified XY = {native_size:g} µm/px' if native_size
               else 'No verified source pixel calibration')
        if use_override:
            label+=f' · XY override = {float(pixel_size_um):g} µm/px (header not used)'
        self.source_label.setText(f'{len(paths)} CT slices · {self._paths[0].parent.name} · '+label)
        self.generate.setEnabled(True)

    def clear_source(self):
        if self._busy:
            raise RuntimeError('Cannot clear source while extraction is active')
        self._paths = ()
        self._discard_image()
        self.generate.setEnabled(False)
        self.source_label.setText('Waiting for CT preview…')

    def sync_coordinates(self, x, y):
        self._bounds = getattr(self,'_bounds', {'X':None,'Y':None})
        self._axis_changed()
        axis='X' if self.plane.currentIndex()==0 else 'Y'
        new = x if axis=='X' else y
        self.index.setValue(max(1,min(self.index.maximum(),int(new)+1)))

    def select_plane_from_preview(self, plane, x, y):
        self.plane.setCurrentIndex(0 if plane=='YZ' else 1)
        self.sync_coordinates(x,y)

    def _axis_changed(self, *_):
        axis='X' if self.plane.currentIndex()==0 else 'Y'
        self.index_label.setText(f'{axis} (1-based)')
        width = (getattr(self,'_bounds',{}).get(axis) or 1)
        self.index.setRange(1,width)

    def _range_changed(self, *_):
        enabled=not self.all_z.isChecked()
        self.z_start.setEnabled(enabled)
        self.z_end.setEnabled(enabled)

    def _set_busy(self, busy):
        self._busy=busy
        self.generate.setEnabled(not busy and bool(self._paths))
        self.stop_button.setEnabled(busy)
        for w in (self.plane,self.index,self.all_z,self.z_start,self.z_end,self.custom_z,self.z_spacing,self.custom_xy,self.xy_spacing):
            w.setEnabled(not busy and (w not in (self.z_start,self.z_end) or not self.all_z.isChecked())
                and (w is not self.z_spacing or self.custom_z.isChecked())
                and (w is not self.xy_spacing or self.custom_xy.isChecked()))
        self.busy_changed.emit(busy)

    def start(self):
        if not self._paths or self._busy:
            return
        start = 0 if self.all_z.isChecked() else self.z_start.value()-1
        stop = len(self._paths) if self.all_z.isChecked() else self.z_end.value()
        if not 0 <= start < stop <= len(self._paths):
            QtWidgets.QMessageBox.warning(self,'Native Section','Z start must not exceed Z end.')
            return
        self._discard_image()
        self._job_id+=1
        token=self._job_id
        self._cancel=threading.Event()
        self._set_busy(True)
        self.progress.setValue(0)
        self.status.setText('Validating original TIFF headers…')
        plane='YZ' if self.plane.currentIndex()==0 else 'ZX'
        native_idx=self.index.value()-1
        paths=tuple(self._paths)
        # An explicit XY override takes priority; otherwise validate TIFF headers.
        xy_um=self.xy_spacing.value() if self.custom_xy.isChecked() else None
        z_um=self.z_spacing.value() if self.custom_z.isChecked() else None
        self.xy_source.setText('Source: manual XY override' if xy_um is not None else 'Source: TIFF header')
        cancel=self._cancel
        temp_folder=self._temp.name

        def run():
            try:
                logger().info('[NATIVE_STAGE] job=%s scan.begin plane=%s z_count=%d', token, plane, stop-start)
                series=scan_series(paths, pixel_size_um=xy_um, cancelled=cancel.is_set,
                    on_progress=lambda n,total:self._signals.progress.emit(token,'Scanning headers',n,total))
                if series.pixel_size_um is None and self._pixel_size_um is not None:
                    # Don't silently equate panel display calibration with verified
                    # original data. Quantitative intensity remains valid but
                    # no physical dimensions are recorded in the TIFF.
                    pass
                logger().info('[NATIVE_STAGE] job=%s scan.done shape=%s dtype=%s', token, series.shape, series.dtype)
                result=extract_plane(series,plane=plane,fixed_index=native_idx,
                    z_start=start,z_stop=stop,z_spacing_um=z_um,
                    output_dir=temp_folder,cancelled=cancel.is_set,
                    on_progress=lambda n,total:self._signals.progress.emit(token,'Extracting original pixels',n,total))
                if cancel.is_set():
                    raise ExtractionCancelled('Stopped')
                logger().info('[NATIVE_STAGE] job=%s extract.done output_shape=%s',token,result.shape)
                data=tifffile.imread(result.tiff_path)
                logger().info('[NATIVE_STAGE] job=%s tiff.read.done shape=%s dtype=%s',token,data.shape,data.dtype)
                if cancel.is_set():
                    raise ExtractionCancelled('Stopped')
                self._signals.completed.emit(token,result,data)
            except ExtractionCancelled:
                logger().info('[NATIVE_STAGE] job=%s cancelled', token)
                self._signals.failed.emit(token,'Stopped by operator',True)
            except Exception as exc:
                logger().exception('[NATIVE_STAGE] job=%s failed', token)
                self._signals.failed.emit(token,str(exc),False)
        # Persist the request before the worker can start (or crash).
        log_action('Native Section orthogonal requested',plane=plane,fixed_index=native_idx,
                   z_start=start,z_stop=stop,frames=len(paths))
        self._pool.submit(run)

    def stop(self):
        if self._cancel is not None and self._busy:
            self._cancel.set()
            self.status.setText('Stopping native-pixel extraction…')
            self.stop_button.setEnabled(False)

    def _on_progress(self, token, stage, n, total):
        if token != self._job_id or not self._busy:
            return
        self.status.setText(f'{stage}: {n}/{total} ({round(n/total*100)}%)')
        self.progress.setValue(int(n*100/total))

    def _on_complete(self,token,result,data):
        if token!=self._job_id:
            return
        if self._cancel is not None and self._cancel.is_set():
            self._discard_files(result)
            self._on_failed(token,'Stopped by operator',True)
            return
        logger().info('[NATIVE_STAGE] job=%s gui.install.begin', token)
        self._result=result
        self._image_data=data
        self._scale=(result.metadata.get('horizontal_spacing_um'), result.metadata.get('vertical_z_spacing_um'))
        lower,upper=display_limits(data)
        logger().info('[NATIVE_STAGE] job=%s gui.image.set.begin',token)
        self.image.setImage(data,autoLevels=False,levels=(lower,upper))
        logger().info('[NATIVE_STAGE] job=%s gui.image.set.done',token)
        self.image.setRect(QtCore.QRectF(0,0,data.shape[1],data.shape[0]))
        self.plot.getViewBox().autoRange(padding=0.015)
        self._set_busy(False)
        self.progress.setValue(100)
        self.save_button.setEnabled(True)
        self.fiji_button.setEnabled(True)
        self.report_menu.setEnabled(True)
        self.png_action.setEnabled(True);self.pdf_action.setEnabled(True)
        self._undo_stack=[];self._redo_stack=[]
        logger().info('[NATIVE_STAGE] job=%s gui.roi.set.begin',token)
        self.roi_layer.set_image(data)
        logger().info('[NATIVE_STAGE] job=%s gui.roi.set.done',token)
        self._update_measurement()
        z0=result.metadata['z_start_zero_based_inclusive'];z1=result.metadata['z_stop_zero_based_exclusive']
        self.details.setText(f"{result.metadata['plane']} · {result.metadata['fixed_axis']}="
            f"{result.metadata['fixed_index_px']+1} px (GUI) · "
            f"Z slices {z0+1}–{z1} · {data.shape[1]}×{data.shape[0]} · {data.dtype}\n"
            f"XY={self._scale[0]} µm/px · Z={self._scale[1]} µm/px "
            f"({result.metadata['z_calibration_source']})")
        self.status.setText(f'Native Section ready in {result.elapsed_seconds:.2f} s · not saved permanently')
        self._update_scale_bar()
        log_action('Native Section orthogonal ready',plane=result.metadata['plane'],
                   shape=list(data.shape),seconds=round(result.elapsed_seconds,3))

    def _on_failed(self,token,error,cancelled):
        if token!=self._job_id:
            return
        self._set_busy(False)
        self.status.setText(error if cancelled else 'Native Section extraction failed: '+error)
        if not cancelled and not self._closed:
            QtWidgets.QMessageBox.warning(self,'Native Section extraction',error)
        log_action('Native Section orthogonal cancelled' if cancelled else 'Native Section orthogonal failed',
                   reason=error[:200])

    def _discard_files(self, result):
        for file in (result.tiff_path,result.metadata_path):
            Path(file).unlink(missing_ok=True)

    def _discard_image(self):
        self.roi_layer.set_image(None)
        self.profile_curve.setData([],[])
        if self._profile_dialog is not None:
            self._profile_dialog.hide()
        self.image.clear()
        self._image_data=None
        self._scale=(None,None)
        self.bar.hide();self.bar_label.hide()
        old=self._result
        self._result=None
        self._exported_path=None
        self.save_button.setEnabled(False)
        self.fiji_button.setEnabled(False)
        self.report_menu.setEnabled(False)
        self.png_action.setEnabled(False);self.pdf_action.setEnabled(False)
        self._last_profile=None
        self._undo_stack=[]; self._redo_stack=[]
        self._update_history_buttons()
        if old is not None:
            self._discard_files(old)

    # ImagePanel's annotation editor is shared via HighResROIController.
    # ROI choice only changes the drawing mode; it never creates an ROI until
    # the user drags on the image, just like the ordinary VIEW.
    space_pan_active=False

    def set_active_panel(self, panel):
        pass  # Only one quantitative canvas in this tab.

    def record_annotation_change(self, panel, key, before, after, **_):
        if before==after:return
        self._undo_stack.append((copy.deepcopy(before),copy.deepcopy(after)))
        self._undo_stack=self._undo_stack[-100:]
        self._redo_stack.clear()
        self._update_history_buttons()

    def _select_pan(self):
        self.profile_mode.setCurrentIndex(0)
        self.pan_button.setChecked(True)

    def _mode_changed(self, *_):
        mode=self.profile_mode.currentIndex()
        self.pan_button.setChecked(mode==0)
        self.width_label.setVisible(mode==1)
        self.line_width.setVisible(mode==1)
        self.show_profile_button.setVisible(mode==1 and self._image_data is not None)
        self.plot.setCursor(QtCore.Qt.CursorShape.ArrowCursor if mode==0
                            else QtCore.Qt.CursorShape.CrossCursor)
        self.roi_layer.update_annotation_styles()
        self._update_measurement()

    def _roi_selection_changed(self, index):
        self.roi_layer.roi_selection_changed(index)
        self._update_measurement()

    def _delete_roi(self):
        self.roi_layer.delete_selected_annotation()

    def _update_history_buttons(self):
        if hasattr(self,'undo_button'):
            self.undo_button.setEnabled(bool(self._undo_stack))
            self.redo_button.setEnabled(bool(self._redo_stack))

    def undo(self):
        if not self._undo_stack:return
        before,after=self._undo_stack.pop()
        self._redo_stack.append((before,after))
        self.roi_layer.apply_annotations_from_history('high_res_local',before)
        self._update_measurement()
        self._update_history_buttons()

    def redo(self):
        if not self._redo_stack:return
        before,after=self._redo_stack.pop()
        self._undo_stack.append((before,after))
        self.roi_layer.apply_annotations_from_history('high_res_local',after)
        self._update_measurement()
        self._update_history_buttons()

    def _update_measurement(self, *_):
        if not hasattr(self,'roi_layer'):return
        layer=self.roi_layer
        item=layer.get_annotation(layer.selected_annotation_id)
        arr=self._image_data
        self.show_profile_button.setVisible(bool(arr is not None and item is not None and
                                                  item['type']=='line'))
        if arr is None:
            self.measurement.setText('Generate a native-pixel section to measure.')
            return
        if item is None:
            self.profile_curve.setData([],[])
            self._last_profile=None
            self.measurement.setText(f'Count: {sum(a["type"]=="count" for a in layer.visible_annotations())} · '
                                     'Drag to create ROI; click an existing ROI to edit.')
            return
        if item['type']=='line':
            a,b=item['start'],item['end']
            width=self.line_width.value()
            dist,vals=sample_thick_line(arr,a,b,width=width)
            self.profile_curve.setData(dist,vals)
            self._last_profile=(dist,vals)
            physical=physical_dimensions(item,layer.calibration())
            length=math.hypot(b[0]-a[0],b[1]-a[1])
            self.measurement.setText(f'Length: {length:.2f} px'+
                (f' / {physical["length"]:.3f} µm' if physical else '')+
                f' · Line width {width} px (bilinear width average)')
        else:
            self.profile_curve.setData([],[])
            self._last_profile=None
            self.measurement.setText(caption(item,layer.calibration())+
                (' · Rectangle mean not measured' if item['type']=='rect' else ''))

    def _report_record(self):
        if self._image_data is None or self._result is None:return None
        sx,sz=self._scale
        plane=self._result.metadata['plane']
        z0=self._result.metadata['z_start_zero_based_inclusive']
        z1=self._result.metadata['z_stop_zero_based_exclusive']
        metadata=(f'Native {plane} orthogonal section | Z slices {z0+1}–{z1} | '
                  f'horizontal spacing: {sx} µm/px | Z spacing: {sz} µm/slice; '
                  'image top = minimum numeric Z index; physical orientation unverified.')
        items=self.roi_layer.all_items()
        selected=self.roi_layer.get_annotation(self.roi_layer.selected_annotation_id)
        record={'side':'Native Section '+plane,'path':str(self._paths[0]),
                'slice':f'{z0+1}–{z1}','image':self._image_data,
                'levels':tuple(self.image.levels), 'annotations':items,
                'calibration':{'enabled':bool(sx),'pixel_size':sx or 1.,'unit':'µm'},
                'show_scale_bar':bool(sx),'vertical_pixel_size_um':sz,'profile':None,
                'orthogonal_provenance':orthogonal_provenance_lines(self._result.metadata)}
        if selected and selected['type']=='line':
            record['profile_line']=(selected['start'],selected['end'])
            if self._last_profile is not None:
                record['profile']={'profile':self._last_profile}
        return record,metadata

    def export_report(self,kind):
        data=self._report_record()
        if data is None:return
        record,details=data
        from ..report import export_pdf_report,export_png_report
        filename='LOUPE_Orthogonal_NativeSection_'+self._result.metadata['plane']+'.'+kind.lower()
        chosen,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export Native Section '+kind,
            str(self._paths[0].parent.parent/'LOUPE_Exports'/filename),
            'PNG Image (*.png)' if kind=='PNG' else 'PDF Document (*.pdf)')
        if not chosen:return
        path=Path(chosen)
        if path.suffix.lower()!='.'+kind.lower():
            path=path.with_suffix('.'+kind.lower())
        if path.exists():
            QtWidgets.QMessageBox.warning(self,'Report already exists','Select a new filename. Existing reports are not overwritten.')
            return
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            func=export_pdf_report if kind=='PDF' else export_png_report
            func(path,[record],title='LOUPE · Native Section',comment=details)
            self.status.setText(kind+' Native Section report saved: '+str(path))
            log_action('Orthogonal native-pixel report exported',format=kind,filename=path.name)
        except Exception as exc:
            path.unlink(missing_ok=True)
            QtWidgets.QMessageBox.warning(self,'Report failed',str(exc))

    def _mouse_moved(self, scene):
        if self._image_data is None or not self.plot.getViewBox().sceneBoundingRect().contains(scene):
            return
        p=self.plot.getViewBox().mapSceneToView(scene)
        x=int(math.floor(p.x()));z_local=int(math.floor(p.y()))
        z0=self._result.metadata['z_start_zero_based_inclusive']
        h,w=self._image_data.shape
        if 0<=x<w and 0<=z_local<h:
            self.pixel_label.setText(f'Native X/Y column={x+1} px · source Z slice={z0+z_local+1} · '
                                     f'original value={float(self._image_data[z_local,x]):.9g}')

    def _update_scale_bar(self,*_):
        if self._image_data is None or not self._scale[0]:
            self.bar.hide();self.bar_label.hide();return
        (xmin,xmax),(ymin,ymax)=self.plot.getViewBox().viewRange()
        spec=scale_bar_spec((xmin,xmax),self._scale[0])
        if spec is None:return
        length_px,length_um=spec
        x=xmin+(xmax-xmin)*.07
        y=ymax-(ymax-ymin)*.08
        self.bar.setData([x,x+length_px],[y,y])
        self.bar_label.setText(scale_bar_label(length_um))
        self.bar_label.setPos(x,y-(ymax-ymin)*.016)
        self.bar.show();self.bar_label.show()

    def export(self):
        if self._busy or self._result is None:
            return None
        meta=self._result.metadata
        origin=self._paths[0].parent
        target_dir = origin.parent if origin.name.lower()=='rec' else origin
        suggestion=target_dir/'LOUPE_Exports'/self._result.tiff_path.name
        suggestion.parent.mkdir(parents=True,exist_ok=True)
        chosen,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export native-pixel TIFF',str(suggestion),
                                                        'TIFF (*.tif *.tiff)')
        if not chosen:return None
        path=Path(chosen)
        if path.suffix.lower() not in ('.tif','.tiff'):
            path=path.with_suffix('.tif')
        sidecar=path.with_suffix('.json')
        if path.exists() or sidecar.exists():
            QtWidgets.QMessageBox.warning(self,'Existing export',
                'This TIFF or JSON already exists. Choose a different filename; existing data will not be overwritten.')
            return None
        tmps=[]
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            for src,dst in ((self._result.tiff_path,path),(self._result.metadata_path,sidecar)):
                tmp=dst.with_name('.'+dst.stem+'.'+uuid.uuid4().hex+'.tmp')
                shutil.copyfile(src,tmp)
                tmps.append((tmp,dst))
            # Publish with O_EXCL, avoiding overwriting an export created concurrently.
            published=[]
            try:
                for tmp,dst in tmps:
                    fd=os.open(dst, os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                    os.close(fd); published.append(dst)
                    os.replace(tmp,dst)
            except BaseException:
                for dst in published:dst.unlink(missing_ok=True)
                raise
            self._exported_path=path
            self.status.setText('Exported: '+str(path))
            log_action('Native Section TIFF exported',file=path.name,plane=meta['plane'])
            return path
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self,'Export failed',str(exc))
            return None
        finally:
            for tmp,_ in tmps:tmp.unlink(missing_ok=True)

    def open_fiji(self):
        if self._result is None or self._busy:return
        # Fiji must not reference disposable temporary files. Require a real export.
        path=self._exported_path
        if path is None or not path.is_file():
            path=self.export()
        if path is None:return
        host=self.window().parent()
        if host is None or not hasattr(host,'_imagej_executable'):
            QtWidgets.QMessageBox.warning(self,'Fiji','LOUPE main window is unavailable.')
            return
        configured=host._imagej_executable()
        if configured is None:return
        from ..imagej_bridge import imagej_current_macro
        from ..fiji_transfer import make_transfer
        from ..measurements import create_annotation
        try:
            # The shared ROI layer stores coordinates local to the exported
            # 2D section; Fiji receives them without a second Z correction.
            rois=self.roi_layer.all_items()
            sx,sz=self._scale
            cal=({'enabled':True,'unit':'µm','pixel_size':sx,'pixel_size_y':sz,
                  'source':'tiff_header'} if sx is not None and sz is not None
                  else {'enabled':False})
            transfer=make_transfer(annotations=rois,
                selected_id=self.roi_layer.selected_annotation_id,
                width_px=self.line_width.value(),
                display_limits=self.image.levels,calibration=cal)
            host._launch_imagej(configured[0], imagej_current_macro(path),
                                source_paths=[str(path)],transfer=transfer)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self,'Fiji',str(exc))

    def dispose(self):
        """Only call when not busy; all exported TIFFs remain untouched."""
        if self._closed:
            return
        self._closed=True
        self._pool.shutdown(wait=True, cancel_futures=True)
        self._discard_image()
        self._temp.cleanup()
