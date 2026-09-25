"""
tabs/10_suno_bulk_studio.py — ⚡ Bulk Video Studio (Suno Music Suite)
Mounts the complete 01_bulk_video_studio from Suno Music Tool with:
- Dual Studio Modes ("Image to Music" & "Video to Music")
- AI Background Removal Cutout
- Player Skin with 30+ moods
- Collapsible Accordions & Floating Action Controls
- Multi-resolution (720p, 1080p, 2K, 4K) & Automated Chapter Timestamps
"""

TAB_TITLE = "⚡  Bulk Video Studio"
TAB_ORDER = 1
TAB_GROUP = "Suno Music"
TAB_COLOR = ("#9d174d", "#db2777")
TAB_ICON  = "⚡"
LAZY_LOAD = True

import os
import sys

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HOT_PATCH = os.path.join(os.environ.get("LOCALAPPDATA", ""), "StoriesStudio", "hot_patches")
_SUNO_ROOT = os.path.join(_BASE_DIR, "Suno Music Tool", "Suno Music Tool")
_SUNO_TABS = os.path.join(_SUNO_ROOT, "tabs")

_SEARCH_PATHS = [
    _HOT_PATCH,
    _BASE_DIR,
    _SUNO_ROOT,
    _SUNO_TABS,
    os.path.join(getattr(sys, "_MEIPASS", ""), "Suno Music Tool", "Suno Music Tool"),
    os.path.join(getattr(sys, "_MEIPASS", ""), "Suno Music Tool", "Suno Music Tool", "tabs"),
]

for _p in _SEARCH_PATHS:
    if _p and os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


def create(parent_frame, boot_data=None):
    import importlib
    mod = importlib.import_module("01_bulk_video_studio")
    return mod.create(parent_frame, boot_data)
