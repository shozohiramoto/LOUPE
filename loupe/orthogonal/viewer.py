"""On-demand orthogonal preview dialog. Never mutates source images or 2D state.

XY is shown from a full-resolution TIFF on demand; YZ/ZX use a bounded,
decimated 3D cache and are explicitly labelled non-quantitative.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime
import os
import tempfile
import threading

import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
import pyqtgraph as pg
from .cache import build_preview, cache_metadata, cache_paths, preview_planes, validate_ct_series
from .scalebar import scale_bar_spec, scale_bar_label
from .high_resolution_widget import HighResolutionWidget
from ..io import load_frame, display_limits
from ..output_paths import suggested_path
from ..version import APP_VERSION



class _WorkerSignals(QtCore.QObject):
    progress = QtCore.Signal(int, int)
    ready = QtCore.Signal(object, object)
    error = QtCore.Signal(str)
    xy_ready = QtCore.Signal(int, object)


class OrthogonalDialog(QtWidgets.QDialog):
    """Lazy workspace: one bounded-cache producer + one XY reader, cancellable."""
    def __init__(self, paths, *, initial_slice=0, pixel_size_um=None, initial_xy=None,
                 parent=None, view_sources=None, selected_view=0):
        super().__init__(parent)
        # Each record: {label, paths, slice, pixel_size_um, current}.
        self._view_sources = view_sources or [{
            'label':'VIEW 1','paths':paths,'slice':initial_slice,
            'pixel_size_um':pixel_size_um,'current':initial_xy}]
        self._selected_view = selected_view
        self.paths = validate_ct_series(paths)
        self.setWindowTitle('LOUPE — Orthogonal View (Preview)')
        self.resize(1120, 800)
        self.setMinimumSize(710, 470)
        self._cancel = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._signals = _WorkerSignals(self)
        self._signals.progress.connect(self._on_progress)
        self._signals.ready.connect(self._on_ready)
        self._signals.error.connect(self._on_error)
        self._signals.xy_ready.connect(self._on_xy_ready)
        self._volume = None
        self._metadata = None
        self._selected_z = max(0, min(len(paths)-1, int(initial_slice)))
        self._xy_token = 0
        self._last_xy_slice = -1
        self._initial_xy = (np.asarray(initial_xy) if initial_xy is not None else None)
        self._pixel_size_um = pixel_size_um
        self._show_scale_bar = bool(self._view_sources[selected_view].get('show_scale_bar', False))
        self._last_report_dir = QtCore.QSettings('BL09W', 'LOUPE').value('orthogonal_report_dir', '')
        self._plots = {}
        self._images = {}
        self._lines = {}
        self._scale_bars = {}
        self._closing_for_high_res = False
        self._build_ui()
        self._xy_debounce=QtCore.QTimer(self)
        self._xy_debounce.setSingleShot(True)
        self._xy_debounce.setInterval(110)
        self._xy_debounce.timeout.connect(lambda:self._read_xy(self._sliders['Z'].value()))
        # No work is started for non-selected datasets. A previous valid cache
        # opens without scanning image data.
        # Keep title bar, taskbar and window frame inside the usable desktop area.
        screen=self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            area=screen.availableGeometry()
            self.setMaximumHeight(max(470,min(1010, area.height()-70)))
            self.resize(min(self.width(),max(710,area.width()-16)), min(self.height(),self.maximumHeight()))
        self._start_preview()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel('<b>Orthogonal View</b>  ·  Preview navigation / quantitative Native Section from original CT pixels')
        layout.addWidget(heading)
        navigation=QtWidgets.QHBoxLayout()
        navigation.addWidget(QtWidgets.QLabel('Dataset:'))
        self.view_selector=QtWidgets.QComboBox(self)
        for idx,record in enumerate(self._view_sources):
            label=record.get('label',f'VIEW {idx+1}')
            self.view_selector.addItem(label,idx)
        self.view_selector.setCurrentIndex(self._selected_view)
        self.view_selector.currentIndexChanged.connect(self._change_view)
        navigation.addWidget(self.view_selector)
        navigation.addStretch(1)
        # ID054: Standard VIEW-style Report drop-down at the upper-right.
        # The preview report contains decimated navigation planes, NEVER TIFF
        # output. Native Section has its own independent quantitative actions.
        self.preview_report_button=QtWidgets.QToolButton(self)
        self.preview_report_button.setObjectName('LOUPE_OrthogonalReport')
        self.preview_report_button.setText('Report ▾')
        self.preview_report_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.preview_report_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.preview_report_button.setAccessibleName('Preview report: choose PNG or PDF')
        self.preview_report_button.setToolTip('Preview report: XY is native; YZ/ZX are navigation-only. No quantitative TIFF output.')
        preview_report_menu=QtWidgets.QMenu(self.preview_report_button)
        self.preview_png_action=preview_report_menu.addAction('PNG…')
        self.preview_pdf_action=preview_report_menu.addAction('PDF…')
        self.preview_png_action.triggered.connect(lambda:self._export_report('PNG'))
        self.preview_pdf_action.triggered.connect(lambda:self._export_report('PDF'))
        self.preview_report_button.setMenu(preview_report_menu)
        self.preview_report_button.setFixedHeight(40)
        self.preview_report_button.setEnabled(False)
        navigation.addWidget(self.preview_report_button)
        layout.addLayout(navigation)
        self.comment_edit=QtWidgets.QPlainTextEdit(self)
        self.comment_edit.setPlaceholderText('Comments included in PNG/PDF report (optional)')
        self.comment_edit.setFixedHeight(60)
        self.comment_edit.setToolTip('Notes are included in the exported report, not in the CT data.')
        self.tabs = QtWidgets.QTabWidget(self)
        preview = QtWidgets.QWidget(self)
        preview_layout = QtWidgets.QVBoxLayout(preview)
        preview_layout.addWidget(QtWidgets.QLabel('PREVIEW — YZ / ZX are for navigation only. No quantitative ROI measurements.'))
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(6)
        for name, row, col, h_label, v_label in (
                ('XY',0,0,'X','Y'), ('YZ',0,1,'Y','Z'), ('ZX',1,0,'X','Z')):
            cell = QtWidgets.QWidget()
            cell_layout = QtWidgets.QVBoxLayout(cell)
            cell_layout.setContentsMargins(0,0,0,0)
            cell_layout.addWidget(QtWidgets.QLabel(f'{name}  ({h_label} ↔, {v_label} ↕)'))
            plot = pg.PlotWidget()
            plot.setBackground('#101820')
            plot.setAspectLocked(True)
            plot.invertY(True)
            plot.hideAxis('bottom');plot.hideAxis('left')
            plot.setMinimumSize(100,100)
            image = pg.ImageItem(axisOrder='row-major')
            plot.addItem(image)
            vx=pg.InfiniteLine(angle=90,pen=pg.mkPen('#ffbf47',width=1))
            vy=pg.InfiniteLine(angle=0,pen=pg.mkPen('#ffbf47',width=1))
            vx.setZValue(25);vy.setZValue(25)
            plot.addItem(vx,ignoreBounds=True)
            plot.addItem(vy,ignoreBounds=True)
            self._images[name]=image
            self._plots[name]=plot
            self._lines[name]=(vx,vy)
            # These items use source-pixel coordinates, like the images and
            # crosshairs.  ignoreBounds prevents a bar shifting the auto-fit.
            bar = pg.PlotCurveItem(pen=pg.mkPen('#ffffff', width=3))
            bar.setZValue(60)
            label = pg.TextItem(color='#ffffff', anchor=(0, 1),
                                fill=pg.mkBrush(8, 16, 27, 210))
            label.setZValue(61)
            plot.addItem(bar, ignoreBounds=True)
            plot.addItem(label, ignoreBounds=True)
            self._scale_bars[name] = (bar, label)
            plot.getViewBox().sigRangeChanged.connect(
                lambda *_, plane=name: self._update_scale_bar(plane))
            plot.scene().sigMouseClicked.connect(lambda event, key=name:self._clicked(event,key))
            cell_layout.addWidget(plot,1)
            grid.addWidget(cell,row,col)
        grid.setColumnStretch(0,1);grid.setColumnStretch(1,1)
        grid.setRowStretch(0,1);grid.setRowStretch(1,1)
        controls=QtWidgets.QGroupBox('Crosshair · native pixel coordinates')
        v=QtWidgets.QVBoxLayout(controls)
        self._sliders={}
        self._positions={}
        for axis in ('X','Y','Z'):
            r=QtWidgets.QHBoxLayout()
            r.addWidget(QtWidgets.QLabel(axis))
            sl=QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
            sl.setTracking(True)
            sl.valueChanged.connect(lambda _, a=axis:self._positions_changed(a))
            display=QtWidgets.QLabel('—')
            display.setFixedWidth(140)
            r.addWidget(sl,1);r.addWidget(display)
            v.addLayout(r)
            self._sliders[axis]=sl
            self._positions[axis]=display
        self._sliders['Z'].setTracking(False)  # no I/O during thumb drag
        self._sliders['Z'].setRange(0,len(self.paths)-1)
        self._sliders['Z'].setValue(self._selected_z)
        self._sliders['X'].setEnabled(False)
        self._sliders['Y'].setEnabled(False)
        v.addWidget(QtWidgets.QLabel('Z spacing = XY pixel size (isotropic CT reconstruction assumption).'))
        buttons = QtWidgets.QHBoxLayout()
        self.hr_yz = QtWidgets.QPushButton('Generate NATIVE SECTION · YZ (X fixed)')
        self.hr_zx = QtWidgets.QPushButton('Generate NATIVE SECTION · ZX (Y fixed)')
        for button, plane in ((self.hr_yz,'YZ'),(self.hr_zx,'ZX')):
            button.setEnabled(False)
            button.clicked.connect(lambda _=False,p=plane:self._select_high_res(p))
            buttons.addWidget(button)
        v.addLayout(buttons)
        grid.addWidget(controls,1,1)
        preview_layout.addLayout(grid,1)
        preview_layout.addWidget(self.comment_edit)
        self.tabs.addTab(preview,'Preview')
        self.hr_widget = HighResolutionWidget(self)
        self.hr_widget.busy_changed.connect(self._high_res_busy_changed)
        # Reuse the exact same top-right output position for both tabs.
        # Parenting the native actions into the dialog avoids covering ROI
        # controls with a tall bottom-right Output dock.
        self.hr_widget.move_output_controls_to(navigation)
        self.tabs.addTab(self.hr_widget,'Native Section')
        self.tabs.setTabToolTip(self.tabs.indexOf(self.hr_widget),
            'Full-resolution quantitative YZ/ZX cut from original CT TIFFs; unrelated to detector High-reso')
        self.tabs.currentChanged.connect(self._tab_changed)
        self._tab_changed(self.tabs.currentIndex())
        layout.addWidget(self.tabs,1)
        bottom=QtWidgets.QHBoxLayout()
        self._status=QtWidgets.QLabel('Preparing preview…')
        bottom.addWidget(self._status,1)
        self._bar=QtWidgets.QProgressBar()
        self._bar.setRange(0,100)
        self._bar.setMaximumWidth(185)
        bottom.addWidget(self._bar)
        cancel=QtWidgets.QPushButton('Close / Cancel')
        cancel.clicked.connect(self.close)
        bottom.addWidget(cancel)
        layout.addLayout(bottom)
        self._updating=False

    def _tab_changed(self,index):
        self.setWindowTitle('LOUPE — Orthogonal View (Preview)' if index==0 else 'LOUPE — Orthogonal View (Native Section)')
        # Preserve the upper-right position for both modes while making the
        # report's source unambiguous. Never export a decimated preview as TIFF.
        is_preview=(index==0)
        self.preview_report_button.setVisible(is_preview)
        for action in (self.hr_widget.report_menu,
                       self.hr_widget.save_button,self.hr_widget.fiji_button):
            action.setVisible(not is_preview)

    def _change_view(self,index):
        if index < 0 or index == self._selected_view:return
        if self._volume is None or self.hr_widget.busy:
            # Dataset switch is disabled while preview generation is unfinished.
            return
        spec=self._view_sources[index]
        try:
            paths=validate_ct_series(spec['paths'])
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self,'Unavailable CT series',str(exc))
            self.view_selector.blockSignals(True)
            self.view_selector.setCurrentIndex(self._selected_view)
            self.view_selector.blockSignals(False)
            return
        self.hr_widget.clear_source()
        self.hr_yz.setEnabled(False);self.hr_zx.setEnabled(False)
        self._selected_view=index
        self.paths=paths
        self._pixel_size_um=spec.get('pixel_size_um')
        self._show_scale_bar=bool(spec.get('show_scale_bar', False))
        self._selected_z=max(0,min(len(paths)-1,int(spec.get('slice',0))))
        self._initial_xy=spec.get('current')
        self._last_xy_slice=-1
        self._xy_token+=1 # Cancel stale XY results.
        self._xy_debounce.stop()
        self._volume=None
        self._metadata=None
        for name in ('XY','YZ','ZX'):
            self._images[name].clear()
            self._update_scale_bar(name)
        for name in ('X','Y'):
            self._sliders[name].setEnabled(False)
        self._sliders['Z'].blockSignals(True)
        self._sliders['Z'].setRange(0,len(paths)-1)
        self._sliders['Z'].setValue(self._selected_z)
        self._sliders['Z'].blockSignals(False)
        self._status.setText('Preparing '+spec.get('label',f'VIEW {index+1}')+'…')
        self._bar.setValue(0)
        # Keep title bar, taskbar and window frame inside the usable desktop area.
        screen=self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            area=screen.availableGeometry()
            self.setMaximumHeight(max(470,min(1010, area.height()-70)))
            self.resize(min(self.width(),max(710,area.width()-16)), min(self.height(),self.maximumHeight()))
        self._start_preview()

    def _start_preview(self):
        self.view_selector.setEnabled(False)
        self.preview_report_button.setEnabled(False)
        def task():
            try:
                m, path=build_preview(self.paths,
                    on_progress=lambda n,total:self._signals.progress.emit(n,total),
                    cancelled=self._cancel.is_set)
                if not self._cancel.is_set():self._signals.ready.emit(m,str(path))
            except InterruptedError:
                pass
            except Exception as exc:
                if not self._cancel.is_set():self._signals.error.emit(str(exc))
        self._pool.submit(task)

    def _on_progress(self,n,total):
        self._bar.setValue(int(100*n/total))
        self._status.setText(f'Building preview cache: {n} / {total} source slices…')

    def _on_error(self,msg):
        self._status.setText('Preview unavailable: '+msg)
        self.view_selector.setEnabled(True)
        QtWidgets.QMessageBox.warning(self,'Orthogonal preview',msg)

    def _on_ready(self,m,path):
        if self._cancel.is_set():return
        self._volume=np.load(path, mmap_mode='r', allow_pickle=False)
        self._metadata=m
        h,w=m['source_shape']
        for axis, maximum in [('X',w-1),('Y',h-1)]:
            self._sliders[axis].setRange(0,maximum)
            self._sliders[axis].setValue(maximum//2)
            self._sliders[axis].setEnabled(True)
        self._bar.setValue(100)
        self.view_selector.setEnabled(True)
        self.preview_report_button.setEnabled(True)
        self.hr_widget.set_source(self.paths,self._pixel_size_um,
                                  self._sliders['X'].value(),self._sliders['Y'].value(),
                                  shape_yx=self._metadata['source_shape'])
        self.hr_yz.setEnabled(True);self.hr_zx.setEnabled(True)
        self._status.setText(f'Preview ready | {self._volume.shape} | '
                             f'{self._volume.nbytes / 2**20:.1f} MiB cache | source is read-only')
        self._render()
        self._read_xy(self._selected_z)

    def _nearest(self,axis,value):
        values=np.asarray(self._metadata[f'samples_{axis}'])
        return int(np.argmin(np.abs(values-float(value))))

    def _set_image(self,name,arr,rect):
        image=self._images[name]
        lo,hi=display_limits(arr)
        image.setImage(arr,autoLevels=False,levels=(lo,hi))
        image.setRect(QtCore.QRectF(*rect))

    def _render(self):
        if self._volume is None:return
        x,y,z=(self._sliders[k].value() for k in ('X','Y','Z'))
        xi,yi,zi=(self._nearest(a,v) for a,v in zip('xyz',(x,y,z)))
        xy,yz,zx=preview_planes(self._volume,xi,yi,zi)
        h,w=self._metadata['source_shape'];depth=len(self.paths)
        # The XY original-resolution image is loaded separately and replaces
        # the reduced preview as soon as it becomes available.
        if self._last_xy_slice != z:
            self._set_image('XY',xy,(0,0,w,h))
        self._set_image('YZ',yz,(0,0,h,depth))
        self._set_image('ZX',zx,(0,0,w,depth))
        for key,(horiz,vertical) in {'XY':(x,y),'YZ':(y,z),'ZX':(x,z)}.items():
            u,v=self._lines[key];u.setValue(horiz);v.setValue(vertical)
        units = f'  ({self._pixel_size_um:g} µm/px)' if self._pixel_size_um else ''
        for name,value in zip(('X','Y','Z'),(x,y,z)):
            self._positions[name].setText(f'{value+1} px' if name!='Z' else f'slice {value+1}/{depth}')
        if units:
            self._positions['X'].setToolTip(units)
            self._positions['Y'].setToolTip(units)
            self._positions['Z'].setToolTip('Z spacing'+units)
        for key in ('YZ','ZX'):
            self._plots[key].getViewBox().autoRange(padding=0.02)
        if self._last_xy_slice != z:
            self._plots['XY'].getViewBox().autoRange(padding=0.02)
        for plane in ('XY','YZ','ZX'):
            self._update_scale_bar(plane)

    def _update_scale_bar(self, name):
        """View-relative 1/2/5 scale bar; preview decimation changes no units."""
        if name not in self._scale_bars:
            return
        bar, label = self._scale_bars[name]
        valid = (self._show_scale_bar and self._volume is not None
                 and self._pixel_size_um is not None and self._pixel_size_um > 0)
        bar.setVisible(valid)
        label.setVisible(valid)
        if not valid:
            return
        (xmin,xmax),(ymin,ymax) = self._plots[name].getViewBox().viewRange()
        spec = scale_bar_spec((xmin, xmax), self._pixel_size_um)
        if spec is None or ymax <= ymin:
            bar.hide();label.hide()
            return
        span = xmax-xmin
        length_pixels, length_um = spec
        left = xmin+span*0.07
        # All plots invert the Y axis: native +Y is visually downward.
        y = ymax-(ymax-ymin)*0.08
        bar.setData([left, left+length_pixels], [y, y])
        label.setText(scale_bar_label(length_um))
        label.setPos(left, y-(ymax-ymin)*0.018)

    def _positions_changed(self,axis):
        if self._volume is None:return
        self._render()
        if axis in ('X','Y') and not self.hr_widget.busy:
            self.hr_widget.sync_coordinates(self._sliders['X'].value(),
                                            self._sliders['Y'].value())
        if axis=='Z':self._xy_debounce.start()

    def _read_xy(self,z):
        if self._volume is None or self._cancel.is_set():return
        self._xy_token+=1
        token=self._xy_token
        # First slice reuses the existing full-resolution display array.
        if z==self._selected_z and self._initial_xy is not None:
            self._on_xy_ready(token,self._initial_xy)
            self._initial_xy=None
            return
        path=self.paths[z]
        def task():
            try:
                arr=load_frame(path)
                if not self._cancel.is_set():self._signals.xy_ready.emit(token,arr)
            except Exception as exc:
                if not self._cancel.is_set():self._signals.error.emit(f'XY slice: {exc}')
        self._pool.submit(task)

    def _on_xy_ready(self,token,arr):
        if self._cancel.is_set() or token!=self._xy_token:return
        if tuple(arr.shape)!=tuple(self._metadata['source_shape']):
            self._on_error('XY slice dimensions changed from those of the preview')
            return
        h,w=arr.shape
        self._set_image('XY',arr,(0,0,w,h))
        self._last_xy_slice=self._sliders['Z'].value()

    def _clicked(self,event,key):
        if self._volume is None or event.button()!=QtCore.Qt.MouseButton.LeftButton:return
        plot=self._plots[key]
        if not plot.getViewBox().sceneBoundingRect().contains(event.scenePos()):return
        p=plot.getViewBox().mapSceneToView(event.scenePos())
        mapping={'XY':('X','Y'),'YZ':('Y','Z'),'ZX':('X','Z')}
        for axis,value in zip(mapping[key],(p.x(),p.y())):
            sl=self._sliders[axis]
            sl.setValue(max(sl.minimum(),min(sl.maximum(),int(round(value)))))

    def _select_high_res(self,plane):
        if self._volume is None or self.hr_widget.busy:return
        self.hr_widget.select_plane_from_preview(plane,
            self._sliders['X'].value(),self._sliders['Y'].value())
        self.tabs.setCurrentWidget(self.hr_widget)

    def _high_res_busy_changed(self,busy):
        self.view_selector.setEnabled(not busy and self._volume is not None)
        self.hr_yz.setEnabled(not busy and self._volume is not None)
        self.hr_zx.setEnabled(not busy and self._volume is not None)
        if not busy and self._closing_for_high_res:
            QtCore.QTimer.singleShot(0,self.close)

    def _render_report(self):
        """Bounded screenshot of current 2D planes; never loads volume again."""
        if self._volume is None or self._last_xy_slice!=self._sliders['Z'].value():
            raise ValueError('Wait until preview and original XY image finish loading')
        width=1500
        comment=self.comment_edit.toPlainText()[:10000]
        lines=comment.splitlines() or ['']
        note_height=max(130,min(1000,45+25*sum(max(1,(len(line)+90)//91) for line in lines)))
        height=1120+note_height
        canvas=QtGui.QImage(width,height,QtGui.QImage.Format.Format_ARGB32)
        canvas.fill(QtGui.QColor('white'))
        paint=QtGui.QPainter(canvas)
        try:
            paint.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform,True)
            paint.setFont(QtGui.QFont('Arial',25,QtGui.QFont.Weight.Bold))
            paint.setPen(QtGui.QColor('#172332'))
            paint.drawText(46,57,'LOUPE')
            paint.setFont(QtGui.QFont('Arial',12))
            paint.setPen(QtGui.QColor('#8291a4'))
            paint.drawText(48,82,'Version '+APP_VERSION+'  |  Orthogonal Preview  |  '+
                           datetime.now().strftime('%Y-%m-%d %H:%M'))
            title=self._view_sources[self._selected_view].get('label',f'VIEW {self._selected_view+1}')
            sample=self.paths[0].parent.name
            paint.setPen(QtGui.QColor('#29384a'))
            paint.drawText(48,116,f'{title}  ·  {sample}  ·  {len(self.paths)} slices')
            positions='   '.join(f'{a}={self._sliders[a].value()+1}' for a in ('X','Y','Z'))
            vox=(f'{self._pixel_size_um:g} µm/voxel (isotropic)' if self._pixel_size_um else 'unknown voxel size')
            paint.drawText(48,139,positions+'  |  '+vox)
            for name,rect in (('XY',(48,192,680,408)),('YZ',(770,192,680,408)),('ZX',(48,646,680,408))):
                x,y,w,h=rect
                paint.setFont(QtGui.QFont('Arial',17,QtGui.QFont.Weight.Bold))
                paint.setPen(QtGui.QColor('#14263a'))
                text=name+(' · Original TIFF display' if name=='XY' else ' · Reduced-resolution preview')
                paint.drawText(x,y-10,text)
                pix=self._plots[name].grab()
                target=QtCore.QRectF(x,y,w,h)
                paint.fillRect(target,QtGui.QColor('#101820'))
                scaled=pix.scaled(w,h,QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                  QtCore.Qt.TransformationMode.SmoothTransformation)
                px=x+(w-scaled.width())/2;py=y+(h-scaled.height())/2
                paint.drawPixmap(QtCore.QPointF(px,py),scaled)
            paint.setFont(QtGui.QFont('Arial',13))
            paint.setPen(QtGui.QColor('#3f5266'))
            paint.drawText(QtCore.QRectF(770,676,680,350),
                QtCore.Qt.TextFlag.TextWordWrap,
                'XY displays original-resolution TIFF data.\nYZ and ZX are decimated '
                'previews for navigation only.\nThey are not suitable for quantitative analysis. '
                'No physical resolution or voxel intensities are inferred from this report.')
            paint.setPen(QtGui.QColor('#29384a'))
            paint.setFont(QtGui.QFont('Arial',13,QtGui.QFont.Weight.Bold))
            paint.drawText(48,1090,'Comments')
            paint.setFont(QtGui.QFont('Arial',12))
            paint.drawText(QtCore.QRectF(48,1100,width-96,note_height),
                           QtCore.Qt.TextFlag.TextWordWrap,comment or '(none)')
        finally:paint.end()
        return canvas

    def _export_layered_preview_pdf(self,destination):
        """Selectable text, three separately copyable raster image objects."""
        writer=QtGui.QPdfWriter(str(destination))
        writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.PageSizeId.A4))
        writer.setPageOrientation(QtGui.QPageLayout.Orientation.Landscape)
        writer.setResolution(150)
        writer.setTitle('LOUPE · Orthogonal Preview')
        painter=QtGui.QPainter()
        if not painter.begin(writer):raise OSError('Cannot write PDF')
        try:
            pw,ph=writer.width(),writer.height()
            painter.scale(pw/1450.,ph/1050.)
            painter.fillRect(QtCore.QRectF(0,0,1450,1050),QtGui.QColor('white'))
            painter.setPen(QtGui.QColor('#192939'))
            painter.setFont(QtGui.QFont('Arial',23,QtGui.QFont.Weight.Bold))
            painter.drawText(QtCore.QPointF(45,52),'LOUPE · Orthogonal Preview')
            painter.setFont(QtGui.QFont('Arial',12))
            painter.drawText(QtCore.QPointF(45,79),
                f'XY: native TIFF · YZ / ZX: reduced-resolution navigation only · Z index: {self._sliders["Z"].value()+1}')
            views=(('XY',50,105),('YZ',740,105),('ZX',50,550))
            for name,x,y in views:
                painter.setFont(QtGui.QFont('Arial',15,QtGui.QFont.Weight.Bold))
                painter.drawText(QtCore.QPointF(x,y+22),name)
                pix=self._plots[name].grab()
                image=pix.toImage()
                box=QtCore.QRectF(x,y+38,625,385)
                painter.fillRect(box,QtGui.QColor('#101820'))
                scaled=image.scaled(int(box.width()),int(box.height()),
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation)
                painter.drawImage(QtCore.QRectF(box.left()+(box.width()-scaled.width())/2,
                    box.top()+(box.height()-scaled.height())/2,
                    scaled.width(),scaled.height()),scaled)
            painter.setPen(QtGui.QColor('#192939'))
            painter.setFont(QtGui.QFont('Arial',13,QtGui.QFont.Weight.Bold))
            painter.drawText(QtCore.QPointF(735,590),'Preview note')
            painter.setFont(QtGui.QFont('Arial',12))
            painter.drawText(QtCore.QRectF(735,606,665,180),QtCore.Qt.TextFlag.TextWordWrap,
                'YZ / ZX previews are decimated and not valid for intensity measurement. '
                'Use Native Section to produce a quantitative section from the original TIFF stack.')
            painter.drawText(QtCore.QRectF(50,990,1350,40),
                QtCore.Qt.TextFlag.TextWordWrap,self.comment_edit.toPlainText()[:1200])
        finally:
            painter.end()
            del painter,writer

    def _export_report(self, kind):
        """The same Save As workflow as normal reports (no silent overwrite).

        The chosen filename is honored verbatim; an existing report is replaced
        only with permission. A failed renderer cannot corrupt the old report:
        write to a sibling temporary file and atomically replace on success.
        """
        if self._volume is None:
            QtWidgets.QMessageBox.warning(self, 'Orthogonal report',
                'Wait until the orthogonal preview is ready.')
            return
        try:
            suggestion = suggested_path([self.paths[0]],
                'Orthogonal_Preview_' +
                self._view_sources[self._selected_view].get('label', 'VIEW').replace(' ', '_'),
                kind.lower())
            if self._last_report_dir and Path(self._last_report_dir).is_dir():
                suggestion = Path(self._last_report_dir) / suggestion.name
            extension = '.' + kind.lower()
            filt = 'PNG Image (*.png)' if kind == 'PNG' else 'PDF Document (*.pdf)'
            chosen, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, 'Save Orthogonal '+kind+' report', str(suggestion), filt,
                options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
            if not chosen:
                return  # Cancel: do not render or create a report.
            path = Path(chosen)
            if not path.suffix:
                path = path.with_suffix(extension)
            elif path.suffix.lower() != extension:
                raise ValueError(f'Select a {extension} filename for this report')
            if path.exists():
                answer = QtWidgets.QMessageBox.question(
                    self, 'Replace report?', f'{path.name} already exists. Replace it?',
                    QtWidgets.QMessageBox.StandardButton.Yes |
                    QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.No)
                if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
            canvas = self._render_report()
            path.parent.mkdir(parents=True, exist_ok=True)
            # Create output only after the report has been rendered successfully.
            fd, tempname = tempfile.mkstemp(prefix='.loupe-report-', suffix=extension,
                                            dir=str(path.parent))
            os.close(fd)
            tmp = Path(tempname)
            try:
                if kind == 'PNG':
                    if not canvas.save(str(tmp), 'PNG'):
                        raise RuntimeError('Failed to save PNG')
                else:
                    self._export_layered_preview_pdf(tmp)
                if tmp.stat().st_size == 0:
                    raise RuntimeError('Report output was empty')
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
            self._last_report_dir = str(path.parent)
            QtCore.QSettings('BL09W', 'LOUPE').setValue('orthogonal_report_dir',
                                                       self._last_report_dir)
            self._status.setText(kind+' report saved: '+path.name)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, 'Orthogonal report', str(exc))

    def closeEvent(self,event):
        if self.hr_widget.busy:
            self._closing_for_high_res=True
            self.hr_widget.stop()
            event.ignore()
            return
        self.hr_widget.dispose()
        self._cancel.set()
        self._xy_debounce.stop()
        self._pool.shutdown(wait=False,cancel_futures=True)
        super().closeEvent(event)
