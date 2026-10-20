"""High-resolution, screen-independent comparison PNG reports (Phase A v1.5).

No TIFF is embedded as a separate file. The generated report contains only
current visible rendered slices, their ROIs, calibrated scale bars, profiles
and the user's optional comment. Uses Qt at runtime; geometry helpers can be
unit-tested without a GUI installation.
"""
from datetime import datetime
from .version import APP_VERSION
from .ui_theme import theme
PROFILE_HEX = theme()["palette"]["profile"]
from pathlib import Path
import math
import numpy as np
from .calibration import normalize_calibration, scale_bar_for_span
from .measurements import caption, frame


def report_grid(n):
    if not isinstance(n, int) or not 1 <= n <= 4:
        raise ValueError('Report supports 1–4 panels')
    return (1 if n == 1 else 2, (n + (1 if n == 1 else 2) - 1) // (1 if n == 1 else 2))


def source_view_range(view_range, image_shape):
    """Respect native TIFF pixel coordinates; default to full image."""
    h, w = map(int, image_shape[:2])
    if w < 1 or h < 1:
        raise ValueError('Empty image')
    if view_range is None:
        return (0., float(w)), (0., float(h))
    axes = [tuple(sorted(float(x) for x in interval)) for interval in view_range]
    if len(axes) != 2 or any(len(v) != 2 for v in axes):
        raise ValueError('Invalid view range')
    if any(not math.isfinite(x) for axis in axes for x in axis):
        raise ValueError('Non-finite view range')
    if any(b-a < 1e-8 for a,b in axes):
        raise ValueError('Zero-length view range')
    return axes[0], axes[1]


def _make_image(arr, lo, hi, target_width, target_height):
    """Color-map gray native intensity to 8-bit only after size-limited decimation."""
    from PySide6 import QtGui
    h,w = arr.shape
    step = max(1, math.ceil(max(w / max(1,target_width*2),h / max(1,target_height*2))))
    sampled = arr[::step, ::step]
    # All intensity modification is display-only; original TIFF array untouched.
    if not (np.isfinite(lo) and np.isfinite(hi) and hi > lo):
        raise ValueError('Invalid contrast limits for PNG report')
    data = np.asarray(sampled, dtype=np.float64)
    mapped = np.clip(np.nan_to_num((data-lo)*(255./(hi-lo)),nan=0.,posinf=255.,neginf=0.),0,255).astype(np.uint8)
    mapped = np.ascontiguousarray(mapped)
    qimg = QtGui.QImage(mapped.data, mapped.shape[1], mapped.shape[0], mapped.strides[0],
                        QtGui.QImage.Format.Format_Grayscale8)
    return qimg.copy()


def _label(painter, text, x, y, fg, bg):
    from PySide6 import QtCore, QtGui
    fm = painter.fontMetrics()
    width = fm.horizontalAdvance(text) + 12
    rect = QtCore.QRectF(x, y-fm.height()-5, width, fm.height()+8)
    painter.fillRect(rect, bg)
    painter.setPen(fg)
    painter.drawText(QtCore.QPointF(x+6, y-6), text)


def _draw_scale_bar(painter, view, source_x_span, map_point, panel_rect, calibration, show):
    from PySide6 import QtCore, QtGui
    if not show:
        return
    item = scale_bar_for_span(source_x_span,calibration)
    if item is None:
        return
    x0 = panel_rect.left() + 25
    y0 = panel_rect.bottom() - 25
    scale = map_point(1., 0.)[0]-map_point(0., 0.)[0]
    length = item['pixels'] * scale
    if length > panel_rect.width()-48 or length < 1:
        return
    painter.save()
    painter.setPen(QtGui.QPen(QtGui.QColor('#101820'),7))
    painter.drawLine(QtCore.QPointF(x0,y0),QtCore.QPointF(x0+length,y0))
    painter.setPen(QtGui.QPen(QtGui.QColor('white'),4))
    painter.drawLine(QtCore.QPointF(x0,y0),QtCore.QPointF(x0+length,y0))
    for x in (x0,x0+length):
        painter.drawLine(QtCore.QPointF(x,y0-6),QtCore.QPointF(x,y0+6))
    _label(painter,item['label'],x0,y0-10,QtGui.QColor('white'),QtGui.QColor(18,25,35,220))
    painter.restore()


def _draw_image(painter, item, bounds):
    from PySide6 import QtCore, QtGui
    image = item['image']
    (vx0,vx1),(vy0,vy1) = source_view_range(item.get('view_range'),image.shape)
    viewport_w,viewport_h=vx1-vx0,vy1-vy0
    # Consistent pixel aspect ratio (no image stretching) even between panels.
    scale = min(bounds.width()/viewport_w,bounds.height()/viewport_h)
    left = bounds.left()+(bounds.width()-viewport_w*scale)*.5
    top = bounds.top()+(bounds.height()-viewport_h*scale)*.5
    def m(x,y): return (left+(float(x)-vx0)*scale, top+(float(y)-vy0)*scale)
    painter.fillRect(bounds,QtGui.QColor('#101820'))
    painter.save()
    painter.setClipRect(bounds)
    x0,y0=max(0,math.floor(vx0)),max(0,math.floor(vy0))
    x1,y1=min(image.shape[1],math.ceil(vx1)),min(image.shape[0],math.ceil(vy1))
    if x1>x0 and y1>y0:
        crop=image[y0:y1,x0:x1]
        lo,hi=map(float,item['levels'])
        qimg=_make_image(crop,lo,hi,int(bounds.width()),int(bounds.height()))
        a,b=m(x0,y0);c,d=m(x1,y1)
        painter.drawImage(QtCore.QRectF(a,b,c-a,d-b),qimg)
    cal=normalize_calibration(item.get('calibration'))
    font=QtGui.QFont('Arial',10)
    painter.setFont(font)
    for roi in item.get('annotations',[]):
        kind=roi.get('type')
        painter.setPen(QtGui.QPen(QtGui.QColor('#35e2ff' if kind!='count' else '#ff7777'),2.5))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        if kind=='line':
            x0,y0=roi['start']; x1,y1=roi['end']
            sx,sy=m(x0,y0);ex,ey=m(x1,y1)
            painter.drawLine(QtCore.QPointF(sx,sy),QtCore.QPointF(ex,ey))
            lx,ly=ex,ey
        elif kind in ('rect','ellipse','circle'):
            cx,cy,w,h,ang=frame(roi)
            lx,ly=m(cx+w/2,cy+h/2)
            painter.save()
            x,y=m(cx,cy)
            painter.translate(x,y);painter.rotate(ang)
            r=QtCore.QRectF(-w*scale/2,-h*scale/2,w*scale,h*scale)
            if kind=='rect':painter.drawRect(r)
            else:painter.drawEllipse(r)
            painter.restore()
        elif kind=='count':
            x,y=m(*roi['point']);lx,ly=x+8,y-6
            painter.drawLine(QtCore.QPointF(x-8,y),QtCore.QPointF(x+8,y))
            painter.drawLine(QtCore.QPointF(x,y-8),QtCore.QPointF(x,y+8))
        else:continue
        if bounds.contains(QtCore.QPointF(lx,ly)):
            # Native TIFF coordinate annotation values, never screen-pixel lengths.
            _label(painter,caption(roi,{'enabled':cal['enabled'],'x':cal['pixel_size'],
                'y':item.get('vertical_pixel_size_um',cal['pixel_size']), 'unit':cal['unit']}),
                min(lx,bounds.right()-150),ly-7,
                   QtGui.QColor('white'),QtGui.QColor(5,18,30,205))
    line = item.get('profile_line')
    if line is not None:
        (x0,y0),(x1,y1)=line
        painter.setPen(QtGui.QPen(QtGui.QColor('#ffb200'),2.5))
        painter.drawLine(QtCore.QPointF(*m(x0,y0)),QtCore.QPointF(*m(x1,y1)))
    _draw_scale_bar(painter,item,viewport_w,m,bounds,cal,item.get('show_scale_bar',True))
    painter.restore()


def _draw_profile(painter, record, bounds):
    from PySide6 import QtCore, QtGui
    painter.fillRect(bounds,QtGui.QColor(theme()['palette']['canvas']))
    painter.setPen(QtGui.QPen(QtGui.QColor('#596a7f'),1))
    painter.drawRect(bounds)
    inset=QtCore.QRectF(bounds.left()+46,bounds.top()+24,bounds.width()-68,bounds.height()-54)
    painter.setPen(QtGui.QColor(REPORT_TEXT))
    painter.drawText(QtCore.QRectF(bounds.left()+12,bounds.top()+5,bounds.width()-24,20),
                     QtCore.Qt.AlignmentFlag.AlignLeft,'Line / mean profile (native TIFF intensity)')
    if record is None:
        painter.drawText(inset,QtCore.Qt.AlignmentFlag.AlignCenter,'Profile not enabled')
        return
    distance, values = record['profile']
    d=np.asarray(distance,dtype=float);v=np.asarray(values,dtype=float)
    mask=np.isfinite(d)&np.isfinite(v)
    if mask.sum()<2:
        painter.drawText(inset,QtCore.Qt.AlignmentFlag.AlignCenter,'No finite profile samples')
        return
    d=d[mask];v=v[mask]
    xmin,xmax=float(d.min()),float(d.max()); ymin,ymax=float(v.min()),float(v.max())
    if xmax<=xmin:xmax=xmin+1
    if ymax<=ymin:ymax=ymin+1
    painter.setPen(QtGui.QPen(QtGui.QColor('#a4b8cd'),1))
    painter.drawLine(inset.bottomLeft(),inset.bottomRight())
    painter.drawLine(inset.bottomLeft(),inset.topLeft())
    pts=[QtCore.QPointF(inset.left()+((a-xmin)/(xmax-xmin))*inset.width(),
                        inset.bottom()-((b-ymin)/(ymax-ymin))*inset.height()) for a,b in zip(d,v)]
    painter.setPen(QtGui.QPen(QtGui.QColor(PROFILE_HEX),2))
    painter.drawPolyline(QtGui.QPolygonF(pts))
    painter.setPen(QtGui.QColor(REPORT_TEXT))
    painter.drawText(QtCore.QRectF(inset.left(),inset.bottom()+2,inset.width(),19),
                     QtCore.Qt.AlignmentFlag.AlignCenter,f'Distance: {xmax:.1f} px')
    painter.drawText(QtCore.QPointF(bounds.left()+4,inset.top()+12),f'{ymax:.3g}')
    painter.drawText(QtCore.QPointF(bounds.left()+4,inset.bottom()),f'{ymin:.3g}')




def has_renderable_profile(record):
    """Only plot when finite original-intensity samples actually form a curve."""
    if not isinstance(record,dict) or 'profile' not in record:return False
    try:
        d,v=record['profile']
        a=np.asarray(d,dtype=float);b=np.asarray(v,dtype=float)
        return a.ndim==b.ndim==1 and len(a)==len(b) and int(np.count_nonzero(np.isfinite(a)&np.isfinite(b)))>=2
    except (ValueError,TypeError,IndexError):return False

# The same dark typographic palette is used in both PNG and PDF reports.
REPORT_TEXT = '#17212f'


def _report_path_lines(path, metrics, max_width, max_lines=4):
    """Wrap a complete source path (never silently elide it).

    Paths can contain long folder names with no spaces. Break after directory
    separators where possible, otherwise by character width. Both Qt painters
    consume the exact same resulting lines.
    """
    path = str(path or '(unknown source)')
    if not path:
        return ['(unknown source)']
    lines = []
    segment = ''
    for char in path:
        candidate = segment + char
        if segment and metrics.horizontalAdvance(candidate) > max_width:
            split = max(segment.rfind('\\'), segment.rfind('/')) + 1
            if 0 < split < len(segment):
                lines.append(segment[:split]); segment = segment[split:] + char
            else:
                lines.append(segment); segment = char
        else:
            segment = candidate
    if segment:lines.append(segment)
    # The report expands the metadata area as required instead of discarding
    # the tail of the file path. Guard only pathologically long strings.
    if len(lines) > max_lines:
        # A long path remains available as selectable PDF text: put remaining
        # lines in the same field (allowed by the text layout).
        return lines
    return lines


def _report_header_title(title):
    raw = str(title or '').strip()
    if not raw or raw.casefold() in ('loupe', 'loupe report'):
        return None
    if raw.casefold().startswith('loupe ·'):
        return raw.split('·', 1)[1].strip()
    return raw


def _paint_orthogonal_provenance(painter, panel, x, y, width):
    """Render full native-section provenance, returning consumed vertical height.

    The same helper is called by PNG and PDF paths. Text is readable/searchable
    in the PDF (not embedded as a screenshot). Ordinary VIEWs are unchanged.
    """
    from PySide6 import QtCore, QtGui
    lines=panel.get('orthogonal_provenance')
    if not lines:
        return 0
    content='\n'.join(str(line) for line in lines)
    painter.save()
    painter.setFont(QtGui.QFont('Arial',10))
    painter.setPen(QtGui.QColor(REPORT_TEXT))
    metrics=QtGui.QFontMetrics(painter.font())
    flags=QtCore.Qt.TextFlag.TextWordWrap | QtCore.Qt.AlignmentFlag.AlignLeft
    bounds=metrics.boundingRect(QtCore.QRect(0,0,int(width)-16,10000),flags,content)
    needed=bounds.height()+18
    rect=QtCore.QRectF(x,y,width,needed)
    painter.fillRect(rect,QtGui.QColor('#eff5fa'))
    painter.setPen(QtGui.QPen(QtGui.QColor('#b1c5d4'),1))
    painter.drawRect(rect)
    painter.setPen(QtGui.QColor(REPORT_TEXT))
    painter.drawText(QtCore.QRectF(x+8,y+8,width-16,needed-14),flags,content)
    painter.restore()
    return needed+8


def render_report_image(panels, comment='', title='LOUPE'):
    """Render report as a Qt image, independent of destination format."""
    from PySide6 import QtCore, QtGui
    if not panels or len(panels)>4:
        raise ValueError('Load between 1 and 4 image datasets before exporting')
    for panel in panels:
        if not isinstance(panel.get('image'),np.ndarray) or panel['image'].ndim!=2:
            raise ValueError('Every included panel must have a loaded 2D image')
    cols,rows=report_grid(len(panels))
    width=1100 if cols==1 else 1900
    margin=48; gap=36; header_h=108
    # Fit the complete user comment rather than silently cropping notes.
    comment_font=QtGui.QFont('Arial',12)
    comment_width=width-2*margin
    comment_bounds=QtGui.QFontMetrics(comment_font).boundingRect(
        QtCore.QRect(0,0,comment_width,100000),
        QtCore.Qt.TextFlag.TextWordWrap | QtCore.Qt.AlignmentFlag.AlignLeft,
        str(comment).strip() or '(none)')
    footer_h=max(140, comment_bounds.height()+85)
    card_w=(width-2*margin-(cols-1)*gap)//cols
    card_h=790; height=header_h+rows*card_h+(rows-1)*gap+footer_h
    canvas=QtGui.QImage(width,height,QtGui.QImage.Format.Format_ARGB32)
    canvas.fill(QtGui.QColor('white'))
    painter=QtGui.QPainter(canvas)
    try:
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing,True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform,True)
        painter.setPen(QtGui.QColor('#0f172a'))
        painter.setFont(QtGui.QFont('Arial',24,QtGui.QFont.Weight.Bold))
        painter.drawText(QtCore.QPointF(margin,53),'LOUPE Report')
        painter.setFont(QtGui.QFont('Arial',12))
        painter.setPen(QtGui.QColor(REPORT_TEXT))
        painter.drawText(QtCore.QPointF(margin,78),f'Version {APP_VERSION}')
        painter.drawText(QtCore.QPointF(margin+260,78),datetime.now().strftime('%Y-%m-%d %H:%M')+
                         f'   |   {len(panels)} view(s)')
        if _report_header_title(title):
            painter.drawText(QtCore.QPointF(margin+530,78),_report_header_title(title)[:68])
        for index, panel in enumerate(panels):
            row,col=divmod(index,cols)
            x=margin+col*(card_w+gap);y=header_h+row*(card_h+gap)
            card=QtCore.QRectF(x,y,card_w,card_h)
            painter.fillRect(card,QtGui.QColor('#ffffff'))
            painter.setPen(QtGui.QPen(QtGui.QColor('#596a7f'),2));painter.drawRoundedRect(card,9,9)
            painter.setFont(QtGui.QFont('Arial',17,QtGui.QFont.Weight.Bold))
            painter.setPen(QtGui.QColor('#0f172a'))
            painter.drawText(QtCore.QPointF(x+22,y+34),str(panel['side']))
            painter.setFont(QtGui.QFont('Arial',12))
            painter.setPen(QtGui.QColor(REPORT_TEXT))
            name=Path(str(panel['path'])).name
            painter.drawText(QtCore.QPointF(x+22,y+61),
                             f'{name}   |   slice {panel["slice"]}')
            metrics=QtGui.QFontMetrics(painter.font())
            path_lines=_report_path_lines(panel.get('path'),metrics,card_w-44)
            line_spacing=metrics.lineSpacing()
            for n,line in enumerate(path_lines):
                painter.drawText(QtCore.QPointF(x+22,y+81+n*line_spacing),line)
            cal=normalize_calibration(panel.get('calibration'))
            desc=f'Pixel size: {cal["pixel_size"]:.8g} {cal["unit"]}/px' if cal['enabled'] else 'Pixel size: not calibrated'
            lo,hi=panel['levels']
            meta_y=y+83+len(path_lines)*line_spacing
            painter.drawText(QtCore.QPointF(x+22,meta_y),
                             f'{desc}    |    Display range: {lo:.5g}–{hi:.5g}')
            # ID051: reserve actual wrapped metadata height in PNG before image.
            provenance_h=_paint_orthogonal_provenance(painter,panel,x+20,meta_y+10,card_w-40)
            content_top=meta_y-y+16+provenance_h
            profile_record=panel.get('profile') if has_renderable_profile(panel.get('profile')) else None
            # No empty profile frame, placeholder text, or wasted space in reports.
            if profile_record is None:
                image_box=QtCore.QRectF(x+20,y+content_top,card_w-40,max(100,card_h-content_top-26))
            else:
                image_box=QtCore.QRectF(x+20,y+content_top,card_w-40,max(100,582-content_top))
            _draw_image(painter,panel,image_box)
            if profile_record is not None:
                painter.setFont(QtGui.QFont('Arial',11))
                profile_box=QtCore.QRectF(x+20,y+602,card_w-40,164)
                _draw_profile(painter,profile_record,profile_box)
        base=header_h+rows*card_h+(rows-1)*gap+32
        painter.setPen(QtGui.QColor('#0f172a'))
        painter.setFont(QtGui.QFont('Arial',14,QtGui.QFont.Weight.Bold))
        painter.drawText(QtCore.QPointF(margin,base),'Comments')
        painter.setFont(QtGui.QFont('Arial',12))
        painter.drawText(QtCore.QRectF(margin,base+12,width-2*margin,footer_h-45),
                         QtCore.Qt.TextFlag.TextWordWrap | QtCore.Qt.AlignmentFlag.AlignLeft,
                         str(comment).strip() or '(none)')
    finally:
        painter.end()
    return canvas


