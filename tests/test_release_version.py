"""v0.5.0 release metadata and schema compatibility checks (Qt-free)."""
import json
from pathlib import Path
from loupe import __version__
from loupe.diagnostics import VERSION
from loupe.version import (APP_VERSION, APP_STATUS, UI_STANDARD_VERSION,
                           build_info, release_identity)

ROOT = Path(__file__).resolve().parents[1]


def test_version_single_source():
    assert __version__ == VERSION == APP_VERSION == "0.9.8d"
    assert APP_STATUS == "Development"


def test_build_stamp_optional_and_stable():
    meta = build_info()
    assert "build_utc" in meta and "git_commit" in meta
    assert "LOUPE v0.9.8d" in release_identity()


def test_ui_theme_remains_independent_of_app_version():
    theme = json.loads((ROOT/"bl09w_ui"/"theme.json").read_text(encoding="utf-8"))
    assert theme["version"] == "1.0.0"
    assert UI_STANDARD_VERSION == "1.0"


def test_gui_displays_current_application_version():
    src = (ROOT/"loupe"/"gui.py").read_text(encoding="utf-8")
    assert "self.setWindowTitle(f'LOUPE v{VERSION}" in src
    assert "Phase A v1.6 | Multi-view comparison" not in src
    assert "build_info()" in src


def test_logs_and_bug_reports_use_release_identity():
    src = (ROOT/"loupe"/"diagnostics.py").read_text(encoding="utf-8")
    assert "VERSION = APP_VERSION" in src
    assert "Git Commit:" in src
    assert "APP_STATUS" in src
