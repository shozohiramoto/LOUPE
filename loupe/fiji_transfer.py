"""Versioned, JSON-only metadata passed to opt-in Fiji receiver.

Native image coordinates are zero-based, image display range is purely
visual, and invalid or unverified physical calibration is NOT transferred.
"""
from __future__ import annotations
import math
from .measurements import validate_annotation


def make_transfer(*, annotations=(), selected_id=None, width_px=1,
                  display_limits=None, calibration=None):
    supported=[]
    for item in annotations:
        roi=validate_annotation(item)
        supported.append(roi)
    if len(supported)>2000:
        raise ValueError('Too many ROI for Fiji transfer')
    result={'schema':'loupe_fiji_transfer_v1','rois':supported,
            'selected_id':selected_id,'line_width_px':max(1,min(101,int(width_px)))}
    if display_limits is not None:
        lo,hi=map(float,display_limits)
        if not (math.isfinite(lo) and math.isfinite(hi) and hi>lo):
            raise ValueError('Invalid contrast min/max')
        result['display']={'min':lo,'max':hi}
    if calibration and calibration.get('enabled'):
        factor={'nm':0.001,'µm':1.,'mm':1000.}[calibration['unit']]
        micron=float(calibration['pixel_size'])*factor
        y_micron=float(calibration.get('pixel_size_y',calibration['pixel_size']))*factor
        if not (math.isfinite(micron) and 1e-6 <= micron <= 1e6 and
                math.isfinite(y_micron) and 1e-6 <= y_micron <= 1e6):
            raise ValueError('Unreasonable Pixel Size for Fiji transfer')
        result['calibration']={'width_um':micron,'height_um':y_micron,'unit':'µm',
                               'source':calibration.get('source','manual')}
    return result
