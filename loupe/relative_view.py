"""Pure coordinate operations for zoom-linked panels with fixed relative offsets."""
from math import isfinite


def validate_offsets(value, count=4):
    if not isinstance(value, (tuple, list)) or len(value) != count:
        return [(0.0, 0.0) for _ in range(count)]
    result=[]
    for i,item in enumerate(value):
        try:
            if len(item) != 2: raise ValueError
            x,y = map(float,item)
            if not (isfinite(x) and isfinite(y)):raise ValueError
            result.append((x,y) if i else (0.0,0.0))
        except (ValueError, TypeError, OverflowError):
            return [(0.0,0.0) for _ in range(count)]
    return result


def move_range(ranges, delta):
    dx,dy=delta
    return [[float(a+dx),float(b+dx)] for (a,b),dx in zip(ranges,(dx,dy))]


def anchor_range(source_range, source_offset):
    return move_range(source_range,(-source_offset[0],-source_offset[1]))


def center_difference(moved, reference):
    return (sum(moved[0])/2-sum(reference[0])/2,
            sum(moved[1])/2-sum(reference[1])/2)
