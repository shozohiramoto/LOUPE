"""Small, dependency-free memory status provider. Values are bytes."""
import os
import ctypes


def memory_snapshot():
    """Return (total physical, used physical, available physical, process RSS).

    Returns None for unknown values; a failed query must never interrupt LOUPE.
    """
    try:
        if os.name == 'nt':
            from ctypes import wintypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [('dwLength',wintypes.DWORD),('dwMemoryLoad',wintypes.DWORD),
                    ('ullTotalPhys',ctypes.c_ulonglong),('ullAvailPhys',ctypes.c_ulonglong),
                    ('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),
                    ('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual',ctypes.c_ulonglong)]
            m = MEMORYSTATUSEX(); m.dwLength = ctypes.sizeof(m)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(MEMORYSTATUSEX)]
            kernel.GlobalMemoryStatusEx.restype=wintypes.BOOL
            if not kernel.GlobalMemoryStatusEx(ctypes.byref(m)):
                return None, None, None, None
            rss=None
            try:
                # PROCESS_MEMORY_COUNTERS; 2 DWORD + 8 SIZE_T values.
                class PMC(ctypes.Structure):
                    _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)] + [
                        (key,ctypes.c_size_t) for key in ('peak_ws','ws','q_peak_paged',
                        'q_paged','q_peak_nonpaged','q_nonpaged','pagefile','peak_pagefile')]
                proc=PMC(); proc.cb=ctypes.sizeof(proc)
                kernel.GetCurrentProcess.restype=wintypes.HANDLE
                psapi=ctypes.WinDLL('psapi',use_last_error=True)
                psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(PMC),wintypes.DWORD]
                psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
                if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(proc),proc.cb):
                    rss=int(proc.ws)
            except (OSError, ValueError, AttributeError):
                pass
            total=int(m.ullTotalPhys); avail=int(m.ullAvailPhys)
            return total,total-avail,avail,rss
        if os.path.exists('/proc/meminfo'):
            values={}
            with open('/proc/meminfo',encoding='ascii') as f:
                for line in f:
                    k,_,v=line.partition(':')
                    if k in ('MemTotal','MemAvailable'):
                        values[k]=int(v.strip().split()[0])*1024
            total=values.get('MemTotal');avail=values.get('MemAvailable')
            rss=None
            try:
                with open('/proc/self/statm',encoding='ascii') as f:
                    rss=int(f.read().split()[1])*os.sysconf('SC_PAGE_SIZE')
            except (OSError,ValueError,IndexError):pass
            return total,(total-avail) if total is not None and avail is not None else None,avail,rss
    except (OSError, ValueError, AttributeError, OverflowError):pass
    return None,None,None,None


def format_ram(total, used, avail, process):
    if not total or used is None:
        return 'RAM —', 'Memory information unavailable', None
    fraction=max(0,min(100,round(100*used/total)))
    gb=lambda x:f'{x/1024**3:.1f} GiB' if x is not None else 'unavailable'
    text=f'RAM {fraction}%  {gb(used)} / {gb(total)}'
    tip=f'PC total: {gb(total)}\nPC in use: {gb(used)}\nPC available: {gb(avail)}\nLOUPE process working set: {gb(process)}'
    return text,tip,fraction
