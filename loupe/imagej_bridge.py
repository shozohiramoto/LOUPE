"""Safe ImageJ/Fiji export and non-virtual TIFF stack preflight.

The GUI must never start a stack import without enough verified physical RAM
and a user-confirmed Java heap maximum.  No Virtual Stack fallbacks.
"""
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
import tifffile
from .exports import imagej_escape

MIB = 1024 ** 2

_RECENT_LAUNCH = 0.0

def recent_fiji_launch(seconds=35):
    return _RECENT_LAUNCH > 0 and time.monotonic()-_RECENT_LAUNCH < seconds


def heap_from_cfg(executable):
    """Try to read -Xmx from installation-local ImageJ.cfg / jvm options."""
    directory=Path(executable).parent
    candidates=[directory/'ImageJ.cfg', directory/'jvm.cfg', directory/'Fiji.app'/'ImageJ.cfg',
                directory/'java.opts',directory/'config'/'jvm.options']
    values=[]
    for path in candidates:
        if not path.is_file():continue
        try:content=path.read_text(encoding='utf-8-sig',errors='replace')
        except OSError:continue
        for number,unit in re.findall(r'-Xmx\s*(\d+(?:\.\d+)?)([kKmMgG]?)',content):
            value=float(number)*{'k':1/1024,'m':1,'g':1024,'':1/MIB}[unit.lower()]
            values.append(int(value))
    return min(values) if values else None


def physical_available():
    """Available system physical memory, without a third-party dependency."""
    if sys.platform=='win32':
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),
                ('total_phys',ctypes.c_ulonglong),('avail_phys',ctypes.c_ulonglong),
                ('total_page',ctypes.c_ulonglong),('avail_page',ctypes.c_ulonglong),
                ('total_virtual',ctypes.c_ulonglong),('avail_virtual',ctypes.c_ulonglong),
                ('avail_extended',ctypes.c_ulonglong)]
        m=MemoryStatus();m.length=ctypes.sizeof(m)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            raise OSError('Windows could not report available physical memory')
        return int(m.avail_phys)
    try:
        import psutil
        return int(psutil.virtual_memory().available)
    except ImportError:
        raise RuntimeError('Available physical memory cannot be measured safely')


def inspect_sequence(paths, *, cancellation=None, allow_subset=False):
    """Check every TIFF header (no bulk pixel read); enforce one grayscale page/frame."""
    paths=[Path(p) for p in paths]
    if not paths:raise ValueError('No TIFF stack data selected')
    if len(paths)>15000:raise ValueError('Stack length exceeds 15,000 slices')
    folders={p.resolve().parent for p in paths}
    if len(folders)!=1:raise ValueError('ImageJ Image Sequence requires one TIFF directory')
    ext={p.suffix.lower() for p in paths}
    if len(ext)!=1:raise ValueError('Mixed .tif/.tiff extensions cannot be imported reliably as one stack')
    directory=paths[0].parent
    # ImageJ Image Sequence is directory-based; avoid silently taking different TIFFs.
    found={p.resolve() for p in directory.iterdir() if p.suffix.lower() in ('.tif','.tiff') and p.is_file()}
    if allow_subset:
        found={p for p in found if p.suffix.lower()==next(iter(ext))}
    if not allow_subset and found!={p.resolve() for p in paths}:
        raise ValueError('The folder contains other TIFF files; isolate one sequence before import')
    start_index=1
    if allow_subset:
        ordered=sorted(found)
        selected=[p.resolve() for p in paths]
        if selected[0] not in ordered or selected!=ordered[ordered.index(selected[0]):ordered.index(selected[0])+len(selected)]:
            raise ValueError('Selected Stack must be contiguous in the sorted TIFF directory')
        start_index=ordered.index(selected[0])+1

    target_shape=None;dtype=None;raw_bytes=0
    for index,path in enumerate(paths):
        if cancellation is not None and cancellation(index,len(paths)):
            raise InterruptedError('Stack preflight cancelled by operator')
        with tifffile.TiffFile(str(path)) as tf:
            if len(tf.pages)!=1 or len(tf.series)!=1 or len(tf.series[0].shape)!=2:
                raise ValueError(f'Expected a single 2D grayscale TIFF: {path.name}')
            page=tf.pages[0]
            shape=tuple(page.shape)
            dt=np.dtype(page.dtype)
            if dt not in (np.dtype('uint8'),np.dtype('uint16'),np.dtype('float32')):
                raise ValueError(f'ImageJ stack requires uint8, uint16 or float32: {path.name} ({dt})')
            if target_shape is None: target_shape,dtype=shape,dt
            if shape!=target_shape or dt!=dtype:
                raise ValueError(f'Different image dimensions or pixel data types: {path.name}')
            raw_bytes+=math.prod(shape)*dt.itemsize
    return {'count':len(paths),'shape':target_shape,'dtype':str(dtype),
            'bytes':raw_bytes, 'directory':str(directory),'extension':next(iter(ext)),
            'starting': start_index}


