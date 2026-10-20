"""Standalone intensity sampling used by the LOUPE line profile widget."""
import numpy as np


def roi_endpoints(roi):
    """Return ROI line endpoints in parent (source image pixel) coordinates."""
    handles = roi.getHandles()
    if len(handles) < 2:
        raise ValueError('Line ROI needs two handles')
    return tuple((float(roi.mapToParent(h.pos()).x()), float(roi.mapToParent(h.pos()).y())) for h in handles[:2])


def sample_line(image, start, end):
    """Sample the native TIFF values by bilinear interpolation (NaN out of bounds).

    Coordinates are pixel-center coordinates: integer (x, y) refers to image[y, x].
    One output sample per about one pixel of Euclidean segment length.
    """
    arr = np.asarray(image)
    if arr.ndim != 2:
        raise ValueError('Expected 2D grayscale image')
    x0, y0 = map(float, start)
    x1, y1 = map(float, end)
    length = float(np.hypot(x1 - x0, y1 - y0))
    n = max(2, int(np.ceil(length)) + 1)
    d = np.linspace(0.0, length, n)
    xs = np.linspace(x0, x1, n)
    ys = np.linspace(y0, y1, n)
    h, w = arr.shape
    valid = (xs >= 0) & (xs <= w - 1) & (ys >= 0) & (ys <= h - 1)
    values = np.full(n, np.nan, dtype=np.float64)
    if not np.any(valid):
        return d, values
    xv = xs[valid]; yv = ys[valid]
    a = np.floor(xv).astype(int); b = np.floor(yv).astype(int)
    c = np.minimum(a + 1, w - 1); e = np.minimum(b + 1, h - 1)
    fx = xv - a; fy = yv - b
    data = arr.astype(np.float64, copy=False)
    values[valid] = ((1-fx)*(1-fy)*data[b, a] + fx*(1-fy)*data[b, c]
                     + (1-fx)*fy*data[e, a] + fx*fy*data[e, c])
    return d, values


def sample_thick_line(image, start, end, width=1, aggregation="mean"):
    """Native-pixel intensity sampled across a perpendicular strip.

    Width is measured in source-image pixels. At every longitudinal sample,
    use `width` equidistant cross-line positions spaced by 1 source pixel;
    bilinear interpolation for fractional positions. Samples outside image
    bounds and non-finite image intensities are ignored. Mean returns a
    normalized strip average; sum returns the strip's discrete sum. If all
    samples are invalid, return NaN. For width=1, preserves sample_line.
    """
    width = int(width)
    if not 1 <= width <= 101:
        raise ValueError('Width must be between 1 and 101 px')
    if aggregation not in ('mean', 'sum'):
        raise ValueError('Aggregation must be mean or sum')
    dist, base = sample_line(image, start, end)
    if width == 1:
        return dist, base
    arr = np.asarray(image)
    x0, y0 = map(float, start)
    x1, y1 = map(float, end)
    seglen = float(np.hypot(x1-x0, y1-y0))
    if seglen == 0:
        perp_x, perp_y = 0.0, 1.0
    else:
        perp_x, perp_y = -(y1-y0)/seglen, (x1-x0)/seglen
    xs = np.linspace(x0, x1, len(dist))
    ys = np.linspace(y0, y1, len(dist))
    offsets = np.arange(width, dtype=float) - (width-1)/2.0
    total = np.zeros(len(dist), dtype=np.float64)
    counts = np.zeros(len(dist), dtype=np.int32)
    h,w = arr.shape
    data = arr.astype(np.float64, copy=False)
    for offset in offsets:
        sx, sy = xs + offset*perp_x, ys + offset*perp_y
        valid = (sx>=0)&(sx<=w-1)&(sy>=0)&(sy<=h-1)
        if not np.any(valid):
            continue
        ids=np.flatnonzero(valid)
        xv,yv=sx[ids],sy[ids]
        xa=np.floor(xv).astype(int); ya=np.floor(yv).astype(int)
        xb=np.minimum(xa+1,w-1); yb=np.minimum(ya+1,h-1)
        fx=xv-xa; fy=yv-ya
        vals=((1-fx)*(1-fy)*data[ya,xa]+fx*(1-fy)*data[ya,xb]
              +(1-fx)*fy*data[yb,xa]+fx*fy*data[yb,xb])
        good=np.isfinite(vals)
        total[ids[good]]+=vals[good]
        counts[ids[good]]+=1
    out=np.full(len(dist),np.nan,dtype=np.float64)
    valid=counts>0
    out[valid]=total[valid]/counts[valid] if aggregation=='mean' else total[valid]
    return dist,out
