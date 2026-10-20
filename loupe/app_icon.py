"""Single icon reference for Qt window, taskbar and About dialog."""
from pathlib import Path

def icon_path():
    return Path(__file__).resolve().parent.parent / "assets" / "loupe.png"

def windows_icon_path():
    return icon_path().with_suffix('.ico')