def stack_preflight(info,available_bytes,heap_mib):
    if heap_mib is None or not math.isfinite(float(heap_mib)) or heap_mib<=0:
        raise ValueError('Java heap must be verified or explicitly entered before Stack import')
    if available_bytes is None or available_bytes<=0:
        raise ValueError('Available physical RAM must be known')
    raw=int(info['bytes'])
    # Memory headroom for ImageJ array copies, TIFF decoding and JVM runtime.
    needed=int(raw*1.65 + 768*MIB)
    if needed > .80*int(heap_mib)*MIB:
        raise MemoryError(f'Insufficient Java heap: needs ~{needed/MIB:.0f} MiB with safety margin, '
                          f'configured heap {int(heap_mib)} MiB')
    if needed > .75*available_bytes:
        raise MemoryError(f'Insufficient free physical RAM: needs ~{needed/MIB:.0f} MiB with safety margin, '
                          f'available {available_bytes/MIB:.0f} MiB')
    return needed


def imagej_stack_macro(info):
    # file= is ImageJ's filename filter in the Image Sequence importer.
    ext=info['extension']
    return (f'// LOUPE regular in-RAM Stack; NEVER Virtual Stack.\n'
            f'// LOUPE preflight: {info["count"]} images, {info["shape"]}, {info["dtype"]}.\n'
            f'run("Image Sequence...", "open=[{imagej_escape(info["directory"])}] '
            f'file={ext} starting={int(info.get("starting", 1))} number={info["count"]} increment=1 sort");\n'
            f'if (is("virtual")) {{ close(); exit("LOUPE: virtual stack is not permitted."); }}\n'
            f'if (nSlices != {info["count"]}) {{ close(); exit("LOUPE: unexpected slice count."); }}\n')


def imagej_current_macro(path):
    path=Path(path)
    if not path.is_file() or path.suffix.lower() not in ('.tif','.tiff'):
        raise ValueError('Select a local TIFF file')
    return f'open("{imagej_escape(path)}");\n'


def imagej_current_with_transfer_macro(path, transfer):
    """Fiji-new-process fallback; macro is internal and never exported.

    Uses only data and fixed ImageJ macro commands. Receiver remains preferred
    for an already-running Fiji. Generated ROIs preserve native pixel geometry.
    """
    code=imagej_current_macro(path)
    if not transfer:
        return code
    contrast=transfer.get('display')
    if contrast:
        code+=f'setMinAndMax({float(contrast["min"]):.15g}, {float(contrast["max"]):.15g});\n'
    cal=transfer.get('calibration')
    if cal:
        code+=(f'run("Properties...", "unit=um pixel_width={float(cal["width_um"]):.15g} '
               f'pixel_height={float(cal["height_um"]):.15g} voxel_depth=1");\n')
    roi_list=transfer.get('rois') or []
    if roi_list:
        for i,item in enumerate(roi_list,1):
            kind=item['type']
            if kind=='line':
                a,b=item['start'],item['end']
                code+=f'makeLine({a[0]:.12g}, {a[1]:.12g}, {b[0]:.12g}, {b[1]:.12g});\n'
            elif kind=='count':
                x,y=item['point'];code+=f'makePoint({x:.12g}, {y:.12g});\n'
            elif kind=='circle':
                x,y=item['center'];radius=item['radius']
                code+=f'makeOval({x-radius:.12g}, {y-radius:.12g}, {2*radius:.12g}, {2*radius:.12g});\n'
            elif kind=='ellipse' and not item.get('angle',0):
                x,y=item['center'];w,h=item['width'],item['height']
                code+=f'makeOval({x-w/2:.12g}, {y-h/2:.12g}, {w:.12g}, {h:.12g});\n'
            elif kind=='rect' and not item.get('angle',0):
                x,y,w,h=item['rect']
                code+=f'makeRectangle({x:.12g}, {y:.12g}, {w:.12g}, {h:.12g});\n'
            else:
                # Never silently substitute a wrong geometry.
                code+=f'print("LOUPE: rotated/unsupported ROI {i} not transferred");\n'
                continue
            if kind=='line' and int(transfer.get('line_width_px',1))>1:
                code+=f'run("Line Width...", "line={int(transfer["line_width_px"])}");\n'
            code+='roiManager("Add");\n'
        code+='roiManager("Show All");\n'
    return code


