"""v0.7.0-beta.1 headless acceptance checks; Windows GUI needs manual QA."""
from pathlib import Path
import json
import socket
import threading

import numpy as np
import pytest

from loupe.fiji_bridge import send_to_running_fiji
from loupe.report import has_renderable_profile

ROOT = Path(__file__).resolve().parents[1]


def test_profile_blank_removed_even_when_mode_on_but_no_samples():
    assert not has_renderable_profile(None)
    assert not has_renderable_profile({'profile':([1],[5])})
    assert not has_renderable_profile({'profile':([1,2],[float('nan'),2])})
    assert not has_renderable_profile({'profile':([1,2],[float('nan'),float('inf')])})
    assert has_renderable_profile({'profile':([1,2],[3,4])})
    assert has_renderable_profile({'profile':(np.array([1,2]),np.array([3,4]))})


def test_report_both_formats_use_one_conditional_renderer():
    source=(ROOT/'loupe/report.py').read_text(encoding='utf8')
    assert 'if profile_record is not None:' in source
    assert 'image_box=QtCore.QRectF(x+20,y+content_top,card_w-40,max(100,card_h-content_top-26))' in source
    assert "profile_record=panel.get('profile') if has_renderable_profile" in source
    assert 'render_report_image(panels' in source


def test_slider_preview_does_not_change_width():
    src=(ROOT/'loupe/gui.py').read_text(encoding='utf8')
    assert 'self.counter.setFixedWidth(110)' in src
    assert "self.counter.setText(f'{number} / {len(self.files)}')" in src
    assert "setTracking(False)" in src
    assert "(release to load)" not in src


def test_single_instance_and_opt_in_window():
    src=(ROOT/'main.py').read_text(encoding='utf8')
    from ast import parse
    parse(src)
    assert 'activate_existing(service)' in src
    assert "'New Window'" in (ROOT/'loupe/gui.py').read_text(encoding='utf8')
    assert 'window.showMaximized()' in src
    assert 'window.showNormal()' in src
    assert 'UserAccessOption' in src


def test_windows_icon_is_pixel_crisp_and_outside_transparent():
    from PIL import Image
    image=Image.open(ROOT/'assets/loupe.png').convert('RGBA')
    assert image.size==(256,256)
    # v0.9.1: user-supplied magnifying-glass pixel art replaces earlier palette.
    assert image.getbbox() is not None
    assert len(image.getcolors(maxcolors=256*256) or [])>4
    assert (ROOT/'assets/loupe.ico').stat().st_size>1000


def _fake_receiver(reply, received):
    s=socket.socket()
    s.bind(('127.0.0.1',0));s.listen(1)
    port=s.getsockname()[1]
    def work():
        try:
            conn,_=s.accept()
            with conn:
                received.append(conn.recv(16384))
                conn.sendall(reply)
        finally:s.close()
    thread=threading.Thread(target=work,daemon=True)
    thread.start()
    return port,thread


def test_authenticated_fiji_macro_relay(tmp_path):
    macro=tmp_path/'LOUPE_Test.ijm';macro.write_text('print("hello");',encoding='utf8')
    received=[]
    port,t=_fake_receiver(b'QUEUED\n',received)
    manifest=tmp_path/'bridge.json'
    token='a'*40
    manifest.write_text(json.dumps({'port':port,'token':token}),encoding='utf8')
    assert send_to_running_fiji(macro,manifest=manifest)
    t.join(1)
    assert received[0]==f'{token}\t{macro.resolve()}\n'.encode('utf8')


def test_fiji_without_active_relay_never_auto_launch(tmp_path):
    macro=tmp_path/'LOUPE_Test.ijm';macro.write_text('print(1);')
    assert not send_to_running_fiji(macro,manifest=tmp_path/'no_file.json')
    bad=tmp_path/'bad.json';bad.write_text('{notjson')
    assert not send_to_running_fiji(macro,manifest=bad)
    wrong=tmp_path/'bad.txt';wrong.write_text('')
    with pytest.raises(ValueError,match='ijm'):
        send_to_running_fiji(wrong,manifest=bad)


def test_fiji_relay_busy_or_failed_is_not_success(tmp_path):
    macro=tmp_path/'LOUPE_Test.ijm';macro.write_text('')
    received=[];port,t=_fake_receiver(b'BUSY\n',received)
    manifest=tmp_path/'bridge.json';manifest.write_text(json.dumps({'port':port,'token':'x'*48}))
    assert not send_to_running_fiji(macro,manifest=manifest)
    t.join(1)


def test_atomic_exports_preserved():
    from loupe.output_paths import reserve_unique_path,rollback_empty
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        a=reserve_unique_path(Path(d)/'a.txt')
        b=reserve_unique_path(Path(d)/'a.txt')
        assert a!=b
        rollback_empty(a);rollback_empty(b)


def test_qt_optional_windows_event_smoke():
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    # Running this test on Windows/Qt-capable CI should exercise the GUI itself.
    from PySide6 import QtWidgets
    from loupe.gui import MainWindow
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window=MainWindow()
    assert window.panels[0].counter.width()==110
    assert window._new_window_callback is None
    window.close()
