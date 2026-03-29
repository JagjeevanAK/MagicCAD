# SPDX-License-Identifier: LGPL-2.1-or-later

import inspect
import os

import FreeCAD
import FreeCADGui


def _add_command(name, command):
    try:
        lines, _line_no = inspect.getsourcelines(command.Activated)
        indent = len(lines[1]) - len(lines[1].lstrip(" \t")) if len(lines) > 1 else 0
        source = "".join(line[indent:] for line in lines[1:])
        FreeCADGui.addCommand(name, command, source)
    except Exception:
        FreeCADGui.addCommand(name, command)


def _controller():
    import DockPanel

    return DockPanel.get_controller()


class _BaseCommand:
    command_name = ""
    pixmap = "Std_Tool1"
    menu_text = ""
    tool_tip = ""
    requires_document = False

    def IsActive(self):
        if not self.requires_document:
            return True
        return FreeCAD.ActiveDocument is not None

    def GetResources(self):
        return {
            "Pixmap": self.pixmap,
            "MenuText": self.menu_text,
            "ToolTip": self.tool_tip,
        }


class OpenPanelCommand(_BaseCommand):
    command_name = "MagicCADAI_Open"
    pixmap = os.path.join(os.path.dirname(__file__), "Resources", "icons", "MagicCADAIWorkbench.svg")
    menu_text = "Open MagicCAD AI"
    tool_tip = "Open the MagicCAD AI copilot and validation panel"

    def Activated(self):
        _controller().show_panel()


class ValidateDocumentCommand(_BaseCommand):
    command_name = "MagicCADAI_ValidateDocument"
    pixmap = "Part_CheckGeometry"
    menu_text = "Validate Document"
    tool_tip = "Run full-document AI-assisted validation"
    requires_document = True

    def Activated(self):
        _controller().show_panel()
        _controller().validate_document(selection_only=False, intent="validate")


class ValidateSelectionCommand(_BaseCommand):
    command_name = "MagicCADAI_ValidateSelection"
    pixmap = "Std_BoxSelection"
    menu_text = "Validate Selection"
    tool_tip = "Run focused validation on the current selection"
    requires_document = True

    def Activated(self):
        _controller().show_panel()
        _controller().validate_document(selection_only=True, intent="validate")


class ApplyDraftCommand(_BaseCommand):
    command_name = "MagicCADAI_ApplyDraft"
    pixmap = "Std_Apply"
    menu_text = "Apply Draft"
    tool_tip = "Approve and apply the currently proposed draft change"
    requires_document = True

    def Activated(self):
        _controller().show_panel()
        _controller().apply_pending_draft()


class ExportReportCommand(_BaseCommand):
    command_name = "MagicCADAI_ExportReport"
    pixmap = "Std_Save"
    menu_text = "Export Report"
    tool_tip = "Export the current MagicCAD AI validation report"
    requires_document = True

    def Activated(self):
        _controller().show_panel()
        _controller().export_report()


def register_commands():
    if getattr(register_commands, "_registered", False):
        return

    commands = [
        OpenPanelCommand(),
        ValidateDocumentCommand(),
        ValidateSelectionCommand(),
        ApplyDraftCommand(),
        ExportReportCommand(),
    ]
    for command in commands:
        _add_command(command.command_name, command)
    register_commands._registered = True
