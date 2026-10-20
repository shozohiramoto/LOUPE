"""Authenticated loopback Fiji bridge with automatic one-time startup installation.

Fiji must opt in via install_fiji_autostart(). Normal Open TIFF/Stack commands
are structured data; they do NOT create or execute user macros. The legacy
macro relay remains available for older receivers and Fiji launched from LOUPE.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import threading
import uuid
from datetime import datetime

_LOCK = threading.Lock()
MAX_REPLY = 256


def bridge_info_path():
    root = os.environ.get('LOCALAPPDATA') or str(Path.home() / '.local' / 'share')
    return Path(root) / 'LOUPE' / 'fiji_bridge.json'


def job_dir():
    return bridge_info_path().parent / 'fiji_jobs'


def _connection(manifest=None):
    path=Path(manifest) if manifest is not None else bridge_info_path()
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        port=int(data.get('port',0));token=data.get('token','')
        if 1024 <= port <= 65535 and isinstance(token,str) and len(token)>=32:
            return port,token
    except (OSError,ValueError,TypeError):
        pass
    return None


def _request(payload, manifest=None, timeout=1.5):
    auth=_connection(manifest)
    if auth is None:return 'OFFLINE'
    port,token=auth
    data=(token+'\t'+payload+'\n').encode('utf-8')
    if len(data)>8192:raise ValueError('Fiji relay command exceeds 8192 bytes')
    with _LOCK:
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=timeout) as sock:
                sock.settimeout(timeout)
                sock.sendall(data)
                reply=b''
                while len(reply)<MAX_REPLY and not reply.endswith(b'\n'):
                    block=sock.recv(min(64,MAX_REPLY-len(reply)))
                    if not block:break
                    reply+=block
        except (OSError,TimeoutError):return 'OFFLINE'
    try:return reply.strip(b'\r\n \t').decode('ascii')
    except UnicodeError:return 'INVALID_REPLY'


def receiver_status(manifest=None):
    """READY/BUSY/OFFLINE without triggering an image action."""
    return _request('PING',manifest)


def send_to_running_fiji(macro_path, manifest=None, timeout=1.5):
    """Backwards-compatible legacy macro transport; CRLF is valid on Windows."""
    macro_path=Path(macro_path).resolve(strict=True)
    if macro_path.suffix.lower()!='.ijm':
        raise ValueError('ImageJ relay only accepts generated .ijm macros')
    return _request(str(macro_path),manifest,timeout)=='QUEUED'


def create_open_request(paths, *, manifest=None, transfer=None):
    """Return (status, job_id), with a unique on-disk job request.

    Fiji receives only the job id; it validates TIFF files itself. No script
    text or arbitrary macro is transferred to a running Fiji.
    """
    frames=[Path(p).resolve(strict=True) for p in paths]
    if not frames or len(frames)>15000:
        raise ValueError('Select 1–15000 TIFF frames')
    if any(p.suffix.lower() not in ('.tif','.tiff') for p in frames):
        raise ValueError('Fiji bridge accepts only TIFF frames')
    if len({str(p) for p in frames})!=len(frames):
        raise ValueError('Duplicate TIFF frames in Fiji request')
    if transfer is not None:
        if len(json.dumps(transfer,ensure_ascii=True))>250000:
            raise ValueError('Fiji ROI transfer exceeds 250 KB')
        if transfer.get('schema')!='loupe_fiji_transfer_v1':
            raise ValueError('Unsupported Fiji transfer schema')
        if len(frames)!=1:
            raise ValueError('ROI and display transfer only applies to current single image')
    if receiver_status(manifest)!='READY':
        return 'OFFLINE', None
    if transfer is not None and _request('CAPS',manifest)!='TRANSFER_V1':
        # Old receivers would silently ignore new display/ROI data.
        return 'INCOMPATIBLE',None
    jid=uuid.uuid4().hex
    folder=job_dir();folder.mkdir(parents=True,exist_ok=True)
    target=folder/(jid+'.request.json')
    with target.open('x',encoding='utf-8') as f:
        json.dump({'protocol':1,'id':jid,'kind':'OPEN_STACK' if len(frames)>1 else 'OPEN_TIFF',
                   'paths':[str(p) for p in frames],
                   'transfer':transfer},f,ensure_ascii=False)
    status=_request('OPEN\t'+jid,manifest)
    if status!='QUEUED':
        target.unlink(missing_ok=True)
        return status,None
    return status,jid


def read_job_status(jid):
    if not isinstance(jid,str) or len(jid)!=32 or any(c not in '0123456789abcdef' for c in jid):
        raise ValueError('Invalid Fiji job id')
    path=job_dir()/(jid+'.status.json')
    if not path.is_file():return {'status':'QUEUED','count':0}
    try:
        result=json.loads(path.read_text(encoding='utf-8'))
        if result.get('id')!=jid:raise ValueError('Mismatched Fiji job status')
        return result
    except (OSError,ValueError):return {'status':'QUEUED','count':0}


def autostart_status(executable):
    """Read-only check: whether Fiji is configured to start our receiver.

    This checks installation artifacts, not whether a running Fiji actually
    invoked AutoRun. A READY handshake is required for operational status.
    """
    exe=Path(executable).expanduser()
    root=exe.parent
    hook=root/'macros'/'AutoRun'/'LOUPE_Bridge_AutoRun.ijm'
    receiver=bridge_info_path().parent/'bridge'/'LOUPE_receiver.py'
    if not startup_autorun_supported(exe):
        return 'STARTUP_UNSUPPORTED'
    if not hook.is_file() or not receiver.is_file():
        return 'NOT_INSTALLED'
    try:
        contents=hook.read_text(encoding='utf-8')
        expected=str(receiver.resolve()).replace('\\','/')
        if expected not in contents or 'Macro_Runner.runPython' not in contents:
            return 'OUTDATED'
    except OSError:
        return 'UNREADABLE'
    return 'INSTALLED'


def startup_autorun_supported(executable):
    """Read-only check for Fiji's macro/AutoRun startup loader."""
    startup=Path(executable).expanduser().parent/'macros'/'StartupMacros.fiji.ijm'
    if not startup.is_file():return False
    content=startup.read_text(encoding='utf-8',errors='replace')
    return ('macro "AutoRun"' in content and 'AutoRun/' in content
            and 'runMacro' in content)


