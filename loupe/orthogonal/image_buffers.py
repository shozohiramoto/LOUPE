"""Memory-safe owned 2D buffers before handing image data to pyqtgraph/Qt."""
from __future__ import annotations
import numpy as np


def qt_owned_plane(array):
    """Return a dense privately owned C-contiguous image with original values.

    Orthogonal planes from `(Z,Y,X)` memmaps, especially YZ/ZX views, are
    heavily strided. Native Qt drawing must not reference a temporary mmap view.
    """
    array=np.asarray(array)
    if array.ndim != 2 or not np.issubdtype(array.dtype, np.number):
        raise ValueError('A numeric two-dimensional image is required')
    return np.array(array, copy=True, order='C')
