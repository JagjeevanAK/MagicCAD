# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD

try:
    import FreeCADGui
except ImportError:
    FreeCADGui = None

import QtCompat

QtCore = QtCompat.QtCore


def _is_internal_object(obj):
    if obj is None:
        return False
    if getattr(obj, "Name", "") in (
        "MagicCADAIData",
        "MagicCADAISession",
        "MagicCADAIReport",
    ):
        return True
    proxy_type = getattr(getattr(obj, "Proxy", None), "Type", "")
    return str(proxy_type).startswith("MagicCADAI::")


class _Debouncer(QtCore.QObject):
    def __init__(self, callback, interval_ms=700):
        super(_Debouncer, self).__init__()
        self._callback = callback
        self._payload = None
        self._timer = QtCompat.QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._flush)

    def schedule(self, payload):
        self._payload = payload
        self._timer.start()

    def _flush(self):
        if self._payload is None:
            return
        payload = self._payload
        self._payload = None
        self._callback(payload)

class MagicCADDocumentObserver:
    def __init__(self, controller):
        self._controller = controller
        self._debouncer = _Debouncer(self._dispatch)
        self._restoring_documents = set()

    def start(self):
        FreeCAD.addDocumentObserver(self)

    def stop(self):
        try:
            FreeCAD.removeDocumentObserver(self)
        except Exception:
            pass

    def _schedule(self, reason, document=None):
        document = document or FreeCAD.ActiveDocument
        if document is None:
            return
        # Suppress observer events while a document is being restored;
        # touching objects during restore can crash FreeCAD (SIGABRT in
        # Part::getPyShapes or SIGSEGV in PropertyLink::getValue).
        if document.Name in self._restoring_documents:
            return
        self._debouncer.schedule({"reason": reason, "document_name": document.Name})

    def _dispatch(self, payload):
        document = FreeCAD.getDocument(payload.get("document_name", "")) if payload else None
        if document is None and FreeCAD.ActiveDocument is not None:
            document = FreeCAD.ActiveDocument
        self._controller.on_document_event(payload.get("reason", "document"), document)

    def slotActivateDocument(self, document):
        self._schedule("activate", document)

    def slotCreatedDocument(self, document):
        self._schedule("created_document", document)

    def slotDeletedDocument(self, document):
        self._restoring_documents.discard(document.Name)
        self._controller.on_document_closed(document)

    def slotStartRestoreDocument(self, document):
        self._restoring_documents.add(document.Name)

    def slotFinishRestoreDocument(self, document):
        self._restoring_documents.discard(document.Name)
        self._schedule("activate", document)

    def slotCreatedObject(self, obj):
        if _is_internal_object(obj):
            return
        self._schedule("created_object", obj.Document)

    def slotDeletedObject(self, obj):
        if _is_internal_object(obj):
            return
        document = getattr(obj, "Document", None)
        if document is not None:
            self._schedule("deleted_object", document)

    def slotChangedObject(self, obj, prop):
        if _is_internal_object(obj):
            return
        if prop in ("Label", "Visibility", "Placement"):
            return
        self._schedule("changed_object", obj.Document)

    def slotRecomputedObject(self, obj):
        if _is_internal_object(obj):
            return
        self._schedule("recomputed_object", obj.Document)

    def slotRecomputedDocument(self, document):
        self._schedule("recomputed_document", document)

    def slotUndoDocument(self, document):
        self._schedule("undo", document)

    def slotRedoDocument(self, document):
        self._schedule("redo", document)

    def slotStartSaveDocument(self, document, filepath):
        self._schedule("start_save", document)

    def slotFinishSaveDocument(self, document, filepath):
        self._schedule("finish_save", document)


class MagicCADSelectionObserver:
    def __init__(self, controller):
        self._controller = controller
        self._debouncer = _Debouncer(self._dispatch, interval_ms=400)

    def start(self):
        if FreeCADGui is not None:
            FreeCADGui.Selection.addObserver(self)

    def stop(self):
        if FreeCADGui is not None:
            try:
                FreeCADGui.Selection.removeObserver(self)
            except Exception:
                pass

    def _schedule(self, reason, document_name):
        if not document_name:
            return
        self._debouncer.schedule({"reason": reason, "document_name": document_name})

    def _dispatch(self, payload):
        document = FreeCAD.getDocument(payload.get("document_name", "")) if payload else None
        if document is None and FreeCAD.ActiveDocument is not None:
            document = FreeCAD.ActiveDocument
        self._controller.on_selection_event(payload.get("reason", "selection"), document)

    def addSelection(self, document_name, object_name, sub_name, position):
        self._schedule("add_selection", document_name)

    def removeSelection(self, document_name, object_name, sub_name):
        self._schedule("remove_selection", document_name)

    def setSelection(self, document_name):
        self._schedule("set_selection", document_name)

    def clearSelection(self, document_name):
        self._schedule("clear_selection", document_name)


class ObserverBundle:
    def __init__(self, controller):
        self._document_observer = MagicCADDocumentObserver(controller)
        self._selection_observer = MagicCADSelectionObserver(controller)
        self._started = False

    def start(self):
        if self._started:
            return
        self._document_observer.start()
        self._selection_observer.start()
        self._started = True

    def stop(self):
        if not self._started:
            return
        self._document_observer.stop()
        self._selection_observer.stop()
        self._started = False
