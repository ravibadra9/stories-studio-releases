"""
tabs/17_bulk_video_uploader.py — 🚀 Bulk Video Uploader Tab Plugin (Video Tool)
══════════════════════════════════════════════════════════════════════════════
Direct YouTube Cloud Studio Integration:
- Upload single or multiple rendered videos in bulk (Parallel or Sequential)
- Schedule publish date & time with YouTube Studio Timezones & RDP automation
- Channel Management & Google OAuth integration
- Seamless integration with Universal Master Render Queue
"""

TAB_TITLE = "🚀  Bulk Video Uploader"
TAB_ORDER = 22
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
