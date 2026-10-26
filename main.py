"""LOUPE launcher — one default process, explicitly requested extra windows.

Secondary invocations only send ACTIVATE over a user-specific Qt local socket.
No remote/network listener is created. If the local service cannot be
validated, fail closed instead of accidentally duplicating the application.
"""
import getpass
import hashlib
import logging
import os
from pathlib import Path
import sys

from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets
from loupe.app_icon import icon_path
from loupe.diagnostics import (start_logging, close_logging, logger, log_action,
                               start_fault_diagnostics, close_fault_diagnostics)
from loupe.gui import MainWindow
from loupe.ui_theme import apply_qt_theme
from loupe.version import APP_VERSION


def instance_service_name(username=None, home=None):
    username = username if username is not None else getpass.getuser()
    home = home if home is not None else str(Path.home())
    fingerprint = hashlib.sha256((username + '\0' + home).encode('utf-8')).hexdigest()[:20]
    return 'LOUPE-single-' + fingerprint


def activate_existing(service):
    """Return True only when an existing LOUPE acknowledges the request."""
    client = QtNetwork.QLocalSocket()
    client.connectToServer(service, QtCore.QIODevice.OpenModeFlag.ReadWrite)
    if not client.waitForConnected(350):
        client.abort()
        return False
    try:
        client.write(b'ACTIVATE\n')
        if not client.waitForBytesWritten(700):
            return False
        if not client.waitForReadyRead(900):
            return False
        return bytes(client.readAll()).startswith(b'OK')
    finally:
        client.disconnectFromServer()


class WindowManager(QtCore.QObject):
    """Own windows and serve ACTIVATE requests from the second launcher."""
    def __init__(self, app, service):
        super().__init__(app)
        self.app = app
        self.service = service
        self.windows = []
        self.number_issued = 0
        self.server = QtNetwork.QLocalServer(self)
        # Scope access to the current Windows user where supported by Qt.
        self.server.setSocketOptions(QtNetwork.QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(service):
            raise RuntimeError('Another LOUPE may be starting or the activation channel is occupied. '
                               'No additional process will be started.')
        self.server.newConnection.connect(self.accept_connection)

    def accept_connection(self):
        while self.server.hasPendingConnections():
            client = self.server.nextPendingConnection()
            client.readyRead.connect(lambda c=client: self.handle_connection(c))
            client.disconnected.connect(client.deleteLater)
            if client.bytesAvailable():
                self.handle_connection(client)

    def handle_connection(self, client):
        if bytes(client.readAll()).strip() != b'ACTIVATE':
            client.write(b'INVALID\n')
        else:
            self.activate()
            client.write(b'OK\n')
        client.flush()

    def activate(self):
        if not self.windows:
            return
        target = self.app.activeWindow()
        if target not in self.windows:
            target = self.windows[0]
        if target.isMinimized():
            target.showNormal()
        target.raise_()
        target.activateWindow()

    def new_window(self):
        if len(self.windows) >= 2:
            answer = QtWidgets.QMessageBox.question(
                self.windows[-1], 'LOUPE memory use',
                f'{len(self.windows)} LOUPE windows are already open. '
                'Each window maintains independent TIFF image caches and can consume significant RAM.\n\n'
                'Open another window?',
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No)
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return None
        self.number_issued += 1
        n = self.number_issued
        window = MainWindow(instance_number=n, new_window_callback=self.new_window)
        window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.setWindowTitle(f'LOUPE v{APP_VERSION} — Comparison {n}')
        self.windows.append(window)
        window.destroyed.connect(lambda _=None, w=window: self._remove_window(w))
        log_action('LOUPE window created', window=n, session=window.window_session_id)
        if n == 1:
            window.showMaximized()
        else:
            window.resize(1120, 820)
            window.showNormal()
            window.raise_()
        return window

    def _remove_window(self, target):
        self.windows = [w for w in self.windows if w is not target]


def _uncaught(error_type, value, traceback):
    logger().critical('Uncaught exception', exc_info=(error_type, value, traceback))
    if QtWidgets.QApplication.instance() is not None:
        QtWidgets.QMessageBox.critical(None, 'LOUPE error',
            f'Unexpected error: {value}\n\nUse Help → Export Bug Report to save the logs.')


def main():
    # Single-instance check is performed BEFORE touching session log files.
    service = instance_service_name()
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    if activate_existing(service):
        return 0
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('BL09W.LOUPE')
        except (OSError, AttributeError):
            pass
    try:
        manager = WindowManager(app, service)
    except RuntimeError as exc:
        QtWidgets.QMessageBox.warning(None, 'LOUPE already running', str(exc))
        return 1
    start_logging()
    start_fault_diagnostics()
    sys.excepthook = _uncaught
    app.setWindowIcon(QtGui.QIcon(str(icon_path())))
    theme_version = apply_qt_theme(app)
    logger().info('BL09W UI Standard v%s applied', theme_version)
    app.aboutToQuit.connect(close_fault_diagnostics)
    app.aboutToQuit.connect(close_logging)
    manager.new_window()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
