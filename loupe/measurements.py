"""LOUPE image-coordinate annotations, geometry editing and measurements.

All coordinates and shapes are stored in native TIFF pixel-center coordinates.
Rotation degrees are clockwise in image coordinates (positive Y down).
Legacy Phase A v1.2 rect/circle formats are read without data loss.
"""
import csv
from pathlib import Path
import math
import numpy as np

TYPES = frozenset(('line', 'rect', 'circle', 'ellipse', 'count'))

def _point(p):
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise ValueError('Expected coordinate pair')
    x, y = float(p[0]), float(p[1])
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError('Non-finite coordinate')
    return [x,y]

def _angle(v):
    angle=float(v)
    if not math.isfinite(angle):raise ValueError('Invalid rotation angle')
    return (angle+180.0)%360.0-180.0 if angle else 0.0

def _rotate(x,y,deg):
    a=math.radians(deg);c,s=math.cos(a),math.sin(a)
    return x*c-y*s, x*s+y*c

def _positive(v):
    value=float(v)
    if not math.isfinite(value) or value<0.5:raise ValueError('Dimension must be >= 0.5 px')
    return value

def create_annotation(kind, a, b=None, *, number=None, identifier=None, angle=0.0):
    """Construct JSON-safe native image geometry; old circle API is supported."""
    if kind not in TYPES:raise ValueError('Invalid annotation type')
    x0,y0=_point(a)
    item={'id':identifier,'type':kind}
    if kind=='count':
        if number is None or int(number)<1:raise ValueError('Count number must be positive')
        item.update(point=[x0,y0],number=int(number))
    else:
        x1,y1=_point(b)
        if kind=='line':
            if math.hypot(x1-x0,y1-y0)<1e-9:raise ValueError('Line is too short')
            item.update(start=[x0,y0],end=[x1,y1])
        elif kind=='rect':
            w,h=abs(x1-x0),abs(y1-y0)
            if w<0.5 or h<0.5:raise ValueError('Rectangle is too small')
            item['rect']=[min(x0,x1),min(y0,y1),w,h]
            angle=_angle(angle)
            if angle:item['angle']=angle
        elif kind=='ellipse':
            w,h=abs(x1-x0),abs(y1-y0)
            if w<0.5 or h<0.5:raise ValueError('Ellipse is too small')
            item.update(center=[(x0+x1)/2,(y0+y1)/2],width=w,height=h)
            angle=_angle(angle)
            if angle:item['angle']=angle
        else:
            radius=math.hypot(x1-x0,y1-y0)
            if radius<0.5:raise ValueError('Circle is too small')
            item.update(center=[x0,y0],radius=radius)
    return item

def validate_annotation(item):
    if not isinstance(item,dict):raise ValueError('Annotation must be an object')
    kind=item.get('type');ident=item.get('id')
    if not isinstance(ident,str) or not ident or len(ident)>128:raise ValueError('Invalid annotation ID')
    if kind=='line':return create_annotation('line',item['start'],item['end'],identifier=ident)
    if kind=='rect':
        x,y,w,h=map(float,item['rect']);_positive(w);_positive(h)
        return create_annotation('rect',(x,y),(x+w,y+h),identifier=ident,angle=item.get('angle',0))
    if kind=='ellipse':
        cx,cy=_point(item['center']);w=_positive(item['width']);h=_positive(item['height'])
        return create_annotation('ellipse',(cx-w/2,cy-h/2),(cx+w/2,cy+h/2),identifier=ident,angle=item.get('angle',0))
    if kind=='circle':
        cx,cy=_point(item['center']);r=_positive(item['radius'])
        return create_annotation('circle',(cx,cy),(cx+r,cy),identifier=ident)
    if kind=='count':return create_annotation('count',item['point'],number=item['number'],identifier=ident)
    raise ValueError('Unknown annotation type')

def frame(item):
    """Return (center_x, center_y, width, height, rotation_degrees)."""
    k=item['type']
    if k=='rect':
        x,y,w,h=item['rect'];return (x+w/2,y+h/2,w,h,item.get('angle',0.0))
    if k=='ellipse':
        cx,cy=item['center'];return (cx,cy,item['width'],item['height'],item.get('angle',0.0))
    if k=='circle':
        cx,cy=item['center'];r=item['radius'];return (cx,cy,r*2,r*2,0.0)
    raise ValueError('No geometry frame')

def from_frame(kind,cx,cy,width,height,angle,identifier):
    if kind=='rect':
        return create_annotation('rect',(cx-width/2,cy-height/2),(cx+width/2,cy+height/2),identifier=identifier,angle=angle)
    if kind=='ellipse':
        return create_annotation('ellipse',(cx-width/2,cy-height/2),(cx+width/2,cy+height/2),identifier=identifier,angle=angle)
    raise ValueError('Invalid frame type')

