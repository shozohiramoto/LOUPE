"""Local, user-readable LOUPE session logs and opt-in private bug-report ZIPs."""
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from pathlib import Path
import os
import platform
import re
import sys
import uuid
import zipfile

from .version import APP_VERSION, APP_STATUS, UI_STANDARD_VERSION, build_info, release_identity

VERSION = APP_VERSION  # Legacy import compatibility: diagnostics.VERSION
SESSION = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
_LOGGER = logging.getLogger('LOUPE')
_LOGGER.addHandler(logging.NullHandler())
_ROOT = None
_PREV_CRASH = False


def log_root():
    return Path(os.environ.get('LOCALAPPDATA') or (Path.home() / '.local' / 'share')) / 'LOUPE' / 'logs'


def start_logging(root=None):
    global _ROOT, _PREV_CRASH
    root = Path(root) if root else log_root()
    root.mkdir(parents=True, exist_ok=True)
    _ROOT = root
    marker = root / 'running.marker'
    _PREV_CRASH = marker.exists()
    marker.write_text(SESSION, encoding='utf-8')
    _LOGGER.setLevel(logging.INFO)
    for handler in _LOGGER.handlers[:]:
        _LOGGER.removeHandler(handler)
        handler.close()
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    for name, level in [(f'LOUPE_{SESSION}.log', logging.INFO), (f'LOUPE_{SESSION}_errors.log', logging.ERROR)]:
        handler = RotatingFileHandler(root / name, maxBytes=2_000_000, backupCount=2, encoding='utf-8')
        handler.setLevel(level)
        handler.setFormatter(fmt)
        _LOGGER.addHandler(handler)
    _LOGGER.info('%s | UI Standard v%s | Session=%s', release_identity(), UI_STANDARD_VERSION, SESSION)
    if _PREV_CRASH: _LOGGER.warning('Previous session may have terminated abnormally')
    purge_old_logs(root)
    return root


def purge_old_logs(root, days=30):
    cutoff = datetime.now().timestamp() - days * 86400
    for path in Path(root).glob('LOUPE_*.log*'):
        try:
            if path.stat().st_mtime < cutoff: path.unlink()
        except OSError: pass


def logger():
    return _LOGGER


def log_action(message, **fields):
    # Add per-window tracking without changing every existing operation logger.
    # Runs only on GUI/main thread; absence of Qt or an active window is benign.
    if 'window' not in fields:
        try:
            from PySide6.QtWidgets import QApplication
            app=QApplication.instance()
            window=app.activeWindow() if app is not None else None
            if window is not None and hasattr(window,'instance_number'):
                fields['window']=window.instance_number
                fields['window_session']=window.window_session_id
        except (ImportError,AttributeError,RuntimeError):
            pass
    # File paths are caller-supplied only as a basename and must never be logged raw.
    safe = ' '.join(f'{k}={v}' for k, v in fields.items())
    _LOGGER.info('[ACTION] %s%s', message, (' | ' + safe) if safe else '')


def close_logging():
    _LOGGER.info('Normal application exit | Session=%s', SESSION)
    if _ROOT:
        try:
            marker=_ROOT / 'running.marker'
            if marker.exists() and marker.read_text(encoding='utf-8')==SESSION:marker.unlink()
        except OSError:pass


def sanitize(text):
    """Redact common paths, home directories, and account identifiers for portable ZIP."""
    text=str(text)
    homes = {str(Path.home()), os.environ.get('USERPROFILE',''), os.environ.get('HOME','')}
    for home in sorted(filter(None,homes),key=len,reverse=True):
        text = re.sub(re.escape(home), '<USER_HOME>', text, flags=re.IGNORECASE)
    text = re.sub(r'(?i)([A-Z]:\\Users\\)[^\\\s]+', r'\1<USER>', text)
    text = re.sub(r'(?i)([A-Z]:/Users/)[^/\s]+', r'\1<USER>', text)
    text = re.sub(r'(?i)(\\\\[^\\\s]+\\)[^\\\s]+', r'\1<SHARE>', text)
    return text


def create_bug_report(destination, description='', expected='', include_logs=True,
                      include_environment=True, root=None, screenshot=None):
    """Only write ZIP to a user-chosen destination; never upload/send data."""
    root = Path(root) if root else (_ROOT or log_root())
    destination = Path(destination)
    manifest = ['LOUPE Bug Report', f'Version: {VERSION}', f'Status: {APP_STATUS}',
                f'UI Standard: {UI_STANDARD_VERSION}', f'Build UTC: {build_info()["build_utc"]}',
                f'Git Commit: {build_info()["git_commit"]}', f'Session: {SESSION}',
                '', 'What happened:', sanitize(description), '', 'Expected:', sanitize(expected), '']
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('report.txt', '\n'.join(manifest))
        if include_logs:
            for filename, target in [(f'LOUPE_{SESSION}.log','loupe.log'),
                                     (f'LOUPE_{SESSION}_errors.log','error.log')]:
                source=root/filename
                if source.exists():
                    archive.writestr(target, sanitize(source.read_text(encoding='utf-8',errors='replace')))
        if include_environment:
            env=(f'{release_identity()}\nUI Standard: {UI_STANDARD_VERSION}\n'
                 f'OS: {platform.system()} {platform.release()}\nPython: {platform.python_version()}\n')
            try:
                from PySide6 import __version__ as qt_ver
                import pyqtgraph as pg
                env += f'PySide6: {qt_ver}\npyqtgraph: {pg.__version__}\n'
            except ImportError:pass
            archive.writestr('environment.txt',env)
        # A screenshot is optional and provided explicitly. Do not add original TIFF.
        if screenshot is not None and Path(screenshot).is_file():
            archive.write(screenshot, arcname='screenshot'+Path(screenshot).suffix.lower())
    return destination