def prepare_runtime_receiver(receiver_source=None):
    """Put LOUPE's Jython receiver in user-local storage (not Fiji/macros)."""
    source=(Path(receiver_source) if receiver_source is not None else
            Path(__file__).resolve().parents[1]/'fiji'/'LOUPE_receiver.py')
    if not source.is_file():
        raise FileNotFoundError(source)
    target=bridge_info_path().parent/'bridge'/'LOUPE_receiver.py'
    target.parent.mkdir(parents=True,exist_ok=True)
    if source.resolve()!=target.resolve():
        tmp=target.with_suffix('.tmp.'+uuid.uuid4().hex)
        try:
            shutil.copyfile(source,tmp)
            os.replace(tmp,target)
        finally:
            tmp.unlink(missing_ok=True)
    return target


def runtime_receiver_macro(receiver_source=None):
    """Start an in-memory Fiji bridge in THIS session via ImageJ1 macro IPC.

    Does not write to or require Fiji's StartupMacros or macros/AutoRun.
    ImageJ1 RMI delivery alone is not evidence of receiver readiness: only
    receiver_status() == READY confirms the listener can accept jobs.
    """
    source=prepare_runtime_receiver(receiver_source)
    path=str(source.resolve()).replace('\\','/')
    if any(c in path for c in ('\"','\r','\n')):
        raise ValueError('Unsafe Fiji receiver path')
    return ('// LOUPE runtime receiver: Fiji startup files remain unchanged.\n'
            f'LOUPE_runtime_source = "{path}";\n'
            'if (File.exists(LOUPE_runtime_source)) {\n'
            '  call("ij.plugin.Macro_Runner.runPython", File.openAsString(LOUPE_runtime_source), "");\n'
            '}\n')


def install_fiji_autostart(executable, receiver_source=None, *, allow_custom_startup_repair=False):
    """Disabled since v0.9.5; no silent or opt-in replacement is supported."""
    raise RuntimeError(
        'LOUPE v0.9.5 never edits Fiji StartupMacros or AutoRun. '
        'Use ImageJ1 runtime IPC instead.')


def minimal_autorun_loader():
    """Retired v0.9.4 repair interface (retained for migration only)."""
    raise RuntimeError('StartupMacros replacement is disabled since v0.9.5')
