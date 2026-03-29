# SPDX-License-Identifier: LGPL-2.1-or-later

import os

import FreeCAD
import FreeCADGui as Gui


class MagicCADAIWorkbench(Workbench):
    def __init__(self):
        resource_root = FreeCAD.getResourceDir()
        icon_candidates = (
            os.path.join(
                resource_root, "Mod", "MagicCADAI", "Resources", "icons", "MagicCADAIWorkbench.svg"
            ),
            os.path.join(
                resource_root,
                "share",
                "Mod",
                "MagicCADAI",
                "Resources",
                "icons",
                "MagicCADAIWorkbench.svg",
            ),
        )
        self.__class__.Icon = next(
            (path for path in icon_candidates if os.path.exists(path)),
            icon_candidates[0],
        )
        self.__class__.MenuText = "MagicCAD AI"
        self.__class__.ToolTip = "AI copilot and validation tools for MagicCAD"

    def Initialize(self):
        import Commands
        import DockPanel

        Commands.register_commands()
        DockPanel.get_controller().ensure_initialized()

        commands = [
            "MagicCADAI_Open",
            "MagicCADAI_ValidateDocument",
            "MagicCADAI_ValidateSelection",
            "MagicCADAI_ApplyDraft",
            "MagicCADAI_ExportReport",
        ]
        self.appendToolbar("MagicCAD AI", commands)
        self.appendMenu(["MagicCAD AI"], commands)
        FreeCAD.Console.PrintLog("MagicCADAI workbench loaded\n")

    def Activated(self):
        import DockPanel

        DockPanel.get_controller().ensure_initialized()

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(MagicCADAIWorkbench())