def launch_imagej_macro(executable,macro_path):
    executable=Path(executable)
    if not executable.is_file():raise FileNotFoundError(f'ImageJ/Fiji executable not found: {executable}')
    if not Path(macro_path).is_file():raise FileNotFoundError(macro_path)
    # Shell invocation prohibited: no shell expansions, no execution of TIFF contents.
    global _RECENT_LAUNCH
    child=subprocess.Popen([str(executable),'-macro',str(macro_path)],shell=False,
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    _RECENT_LAUNCH=time.monotonic()
    return child


def is_fiji_window(title, owner_executable, *, configured_executable=''):
    """Identify a genuine Fiji window, not e.g. 'Fiji - エクスプローラー'.

    Window titles alone are not trustworthy: Explorer displays the name of an
    open directory as a title.  Only a known Fiji launcher or a Java process
    owning an ImageJ/Fiji window qualifies.  No fuzzy substring matches.
    """
    name = Path(str(owner_executable)).name.casefold()
    configured = Path(str(configured_executable)).name.casefold()
    fiji_launchers = {'fiji-windows-x64.exe', 'fiji-win64.exe', 'fiji.exe',
                      'imagej-win32.exe', 'imagej-win64.exe', 'imagej.exe'}
    # java.exe/javaw.exe are shared by many applications and require a title.
    if configured not in {'java.exe', 'javaw.exe', ''}:
        fiji_launchers.add(configured)
    if name not in fiji_launchers | {'java.exe', 'javaw.exe'}:
        return False
    label = str(title).strip().casefold()
    return bool(re.match(r'^(?:\(just\)\s*)?(?:fiji|imagej)(?=$|\s|[-—|])', label))


def detect_running_fiji(executable):
    """Conservative Windows-only Fiji detection with owner-PID validation.

    A window's title is NOT evidence that Fiji is running: Windows Explorer
    calls a directory window 'Fiji - エクスプローラー'.  Enumerate both process
    names and window owners; accept only a known launcher or a Java process
    displaying a recognizable Fiji/ImageJ window.  Enumeration failure of
    tasklist fails closed (prevents unintentional multiple Fiji launches).
    """
    if sys.platform != 'win32':
        raise RuntimeError('Fiji process detection is supported on Windows only; do not auto-launch')
    import csv
    configured = Path(executable).name.casefold()
    proc = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True,
                          text=True, timeout=10,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if proc.returncode:
        raise RuntimeError('Could not check running Fiji processes; refusing new launch')
    launchers = {'imagej-win64.exe', 'imagej-win32.exe', 'imagej.exe',
                 'fiji.exe', 'fiji-win64.exe', 'fiji-windows-x64.exe'}
    if configured not in {'javaw.exe', 'java.exe'}:
        launchers.add(configured)
    process_by_pid = {}
    found = []
    for row in csv.reader(proc.stdout.splitlines()):
        if len(row) < 2:
            continue
        name, pid = row[0].strip(), row[1].strip()
        if not pid.isdigit():
            continue
        process_by_pid[int(pid)] = name
        if name.casefold() in launchers:
            found.append((name, pid))

    # Java-launched Fiji can use javaw.exe. Confirm the title AND the owning
    # PID's actual executable. An Explorer title is never sufficient.
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        # Explicit pointer-width HWND signatures matter on 64-bit Windows.
        for method, signature in (
            ('EnumWindows', [callback_type, wintypes.LPARAM]),
            ('IsWindowVisible', [wintypes.HWND]),
            ('GetWindowTextLengthW', [wintypes.HWND]),
            ('GetWindowTextW', [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
        ):
            fun = getattr(user32, method)
            if hasattr(fun, 'argtypes'):
                fun.argtypes = signature
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        @callback_type
        def callback(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if not n:
                return True
            title = ctypes.create_unicode_buffer(n+1)
            user32.GetWindowTextW(hwnd, title, n+1)
            owner_pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            owner_name = process_by_pid.get(owner_pid.value, '')
            if is_fiji_window(title.value, owner_name, configured_executable=configured):
                evidence = (owner_name, str(owner_pid.value))
                if evidence not in found:
                    found.append(evidence)
            return True
        user32.EnumWindows(callback, 0)
    except (OSError, AttributeError, TypeError, ValueError):
        # Positive matches from tasklist remain valid.  An unconfirmed window
        # title is never promoted to 'running Fiji'.
        pass
    return found


def recommended_stack_count(shape, dtype, available_bytes, heap_mib, cap=None):
    """Conservative recommended normal-Stack frame count for current free RAM.

    Uses same budget as stack_preflight and excludes 768 MiB of fixed JVM
    overhead. Zero means even a single slice cannot be safely loaded.
    """
    frame=int(np.prod(shape))*np.dtype(dtype).itemsize
    if frame <= 0 or available_bytes is None or heap_mib is None:
        return 0
    budget=min(0.75*int(available_bytes),0.8*float(heap_mib)*MIB)
    count=max(0,math.floor((budget-768*MIB)/(1.65*frame)))
    return min(count,int(cap)) if cap is not None else count
