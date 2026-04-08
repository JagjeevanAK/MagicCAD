# SPDX-License-Identifier: LGPL-2.1-or-later

import os


MODULE_NAME = "MagicCADAI"
WORKBENCH_NAME = "MagicCADAIWorkbench"
DEFAULT_MODEL = "gemini-2.5-flash"  # Gemini - fast and cost-effective
DEEP_REVIEW_MODEL = "gemini-2.5-pro"  # For complex analysis
BACKGROUND_MODEL = "gemini-2.5-flash-lite"  # For quick background tasks
RULEPACK_VERSION = "v1"

MODULE_DIR = os.path.dirname(__file__)
RESOURCE_DIR = os.path.join(MODULE_DIR, "Resources")
ICON_PATH = os.path.join(RESOURCE_DIR, "icons", "MagicCADAIWorkbench.svg")
SIDECAR_PATH = os.path.join(MODULE_DIR, "SidecarServer.py")


def resource_path(*parts):
    return os.path.join(RESOURCE_DIR, *parts)