def measurement(item):
    kind=item['type'];m={}
    if kind=='line':
        x0,y0=item['start'];x1,y1=item['end'];m['length_px']=math.hypot(x1-x0,y1-y0)
    elif kind in ('rect','ellipse','circle'):
        cx,cy,w,h,angle=frame(item)
        m.update(width_px=w,height_px=h,area_px2=w*h if kind=='rect' else math.pi*w*h/4)
        if kind=='circle':m.update(radius_px=w/2,diameter_px=w)
        m['angle_deg']=angle
    elif kind=='count':m['count_number']=item['number']
    return m

def physical_dimensions(item, calibration):
    """Calibrated axis lengths in the provided unit; returns None if unset."""
    if not calibration or not calibration.get('enabled'):return None
    sx=float(calibration['x']);sy=float(calibration['y'])
    if not (math.isfinite(sx) and math.isfinite(sy) and sx>0 and sy>0):return None
    unit=calibration.get('unit','µm')
    if item['type']=='line':
        (x0,y0),(x1,y1)=item['start'],item['end']
        return {'length':math.hypot((x1-x0)*sx,(y1-y0)*sy),'unit':unit}
    if item['type'] in ('rect','ellipse','circle'):
        _,_,w,h,a=frame(item);rad=math.radians(a)
        return {'width':w*math.hypot(sx*math.cos(rad),sy*math.sin(rad)),
                'height':h*math.hypot(sx*math.sin(rad),sy*math.cos(rad)), 'unit':unit}
    return None

def caption(item, calibration=None):
    m=measurement(item);kind=item['type']
    if kind=='count':return str(m['count_number'])
    cal=physical_dimensions(item,calibration)
    if kind=='line':
        s=f"L {m['length_px']:.1f} px"
        return s+(f" / {cal['length']:.2f} {cal['unit']}" if cal else '')
    s=f"{m['width_px']:.1f} × {m['height_px']:.1f} px"
    if cal:s+=f" / {cal['width']:.2f} × {cal['height']:.2f} {cal['unit']}"
    if abs(m['angle_deg'])>1e-8:s+=f" | {m['angle_deg']:.1f}°"
    return s

def snap_endpoint(fixed, pointer, image_shape=None):
    """Constrain a line to nearest 45 deg; preserve cursor radius unless image-boundary clipped."""
    fx,fy=_point(fixed);px,py=_point(pointer)
    dx,dy=px-fx,py-fy
    distance=math.hypot(dx,dy)
    if distance<1e-9:return [fx,fy]
    a=round(math.atan2(dy,dx)/(math.pi/4))*(math.pi/4)
    ux,uy=math.cos(a),math.sin(a)
    if image_shape is not None:
        h,w=image_shape
        limits=[]
        if ux>1e-12:limits.append(((w-1)-fx)/ux)
        if ux<-1e-12:limits.append((0-fx)/ux)
        if uy>1e-12:limits.append(((h-1)-fy)/uy)
        if uy<-1e-12:limits.append((0-fy)/uy)
        if limits:distance=max(0.0,min(distance,*limits))
    return [fx+distance*ux,fy+distance*uy]

def rect_mean_profile(image, rect, axis='x'):
    """Finite-pixel mean in a rectangle (per image column or row).

    Select native pixel centers x in [left, right), y in [top, bottom).
    Coordinates are clipped to the 2D image. Empty and all-NaN samples are
    represented by empty arrays or NaN. axis='x': average over y per x.
    axis='y': average over x per y. This is not sub-pixel/bilinear sampling.
    Returns (distance_from_first_pixel_in_px, value, x_center, y_center).
    """
    arr=np.asarray(image)
    if arr.ndim!=2:raise ValueError('Expected a 2D image')
    if axis not in ('x','y'):raise ValueError('axis must be x or y')
    left, top, width, height=map(float,rect)
    if not all(map(math.isfinite,(left,top,width,height))) or width<=0 or height<=0:
        raise ValueError('Invalid rectangle')
    h,w=arr.shape
    # Pixel centers with integer x,y in the rectangle's half-open bounds.
    x0=max(0, int(math.ceil(left))); x1=min(w,int(math.ceil(left+width)))
    y0=max(0, int(math.ceil(top))); y1=min(h,int(math.ceil(top+height)))
    if x1<=x0 or y1<=y0:
        return tuple(np.empty(0,dtype=np.float64) for _ in range(4))
    raw=np.asarray(arr[y0:y1,x0:x1],dtype=np.float64)
    finite=np.isfinite(raw)
    sum_vals=np.where(finite,raw,0).sum(axis=0 if axis=='x' else 1,dtype=np.float64)
    counts=finite.sum(axis=0 if axis=='x' else 1)
    values=np.full(len(counts),np.nan,dtype=np.float64)
    np.divide(sum_vals,counts,out=values,where=counts>0)
    coords=np.arange(x0,x1,dtype=float) if axis=='x' else np.arange(y0,y1,dtype=float)
    distances=coords-coords[0]
    xcoords=coords if axis=='x' else np.full(len(coords),(x0+x1-1)/2,dtype=float)
    ycoords=np.full(len(coords),(y0+y1-1)/2,dtype=float) if axis=='x' else coords
    return distances,values,xcoords,ycoords


