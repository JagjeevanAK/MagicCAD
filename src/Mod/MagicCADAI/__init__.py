# SPDX-License-Identifier: LGPL-2.1-or-later

import os


MODULE_NAME = "MagicCADAI"
WORKBENCH_NAME = "MagicCADAIWorkbench"
DEFAULT_MODEL = "gpt-5.4"
DEEP_REVIEW_MODEL = "gpt-5.4-pro"
BACKGROUND_MODEL = "gpt-5.4-mini"
RULEPACK_VERSION = "v1"

MODULE_DIR = os.path.dirname(__file__)
RESOURCE_DIR = os.path.join(MODULE_DIR, "Resources")
ICON_PATH = os.path.join(RESOURCE_DIR, "icons", "MagicCADAIWorkbench.svg")
SIDECAR_PATH = os.path.join(MODULE_DIR, "SidecarServer.py")


def resource_path(*parts):
    return os.path.join(RESOURCE_DIR, *parts)
