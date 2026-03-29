# SPDX-License-Identifier: LGPL-2.1-or-later

try:
    from PySide import QtCore, QtGui
    QtWidgets = QtGui
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide6 import QtCore, QtGui, QtWidgets


Signal = getattr(QtCore, "Signal", None) or getattr(QtCore, "pyqtSignal")
Slot = getattr(QtCore, "Slot", None) or getattr(QtCore, "pyqtSlot", lambda *args, **kwargs: (lambda fn: fn))
Qt = QtCore.Qt


def qapplication():
    app = getattr(QtWidgets, "QApplication", None)
    if app is None:
        app = getattr(QtGui, "QApplication", None)
    return app


def process_events():
    app = qapplication()
    if app is None:
        return
    instance = app.instance()
    if instance is not None:
        instance.processEvents()


def standard_button_value(button):
    return getattr(QtWidgets.QMessageBox, button, getattr(QtGui.QMessageBox, button))
