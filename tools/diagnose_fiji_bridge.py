"""Safe, read-only Fiji Bridge diagnostics (no secret tokens are printed)."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from loupe.fiji_bridge import receiver_status, autostart_status, bridge_info_path

if __name__=='__main__':
    state=receiver_status()
    print('LOUPE Fiji receiver state:',state)
    print('Bridge information file present:',bridge_info_path().is_file())
    if len(sys.argv)>1:
        executable=Path(sys.argv[1].strip('"'))
        print('Configured Fiji exe exists:',executable.is_file())
        print('AutoRun receiver installation:',autostart_status(executable))
    else:
        print('Optional: py tools\\diagnose_fiji_bridge.py "C:\\path\\to\\Fiji.app\\ImageJ-win64.exe"')
    if state not in ('READY','BUSY'):
        print('Fiji is not reporting an active LOUPE receiver. If Fiji is running,')
        print('use ImageJ / Fiji > Fiji auto-relay setup, then fully restart Fiji once.')
