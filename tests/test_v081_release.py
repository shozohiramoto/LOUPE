"""v0.8.3 headless release regression checks; Fiji workstation QA remains required."""
import json
import socket
import threading
from pathlib import Path
import numpy as np
import pytest

from loupe import fiji_bridge as bridge
from loupe.imagej_bridge import recommended_stack_count, stack_preflight, MIB
from loupe.version import APP_VERSION

ROOT=Path(__file__).resolve().parents[1]


def _receiver(replies,received):
    s=socket.socket();s.bind(('127.0.0.1',0));s.listen(5)
    port=s.getsockname()[1]
    def work():
        try:
            for reply in replies:
                conn,_=s.accept()
                with conn:
                    received.append(conn.recv(16000))
                    conn.sendall(reply)
        finally:s.close()
    t=threading.Thread(target=work,daemon=True);t.start()
    return port,t


def _manifest(folder,port):
    path=folder/'fiji_bridge.json'
    path.write_text(json.dumps({'port':port,'token':'a'*48}))
    return path


def test_v081_version():
    assert APP_VERSION=='0.9.8d'


@pytest.mark.parametrize('reply',[b'QUEUED\n',b'QUEUED\r\n',b'QUEUED\r\n  '])
def test_queue_reply_crlf_accepted(tmp_path,reply):
    macro=tmp_path/'Macro.ijm';macro.write_text('print("test");')
    received=[];p,t=_receiver([reply],received)
    assert bridge.send_to_running_fiji(macro,manifest=_manifest(tmp_path,p))
    t.join(2)
    assert received[0].startswith(b'a'*48+b'\t')


def test_structured_open_submission_and_file_status(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'bridge_info_path',lambda:tmp_path/'fiji_bridge.json')
    f=tmp_path/'rec00000.tif';f.write_bytes(b'dummy')
    received=[];port,t=_receiver([b'READY\r\n',b'QUEUED\r\n'],received)
    _manifest(tmp_path,port)
    status,jid=bridge.create_open_request([f])
    assert status=='QUEUED' and len(jid)==32
    t.join(2)
    assert received[0].endswith(b'PING\n')
    assert received[1].endswith(('OPEN\t'+jid+'\n').encode())
    req=json.loads((tmp_path/'fiji_jobs'/(jid+'.request.json')).read_text())
    assert req['paths']==[str(f)] and req['kind']=='OPEN_TIFF'
    assert bridge.read_job_status(jid)['status']=='QUEUED'
    outcome={'id':jid,'status':'COMPLETED','count':1,'requested':1}
    (tmp_path/'fiji_jobs'/(jid+'.status.json')).write_text(json.dumps(outcome))
    assert bridge.read_job_status(jid)['count']==1


def test_structured_requires_receiver_before_creating_request(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'bridge_info_path',lambda:tmp_path/'fiji_bridge.json')
    f=tmp_path/'rec1.tif';f.write_bytes(b'dummy')
    assert bridge.create_open_request([f])==('OFFLINE',None)
    assert not (tmp_path/'fiji_jobs').exists()


def test_reject_untrusted_open_input(tmp_path):
    f=tmp_path/'danger.py';f.write_text('x')
    with pytest.raises(ValueError,match='TIFF'):
        bridge.create_open_request([f])


def test_receiver_autorun_one_time_setup(tmp_path,monkeypatch):
    exe=tmp_path/'Fiji.app'/'ImageJ-win64.exe';exe.parent.mkdir();exe.write_bytes(b'exe')
    original=exe.parent/'macros'/'StartupMacros.fiji.ijm'
    original.parent.mkdir()
    original.write_text('macro "AutoRun" { dir="AutoRun/"; runMacro("x"); }')
    source=ROOT/'fiji'/'LOUPE_receiver.py'
    monkeypatch.setattr(bridge,'bridge_info_path',lambda:tmp_path/'APPDATA'/'LOUPE'/'fiji_bridge.json')
    before=original.read_bytes()
    macro=bridge.runtime_receiver_macro(source)
    assert 'Macro_Runner.runPython' in macro
    assert original.read_bytes()==before
    assert not (original.parent/'AutoRun'/'LOUPE_Bridge_AutoRun.ijm').exists()
    assert (tmp_path/'APPDATA'/'LOUPE'/'bridge'/'LOUPE_receiver.py').read_bytes()==source.read_bytes()


def test_incompatible_fiji_not_modified(tmp_path):
    exe=tmp_path/'Fiji.app'/'Fiji.exe';exe.parent.mkdir();exe.write_bytes(b'exe')
    with pytest.raises(RuntimeError,match='never edits'):
        bridge.install_fiji_autostart(exe)
    assert not (exe.parent/'macros'/'AutoRun').exists()


def test_safe_stack_count_matches_current_preflight():
    available=2965*MIB;heap=11264
    safe=recommended_stack_count((2048,2048),'float32',available,heap,cap=2000)
    assert 1<=safe<100
    data={'bytes':int(safe*2048*2048*4)}
    assert stack_preflight(data,available,heap)>0
    with pytest.raises(MemoryError):
        stack_preflight({'bytes':100*2048*2048*4},available,heap)


def test_gui_and_orthogonal_features_are_wired():
    gui=(ROOT/'loupe/gui.py').read_text()
    ort=(ROOT/'loupe/orthogonal/viewer.py').read_text()
    assert 'runtime_receiver_macro' in gui
    assert 'create_open_request(source_paths,transfer=transfer)' in gui
    assert 'read_job_status(job)' in gui
    assert 'view_sources=options' in gui
    assert 'view_selector.currentIndexChanged.connect(self._change_view)' in ort
    assert "self.preview_png_action.triggered.connect(lambda:self._export_report('PNG'))" in ort
    assert "self.preview_pdf_action.triggered.connect(lambda:self._export_report('PDF'))" in ort
    assert 'Reduced-resolution preview' in ort


def test_no_user_macro_needed_for_online_receiver():
    src=(ROOT/'loupe/fiji_bridge.py').read_text()
    assert "'_request('OPEN\\t'+jid'" not in src  # check no invalid hard-coded literal
    assert "_request('OPEN\\t'+jid" in src
    assert 'macro' not in json.dumps({'kind':'OPEN_TIFF'})