MEASUREMENT_CSV_COLUMNS = ['panel','source_tiff','slice_1_based','roi_id','type',
    'x0_px','y0_px','x1_px','y1_px','width_px','height_px','radius_px',
    'length_px','area_px2','count_number','angle_deg','center_x_px','center_y_px']


def measurement_row(side, path, slice_number, item):
    item=validate_annotation(item)
    m=measurement(item)
    row={k:'' for k in MEASUREMENT_CSV_COLUMNS}
    row.update(panel=side,source_tiff=str(path),slice_1_based=slice_number,
               roi_id=item['id'],type=item['type'])
    kind=item['type']
    if kind=='line':
        row.update(x0_px=item['start'][0],y0_px=item['start'][1],
                   x1_px=item['end'][0],y1_px=item['end'][1])
    elif kind=='rect':
        x,y,w,h=item['rect'];row.update(x0_px=x,y0_px=y,x1_px=x+w,y1_px=y+h)
    elif kind in ('circle','ellipse'):
        x,y=item['center'];row.update(x0_px=x,y0_px=y)
    else:
        x,y=item['point'];row.update(x0_px=x,y0_px=y)
    row.update(m)
    if kind in ('rect','circle','ellipse'):
        cx,cy,_,_,_=frame(item)
        row.update(center_x_px=cx,center_y_px=cy)
    return row


