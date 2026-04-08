# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD

try:
    import FreeCADGui
except ImportError:
    FreeCADGui = None


class HighlightManager:
    def __init__(self):
        self._styles = {}

    def clear(self):
        if not FreeCAD.GuiUp or FreeCADGui is None:
            return
        for object_name, style in list(self._styles.items()):
            obj = FreeCAD.ActiveDocument.getObject(object_name) if FreeCAD.ActiveDocument else None
            if obj is None or not getattr(obj, "ViewObject", None):
                continue
            view = obj.ViewObject
            for prop_name, value in style.items():
                if hasattr(view, prop_name):
                    try:
                        setattr(view, prop_name, value)
                    except Exception:
                        pass
        self._styles = {}

    def highlight_issue(self, issue):
        if not issue or not FreeCAD.GuiUp or FreeCADGui is None or FreeCAD.ActiveDocument is None:
            return False

        object_name = issue.get("object_ref", {}).get("object_name", "")
        if not object_name:
            return False

        obj = FreeCAD.ActiveDocument.getObject(object_name)
        if obj is None:
            return False

        self.clear()
        view = getattr(obj, "ViewObject", None)
        if view is not None:
            saved = {}
            for prop_name in ("ShapeColor", "LineColor", "PointColor", "Transparency", "LineWidth"):
                if hasattr(view, prop_name):
                    try:
                        saved[prop_name] = getattr(view, prop_name)
                    except Exception:
                        continue
            self._styles[obj.Name] = saved
            if hasattr(view, "ShapeColor"):
                view.ShapeColor = (0.95, 0.35, 0.25)
            if hasattr(view, "LineColor"):
                view.LineColor = (1.0, 0.2, 0.2)
            if hasattr(view, "PointColor"):
                view.PointColor = (1.0, 0.2, 0.2)
            if hasattr(view, "Transparency"):
                view.Transparency = max(int(getattr(view, "Transparency", 0)), 15)
            if hasattr(view, "LineWidth"):
                view.LineWidth = max(int(getattr(view, "LineWidth", 1)), 3)

        try:
            FreeCADGui.Selection.clearSelection()
            sub_name = issue.get("subelement_ref", {}).get("subelement_name", "")
            if sub_name:
                FreeCADGui.Selection.addSelection(obj, sub_name)
            else:
                FreeCADGui.Selection.addSelection(obj)
            FreeCADGui.SendMsgToActiveView("ViewSelection")
        except Exception:
            pass
        return True
