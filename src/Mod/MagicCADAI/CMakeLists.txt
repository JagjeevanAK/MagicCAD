# SPDX-License-Identifier: LGPL-2.1-or-later

set(MagicCADAI_SCRIPTS
    __init__.py
    Init.py
    InitGui.py
    QtCompat.py
    Commands.py
    DockPanel.py
    Observers.py
    Snapshot.py
    Validators.py
    Highlighting.py
    BridgeClient.py
    ToolRegistry.py
    SessionObjects.py
    SidecarServer.py
)

set(MagicCADAI_ICONS
    Resources/icons/MagicCADAIWorkbench.svg
)

add_custom_target(MagicCADAI ALL
    SOURCES ${MagicCADAI_SCRIPTS} ${MagicCADAI_ICONS}
)

fc_copy_sources(MagicCADAI "${CMAKE_BINARY_DIR}/Mod/MagicCADAI" ${MagicCADAI_SCRIPTS})
fc_copy_sources(
    MagicCADAI
    "${CMAKE_BINARY_DIR}/${CMAKE_INSTALL_DATADIR}/Mod/MagicCADAI"
    ${MagicCADAI_ICONS}
)

install(
    FILES
        ${MagicCADAI_SCRIPTS}
    DESTINATION
        Mod/MagicCADAI
)

install(
    FILES
        ${MagicCADAI_ICONS}
    DESTINATION
        "${CMAKE_INSTALL_DATADIR}/Mod/MagicCADAI/Resources/icons"
)
