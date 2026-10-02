"""
tabs/12_suno_bulk_generator.py — 🚀 Bulk Generator (Suno Music Suite)
Mounts the complete 04_bulk_generator from Suno Music Tool with:
- Batch Prompt Multi-Job Queue
- Universal & Per-Song Style Dispatcher
- Real-time Progress Tracking
"""

TAB_TITLE = "⚡  Bulk Generator"
TAB_ORDER = 12
TAB_GROUP = "Suno Music"
TAB_COLOR = ("#06b6d4", "#22d3ee")
TAB_ICON  = "🚀"
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
    mod = importlib.import_module("04_bulk_generator")
    return mod.create(parent_frame, boot_data)
