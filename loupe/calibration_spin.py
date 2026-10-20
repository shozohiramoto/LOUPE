"""Explicit physical calibration entry, independent of QDoubleSpinBox arrows.

Changes are committed only on Return/focus loss. Keep the numeric API used by
existing LOUPE panels, but ensure the native QLineEdit always displays its text.
"""
import math
from PySide6 import QtWidgets, QtCore, QtGui


class CalibrationSpinBox(QtWidgets.QLineEdit):
    valueChanged = QtCore.Signal(float)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._minimum, self._maximum = 1e-6, 1e9
        self._decimals = 6
        self._value = 1.0
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.setValidator(QtGui.QDoubleValidator(self._minimum, self._maximum, 10, self))
        self.setText('1')
        self.editingFinished.connect(self._commit)

    def setDecimals(self, decimals):
        self._decimals = int(decimals)
        self.validator().setDecimals(max(self._decimals, 6))
        self.setValue(self._value)

    def setRange(self, minimum, maximum):
        self._minimum, self._maximum = float(minimum), float(maximum)
        self.validator().setBottom(self._minimum)
        self.validator().setTop(self._maximum)
        self.setValue(self._value)

    def setSingleStep(self, step):
        pass  # no stepping operation by design

    def setValue(self, value):
        value = float(value)
        if not (math.isfinite(value) and self._minimum <= value <= self._maximum):
            raise ValueError('Pixel size must be positive and finite')
        changed = value != self._value
        self._value = value
        # A fixed number of decimals is not forced: 0.650000 -> 0.65.
        self.setText(format(value, '.10g'))
        if changed:
            self.valueChanged.emit(value)

    def value(self):
        return self._value

    def _commit(self):
        try:
            raw = self.text().strip().replace(',', '.')
            value = float(raw)
            if not (math.isfinite(value) and self._minimum <= value <= self._maximum):
                raise ValueError(raw)
            self.setValue(value)
        except (TypeError, ValueError, OverflowError):
            self.setText(format(self._value, '.10g'))

    def wheelEvent(self, event):
        event.ignore()

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key.Key_Up, QtCore.Qt.Key.Key_Down,
                           QtCore.Qt.Key.Key_PageUp, QtCore.Qt.Key.Key_PageDown):
            event.ignore()
        else:
            super().keyPressEvent(event)
