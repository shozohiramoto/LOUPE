"""v0.9.5 ID047/ID050 and runtime-only ImageJ1 RMI contracts."""
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile
import ast
import pytest
from loupe import fiji_bridge as b
from loupe import fiji_rmi as rmi
from loupe.version import APP_VERSION

ROOT=Path(__file__).resolve().parents[1]
GUI=(ROOT/'loupe'/'gui.py').read_text(encoding='utf-8')


def test_release_and_unmodified_094_features():
    assert APP_VERSION=='0.9.8d'
    ast.parse(GUI)
    assert 'self._pending_fiji_job=(job,_time.monotonic())' in GUI
    assert 'source_paths=selected' in GUI
    assert "self.roi_layer.apply_annotations_from_history" in (
        ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf-8')


def test_id047_pixel_value_and_unit_never_split():
    assert 'LOUPE_PixelSizeUnitGroup' in GUI
    assert 'self.calibration_value_layout.addWidget(self.cal_size)' in GUI
    assert 'self.calibration_value_layout.addWidget(self.cal_unit)' in GUI
    assert 'self.calibration_value_layout.addStretch(1)' in GUI
    assert GUI.count('(self.show_scale_bar,1,0,1,3)')==4
    assert '(self.cal_unit,1,0,1,1)' not in GUI


def test_id050_end_user_labels():
    assert "addMenu('ImageJ/Fiji')" in GUI
    assert "addAction('ImageJ/Fiji Connection Check…')" in GUI
    assert "Locate ImageJ/Fiji executable" in GUI
    assert 'ImageJ / Fiji' not in GUI
    assert 'Fiji auto-relay setup' not in GUI


def test_no_startup_replacement_even_with_consent(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'Local'))
    exe=tmp_path/'Fiji.app'/'ImageJ-win64.exe'
    exe.parent.mkdir()
    exe.write_bytes(b'exe')
    startup=exe.parent/'macros'/'StartupMacros.fiji.ijm'
    startup.parent.mkdir()
    data=b'run("scientific analysis");\r\n'
    startup.write_bytes(data)
    receiver=tmp_path/'source.py';receiver.write_text('# dummy')
    with pytest.raises(RuntimeError,match='never edits'):
        b.install_fiji_autostart(exe,receiver,allow_custom_startup_repair=True)
    macro=b.runtime_receiver_macro(receiver)
    assert 'Macro_Runner.runPython' in macro
    assert startup.read_bytes()==data
    assert not (startup.parent/'AutoRun').exists()
    assert (tmp_path/'Local'/'LOUPE'/'bridge'/'LOUPE_receiver.py').exists()
    assert 'StartupMacros' not in macro


def _synthetic_ij_jar(tmp_path):
    exe=tmp_path/'Fiji.app'/'ImageJ-win64.exe'
    exe.parent.mkdir()
    exe.write_bytes(b'exe')
    jar=exe.parent/'jars'/'ij-1.54-test.jar'
    jar.parent.mkdir()
    with ZipFile(jar,'w') as z:
        z.writestr('ij/OtherInstance.class',b'fake')
        z.writestr('ij/ImageJ.class',b'fake')
    return exe,jar


def test_java_client_uses_only_selected_fiji_jar(tmp_path,monkeypatch):
    exe,jar=_synthetic_ij_jar(tmp_path)
    assert rmi.imagej_jar(exe)==jar
    source=tmp_path/'import.ijm';source.write_text('// internal')
    fake_java=tmp_path/'java.exe';fake_java.write_bytes(b'')
    monkeypatch.setattr(rmi.sys,'platform','win32')
    monkeypatch.setattr(rmi,'java_executable',lambda _: fake_java)
    call=[]
    def fake_run(cmd,**kw):
        call.append((cmd,kw))
        return Mock(returncode=0,stdout='DELIVERED\n',stderr='')
    monkeypatch.setattr(rmi.subprocess,'run',fake_run)
    status,detail=rmi.send_macro_to_existing_fiji(exe,source)
    assert status=='DELIVERED'
    assert len(call)==1
    assert call[0][0][0]==str(fake_java)
    assert 'LoupeOtherInstanceClient' in call[0][0]
    assert '-macro' not in call[0][0] # Only the child helper calls ImageJ1 remote API
    assert 'java.awt.headless=true' in call[0][0][1]
    assert 'shell' not in call[0][1] # subprocess list form, never shell=True


def test_no_rmi_on_non_windows_and_invalid_macro(tmp_path):
    f=tmp_path/'x.ijm';f.write_text('// internal')
    if rmi.sys.platform != 'win32':
        assert rmi.send_macro_to_existing_fiji('/missing/fiji.exe',f)[0]=='UNAVAILABLE'
    invalid=tmp_path/'danger.py';invalid.write_text('x')
    with pytest.raises(ValueError,match='internal .ijm'):
        rmi.send_macro_to_existing_fiji('/missing',invalid)


def test_protocol_only_reports_delivery_not_image_completion():
    source=(ROOT/'tools/java/LoupeOtherInstanceClient.java').read_text(encoding='utf-8')
    assert 'sendArguments' in source
    assert 'RMI_STUB_ABSENT' in source
    assert 'DELIVERED' in source
    assert 'IJ.runMacroFile' not in source
    assert "No second Fiji process was started" in GUI
    assert 'Fiji receiver not READY' in GUI