def export_png_report(destination, panels, comment='', title='LOUPE'):
    """Save the comparison as a full-resolution, lossless PNG."""
    canvas = render_report_image(panels, comment=comment, title=title)
    destination = Path(destination)
    if not canvas.save(str(destination), 'PNG'):
        raise OSError('Failed to save PNG report: '+str(destination))
    return destination


def export_pdf_report(destination, panels, comment='', title='LOUPE'):
    """Layered PDF: native/selectable text, raster CT as an image object,
    vector overlays / vector line-profile graphs (not a flattened page image).
    PDF viewer image-copy context-menu availability depends on the viewer.
    """
    from PySide6 import QtCore, QtGui
    if not 1 <= len(panels) <= 4:
        raise ValueError('PDF report requires 1–4 loaded views')
    destination=Path(destination)
    writer=QtGui.QPdfWriter(str(destination))
    writer.setResolution(150)
    writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.PageSizeId.A4))
    writer.setPageOrientation(QtGui.QPageLayout.Orientation.Landscape)
    writer.setTitle(str(title))
    writer.setCreator('LOUPE')
    painter=QtGui.QPainter()
    if not painter.begin(writer):raise OSError('Unable to start PDF painter')
    try:
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing,True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform,True)
        canvas_w,canvas_h=1900.,1240.
        for offset in range(0,len(panels),2):
            if offset: writer.newPage()
            painter.save()
            width,height=writer.width(),writer.height()
            factor=min(width/canvas_w,height/canvas_h)
            painter.translate((width-canvas_w*factor)/2,(height-canvas_h*factor)/2)
            painter.scale(factor,factor)
            painter.fillRect(QtCore.QRectF(0,0,canvas_w,canvas_h),QtGui.QColor('white'))
            painter.setPen(QtGui.QColor('#17212f'))
            painter.setFont(QtGui.QFont('Arial',25,QtGui.QFont.Weight.Bold))
            painter.drawText(QtCore.QPointF(48,58),'LOUPE Report')
            painter.setFont(QtGui.QFont('Arial',13))
            subtitle=_report_header_title(title)
            if subtitle:
                painter.drawText(QtCore.QPointF(48,87),subtitle[:100])
            painter.drawText(QtCore.QPointF(1150,87),f'Version {APP_VERSION}  ·  {offset//2+1}/{(len(panels)+1)//2}')
            for i,item in enumerate(panels[offset:offset+2]):
                x=48+i*930
                painter.setFont(QtGui.QFont('Arial',16,QtGui.QFont.Weight.Bold))
                painter.setPen(QtGui.QColor('#17212f'))
                painter.drawText(QtCore.QPointF(x,134),str(item['side']))
                painter.setFont(QtGui.QFont('Arial',11))
                painter.drawText(QtCore.QPointF(x,164),
                    Path(str(item['path'])).name+f' · slice {item["slice"]}')
                metrics=QtGui.QFontMetrics(painter.font())
                path_lines=_report_path_lines(item.get('path'),metrics,870)
                row_height=metrics.lineSpacing()
                for n,line in enumerate(path_lines):
                    painter.drawText(QtCore.QPointF(x,183+n*row_height),line)
                cal=normalize_calibration(item.get('calibration'))
                desc=(f'{cal["pixel_size"]:.8g} {cal["unit"]}/px' if cal['enabled'] else 'Uncalibrated')
                lo,hi=item['levels']
                cal_y=183+len(path_lines)*row_height+3
                painter.drawText(QtCore.QPointF(x,cal_y),
                    f'Pixel size: {desc} | Display range: {lo:.5g} – {hi:.5g}')
                has_profile=has_renderable_profile(item.get('profile'))
                # ID051: show cut location, orientation and generation conditions
                # as selectable text in PDF as well as printed pixels in PNG.
                provenance_h=_paint_orthogonal_provenance(painter,item,x,cal_y+10,865)
                image_y=max(230,cal_y+14+provenance_h)
                image_box=QtCore.QRectF(x,image_y,865,max(160,(845 if has_profile else 1000)-image_y))
                _draw_image(painter,item,image_box)
                if has_profile:
                    _draw_profile(painter,item['profile'],QtCore.QRectF(x,860,865,175))
            painter.setPen(QtGui.QColor('#17212f'))
            painter.setFont(QtGui.QFont('Arial',13,QtGui.QFont.Weight.Bold))
            painter.drawText(QtCore.QPointF(48,1080),'Comments / metadata')
            painter.setFont(QtGui.QFont('Arial',11))
            painter.drawText(QtCore.QRectF(48,1090,1800,125),
                QtCore.Qt.TextFlag.TextWordWrap | QtCore.Qt.AlignmentFlag.AlignLeft,
                str(comment).strip() or '(none)')
            painter.restore()
    finally:
        painter.end()
        del painter,writer
    if not destination.exists() or destination.stat().st_size==0:
        raise OSError('PDF report was not written: '+str(destination))
    return destination
