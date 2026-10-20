"""Small, thread-safe, bounded native-array TIFF cache for slice navigation."""
from collections import OrderedDict
from pathlib import Path
from threading import RLock
import numpy as np


class FrameCache:
    def __init__(self,max_bytes=128*1024**2):
        if max_bytes<=0:raise ValueError('Cache size must be positive')
        self.max_bytes=int(max_bytes)
        self._items=OrderedDict()
        self._bytes=0
        self._epoch=0
        self._inflight=set()
        self._lock=RLock()

    def clear(self):
        with self._lock:
            self._items.clear();self._inflight.clear();self._bytes=0
            self._epoch+=1

    def get(self,path):
        key=str(Path(path))
        with self._lock:
            if key not in self._items:return None
            self._items.move_to_end(key)
            return self._items[key]

    def put(self,path,array,epoch=None):
        if not isinstance(array,np.ndarray):raise TypeError('Cache accepts only NumPy arrays')
        key=str(Path(path))
        size=array.nbytes
        with self._lock:
            if epoch is not None and epoch!=self._epoch:return False
            if size>self.max_bytes:return False
            if key in self._items:
                self._bytes-=self._items.pop(key).nbytes
            self._items[key]=array
            self._bytes+=size
            while self._bytes>self.max_bytes:
                self._bytes-=self._items.popitem(last=False)[1].nbytes
            return True

    def prefetch(self,path,loader,estimate=None):
        key=str(Path(path))
        with self._lock:
            if key in self._items or key in self._inflight:return False
            self._inflight.add(key)
            epoch=self._epoch
        try:
            if estimate is not None and estimate(path)>self.max_bytes:
                return False
            array=loader(path)
            return self.put(path,array,epoch)
        except (OSError,ValueError):
            return False
        finally:
            with self._lock:self._inflight.discard(key)

    @property
    def bytes_used(self):
        with self._lock:return self._bytes
