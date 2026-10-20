"""Single source of truth for LOUPE application release identity.

App version, comparison schema version, and UI Standard version are
independent. Do not use the old Phase A prototype number as APP_VERSION.
"""
from __future__ import annotations
import json
from pathlib import Path

APP_NAME = "LOUPE"
APP_VERSION = "0.9.7"
APP_STATUS = "Development"  # Not a validated public 1.0.0 release.
UI_STANDARD_VERSION = "1.0"  # Separate UI design standard, not app SemVer.


def build_info():
    """Read optional packaging stamp; a source checkout runs without it."""
    path = Path(__file__).with_name("_build_info.json")
    default = {"build_utc": "unrecorded", "git_commit": "unrecorded"}
    if path.is_file():
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(values, dict) and values.get("application_version") == APP_VERSION:
                return {
                    "build_utc": str(values.get("build_utc") or "unrecorded"),
                    "git_commit": str(values.get("git_commit") or "unrecorded"),
                }
        except (OSError, ValueError, TypeError):
            pass
    return default


def release_identity():
    info = build_info()
    commit = info["git_commit"]
    short = commit[:12] if len(commit) == 40 else commit
    return f"{APP_NAME} v{APP_VERSION} [{APP_STATUS}] | Build={info['build_utc']} | Git={short}"
