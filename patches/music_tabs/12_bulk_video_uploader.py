"""
music_tabs/12_bulk_video_uploader.py — 🚀 Bulk Video Uploader Tab Plugin (Music Tool)
═══════════════════════════════════════════════════════════════════════════════════
Direct YouTube Cloud Studio Integration for Music Suite:
- Upload Song Video Maker, Prayer Shorts, and Suno Music videos directly to YouTube
- Batch multi-video upload (Parallel or Sequential)
- YouTube Studio schedule picker with Timezone & RDP automation
- Shared channel authentication & OAuth tokens
"""

TAB_TITLE = "🚀  Bulk Video Uploader"
TAB_ORDER = 45
TAB_GROUP = ""
TAB_COLOR = ("#b91c1c", "#dc2626")
TAB_ICON  = "🚀"
LAZY_LOAD = True

def create(parent_frame, boot_data=None):
    from uploader_engine.uploader_ui import BulkVideoUploaderFrame
    frame = BulkVideoUploaderFrame(parent_frame, boot_data=boot_data)
    frame.grid(row=0, column=0, sticky="nsew")
    try:
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1)
    except Exception:
        pass
    return frame