def write_measurement_csv(path, rows):
    with open(path,'w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=MEASUREMENT_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:writer.writerow(row)



def rotated_rect_mean_profile(image, item, axis='x'):
    """Rotation-aware native pixel-center rectangle mean profile.

    Pixels whose centers lie inside the rotated rectangle are assigned to
    local-axis integer bins; no resampling or artificial interpolation.
    """
    if axis not in ('x','y'):raise ValueError('axis must be x or y')
    arr=np.asarray(image)
    if arr.ndim!=2:raise ValueError('Expected a 2D image')
    cx,cy,width,height,angle=frame(item)
    if abs(angle)<1e-10:
        return rect_mean_profile(arr,[cx-width/2,cy-height/2,width,height],axis)
    rad=math.radians(angle);c,s=math.cos(rad),math.sin(rad)
    ex=abs(width*c/2)+abs(height*s/2)
    ey=abs(width*s/2)+abs(height*c/2)
    x0=max(0,math.ceil(cx-ex));x1=min(arr.shape[1],math.ceil(cx+ex))
    y0=max(0,math.ceil(cy-ey));y1=min(arr.shape[0],math.ceil(cy+ey))
    if x0>=x1 or y0>=y1:
        return tuple(np.empty(0,dtype=float) for _ in range(4))
    yy,xx=np.mgrid[y0:y1,x0:x1]
    u=(xx-cx)*c+(yy-cy)*s
    v=-(xx-cx)*s+(yy-cy)*c
    mask=(abs(u)<=width/2)&(abs(v)<=height/2)&np.isfinite(arr[y0:y1,x0:x1])
    length=width if axis=='x' else height
    nbins=int(math.ceil(length))
    if nbins<=0:return tuple(np.empty(0,dtype=float) for _ in range(4))
    z=u if axis=='x' else v
    bins=np.floor(z+length/2).astype(int)
    bins=np.clip(bins,0,nbins-1)
    indexes=bins[mask]
    vals=np.asarray(arr[y0:y1,x0:x1],dtype=float)[mask]
    counts=np.bincount(indexes,minlength=nbins)
    total=np.bincount(indexes,weights=vals,minlength=nbins)
    means=np.divide(total,counts,out=np.full(nbins,np.nan),where=counts>0)
    dist=np.arange(nbins,dtype=float)
    axis_coords=dist+0.5-length/2
    if axis=='x':xs=cx+axis_coords*c;ys=cy+axis_coords*s
    else:xs=cx-axis_coords*s;ys=cy+axis_coords*c
    return dist,means,np.asarray(xs),np.asarray(ys)

def annotation_key(path):
    return str(Path(path).resolve())

def adjust_annotation(item, handle, point, drag_start=None, image_shape=None, constrain=False):
    """Immutable per-handle edit, including rotated shapes and 45-degree line snapping.

    constrain means Shift-held. Native pixel coordinates remain authoritative.
    """
    item=validate_annotation(item)
    x,y=_point(point)
    kind=item['type']
    if kind not in ('line','rect','ellipse','circle'):
        raise ValueError('This annotation type does not support editing')
    if image_shape is not None:
        h,w=image_shape
        if h<1 or w<1:raise ValueError('Invalid image shape')
        x=min(max(x,0.0),w-1.0);y=min(max(y,0.0),h-1.0)
    else:h=w=None
    if kind=='line':
        (x0,y0),(x1,y1)=item['start'],item['end']
        if handle=='start':
            x0,y0=snap_endpoint((x1,y1),(x,y),image_shape) if constrain else (x,y)
        elif handle=='end':
            x1,y1=snap_endpoint((x0,y0),(x,y),image_shape) if constrain else (x,y)
        elif handle=='move':
            if drag_start is None:raise ValueError('Move requires drag_start')
            sx,sy=_point(drag_start);dx,dy=x-sx,y-sy
            if w is not None:
                dx=max(-min(x0,x1),min(dx,(w-1)-max(x0,x1)))
                dy=max(-min(y0,y1),min(dy,(h-1)-max(y0,y1)))
            x0,y0,x1,y1=x0+dx,y0+dy,x1+dx,y1+dy
        else:raise ValueError('Unknown line handle')
        return create_annotation('line',(x0,y0),(x1,y1),identifier=item['id'])
    if kind=='circle':
        cx,cy=item['center'];radius=item['radius']
        if handle=='move':
            if drag_start is None:raise ValueError('Move requires drag_start')
            sx,sy=_point(drag_start);cx+=x-sx;cy+=y-sy
            if w is not None:cx=max(0,min(w-1,cx));cy=max(0,min(h-1,cy))
        elif handle=='radius':radius=max(0.5,math.hypot(x-cx,y-cy))
        else:raise ValueError('Unknown circle handle')
        return create_annotation('circle',(cx,cy),(cx+radius,cy),identifier=item['id'])
    cx,cy,width,height,angle=frame(item)
    if handle=='move':
        if drag_start is None:raise ValueError('Move requires drag_start')
        sx,sy=_point(drag_start);dx,dy=x-sx,y-sy
        if w is not None:
            # Use rotated bounding extents to preserve the entire visible shape.
            rad=math.radians(angle)
            ex=abs(width/2*math.cos(rad))+abs(height/2*math.sin(rad))
            ey=abs(width/2*math.sin(rad))+abs(height/2*math.cos(rad))
            dx=max(ex-cx,min(dx,(w if angle==0 else w-1)-ex-cx)) if 2*ex<=w-1 else 0
            dy=max(ey-cy,min(dy,(h if angle==0 else h-1)-ey-cy)) if 2*ey<=h-1 else 0
        return from_frame(kind,cx+dx,cy+dy,width,height,angle,item['id'])
    if handle=='rotate':
        if math.hypot(x-cx,y-cy)<1e-8:return item
        angle=math.degrees(math.atan2(y-cy,x-cx))+90.0
        return from_frame(kind,cx,cy,width,height,_angle(angle),item['id'])
    if handle not in ('nw','n','ne','w','e','sw','s','se'):
        raise ValueError('Unknown '+kind+' handle')
    px,py=_rotate(x-cx,y-cy,-angle)
    # A dragged side/corner is measured in the shape's local coordinate system.
    sx=-1 if 'w' in handle else (1 if 'e' in handle else 0)
    sy=-1 if 'n' in handle else (1 if 's' in handle else 0)
    if sx:
        anchor_x=-sx*width/2
        new_edge_x= max(anchor_x+0.5,px) if sx>0 else min(anchor_x-0.5,px)
        new_w=abs(new_edge_x-anchor_x)
        shift_x=(new_edge_x+anchor_x)/2
    else:new_w=width;shift_x=0.0
    if sy:
        anchor_y=-sy*height/2
        new_edge_y=max(anchor_y+0.5,py) if sy>0 else min(anchor_y-0.5,py)
        new_h=abs(new_edge_y-anchor_y)
        shift_y=(new_edge_y+anchor_y)/2
    else:new_h=height;shift_y=0.0
    if constrain:
        if sx and sy:
            size=max(new_w,new_h)
            new_w=new_h=size
            shift_x=anchor_x+sx*size/2
            shift_y=anchor_y+sy*size/2
        elif sx:
            new_h=new_w
        elif sy:
            new_w=new_h
    dx,dy=_rotate(shift_x,shift_y,angle)
    return from_frame(kind,cx+dx,cy+dy,new_w,new_h,angle,item['id'])
