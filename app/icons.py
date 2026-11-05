"""Line icons, drawn from SVG paths in code (no image files to ship).

24 x 24 grid, 1.7 px rounded strokes in the theme's text colour, with an
accent colour on the part that tells tools apart. They re-tint when the
theme changes (icons.retint(widget) or theme.hub.changed).
"""
from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# "A" = accent stroke, "AF" = accent fill (soft), "F" = text fill
_P = {
    # ---- file / edit ----
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1"/><path d="M3 7v10a2 2 0 0 0 2 2h13l3-8H7l-3 8"/>',
    "save": '<path d="M5 3h11l4 4v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a1 1 0 0 1 1-2z"/><path d="M8 3v5h7V3"/><rect A x="7" y="13" width="10" height="6" rx="1"/>',
    "print": '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path A d="M7 14h10v7H7z"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
    "find": '<circle cx="11" cy="11" r="7"/><path A d="m20 20-4-4"/>',
    "menu": '<path d="M4 6h16M4 12h16"/><path A d="M4 18h16"/>',
    "tools": '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect A x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "new": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path A d="M12 12v6M9 15h6"/>',
    "combine": '<rect x="3" y="3" width="10" height="13" rx="1.5"/><rect A x="11" y="8" width="10" height="13" rx="1.5"/>',
    "export": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path A d="M12 18v-7M9 14l3-3 3 3"/>',
    "import": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path A d="M12 11v7M9 15l3 3 3-3"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path A d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "compress": '<path d="M4 14h6v6M20 10h-6V4"/><path A d="m14 10 7-7M3 21l7-7"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path A d="M12 7v5l3 2"/>',
    "compare": '<rect x="3" y="4" width="11" height="14" rx="1.5"/><rect A x="10" y="7" width="11" height="14" rx="1.5"/>',
    "overlay": '<path d="m12 3 9 5-9 5-9-5z"/><path A d="m3 13 9 5 9-5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path A d="M12 11v6M12 7.5v.5"/>',
    "sign": '<path d="M3 17c3 0 4-8 7-8s1 8 4 8 3-4 5-4"/><path A d="M3 21h18"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path A d="m9 12 2 2 4-4"/>',
    "settings": '<circle A cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "sun": '<circle A cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path A d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "command": '<rect x="3" y="5" width="18" height="14" rx="2"/><path A d="m7 10 3 2-3 2M12 15h5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path A d="M3 10h18"/>',
    "layers": '<path A d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5M3 17l9 5 9-5"/>',
    "palette": '<path d="M12 3a9 9 0 0 0 0 18c1.1 0 1.8-.9 1.8-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-1 .8-1.8 1.8-1.8H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z"/><circle AF cx="7.5" cy="11" r="1.3"/><circle AF cx="11" cy="7" r="1.3"/><circle AF cx="15.5" cy="8.5" r="1.3"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path A d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "walls": '<path d="M3 4h18v16H3z"/><path d="M3 12h9v8"/><path A d="M15 20a3 3 0 0 0-3-3"/><path A d="M12 4v5"/>',
    "gantt": '<path d="M4 3v18h17"/><rect A x="7" y="6" width="7" height="3" rx="1"/><rect x="10" y="11" width="8" height="3" rx="1"/><rect A x="14" y="16" width="5" height="3" rx="1"/>',
    # ---- view ----
    "select": '<path d="M5 3l14 7-6 2-2 6z"/><path A d="m13 12 5 5"/>',
    "zoom": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.5-4.5"/><path A d="M8 10.5h5M10.5 8v5"/>',
    "zoom_out": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.5-4.5"/><path A d="M8 10.5h5"/>',
    "fit_width": '<rect x="3" y="5" width="18" height="14" rx="2"/><path A d="M7 12h10M7 12l2-2M7 12l2 2M17 12l-2-2M17 12l-2 2"/>',
    "fit_page": '<rect x="5" y="3" width="14" height="18" rx="2"/><path A d="M9 8h6v8H9z"/>',
    "page_next": '<path A d="m9 18 6-6-6-6"/>',
    "page_prev": '<path A d="m15 18-6-6 6-6"/>',
    "snap": '<path d="M6 3v7a6 6 0 0 0 12 0V3"/><path A d="M6 3h3v4H6zM15 3h3v4h-3z"/>',
    "panels": '<rect x="3" y="4" width="18" height="16" rx="2"/><path A d="M9 4v16"/>',
    # ---- markup ----
    "add_highlight": '<path d="m9 11 6-6 4 4-6 6"/><path d="M9 11 6 18l3 1 4-4"/><path A d="M3 21h10"/>',
    "add_underline": '<path d="M7 4v6a5 5 0 0 0 10 0V4"/><path A d="M5 20h14"/>',
    "add_strike": '<path d="M16 6a4 3 0 0 0-8 0c0 3 8 3 8 6a4 3 0 0 1-8 0"/><path A d="M4 12h16"/>',
    "add_rect": '<rect A x="4" y="5" width="16" height="14" rx="1.5"/>',
    "add_ellipse": '<ellipse A cx="12" cy="12" rx="9" ry="7"/>',
    "add_cloud": '<path A d="M6 18a3 3 0 0 1-.5-6A4 4 0 0 1 12 8a3.5 3.5 0 0 1 6.5 2A3 3 0 0 1 18 18z"/>',
    "add_line": '<path A d="M4 20 20 4"/>',
    "arrow": '<path A d="M5 19 19 5"/><path A d="M10 5h9v9"/>',
    "add_polyline": '<path A d="M3 18 9 9l5 6 7-10"/><circle F cx="9" cy="9" r="1.2"/><circle F cx="14" cy="15" r="1.2"/>',
    "add_polygon": '<path A d="m12 3 9 7-3.5 10h-11L3 10z"/>',
    "add_ink": '<path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/><path A d="m15 5 4 4"/>',
    "add_note": '<path d="M5 4h14a1 1 0 0 1 1 1v10l-5 5H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/><path A d="M20 15h-5v5M8 9h8M8 13h5"/>',
    "add_textbox": '<rect x="3" y="5" width="18" height="14" rx="1.5"/><path A d="M8 9h8M12 9v7"/>',
    "add_stamp": '<path d="M9 13V9a3 3 0 1 1 6 0v4"/><path d="M5 13h14v4H5z"/><path A d="M5 21h14"/>',
    "date_stamp": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/><path A d="M8 14h3v3H8z"/>',
    "callout": '<path d="M4 4h16v10H10l-4 4v-4H4z"/><path A d="M8 8h8M8 11h5"/>',
    "legend": '<rect x="3" y="4" width="18" height="16" rx="2"/><path A d="M7 9h2M7 13h2M7 17h2"/><path d="M12 9h5M12 13h5M12 17h5"/>',
    "add_redact": '<rect x="3" y="5" width="18" height="14" rx="1.5"/><rect AF x="6" y="9" width="12" height="6" rx="1"/>',
    "color": '<circle A cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 0 0 16z"/>',
    "line_style": '<path d="M3 7h18"/><path A d="M3 12h4M10 12h4M17 12h4"/><path d="M3 17h2M8 17h2M13 17h2M18 17h2"/>',
    "hatch": '<rect x="3" y="3" width="18" height="18" rx="2"/><path A d="M3 15 15 3M9 21 21 9M3 21 21 3"/>',
    "chest": '<rect x="3" y="8" width="18" height="12" rx="2"/><path d="M8 8V6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path A d="M3 13h18M11 12h2v3h-2z"/>',
    "list": '<path A d="M4 6h1M4 12h1M4 18h1"/><path d="M9 6h11M9 12h11M9 18h11"/>',
    # ---- edit / forms / sign ----
    "snapshot": '<path d="M3 8a2 2 0 0 1 2-2h2l2-2h6l2 2h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><circle A cx="12" cy="13" r="3.5"/>',
    "package": '<path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/><path A d="m7.5 5.2 9 4.6"/>',
    "select_text": '<path d="M9 4h6M9 20h6M12 4v16"/><rect AF x="3" y="9" width="18" height="6" rx="1" opacity=".35"/>',
    "edit_text": '<path d="M4 7V5h12v2M10 5v14M8 19h4"/><path A d="m14 17 5-5 2 2-5 5h-2z"/>',
    "add_image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle A cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
    "field_text": '<rect x="3" y="7" width="18" height="10" rx="2"/><path A d="M7 10v4"/>',
    "field_checkbox": '<rect x="4" y="4" width="16" height="16" rx="3"/><path A d="m8 12 3 3 5-6"/>',
    "field_combo": '<rect x="3" y="7" width="18" height="10" rx="2"/><path A d="m14 11 2 2 2-2"/><path d="M6 12h5"/>',
    "crop": '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path A d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    "fs_signature": '<path d="M3 17c3 0 4-8 7-8s1 8 4 8 3-4 5-4"/><path A d="M3 21h18"/>',
    "fs_initials": '<path d="M4 17V7l4 10V7M13 7v10M13 7h3a2.5 2.5 0 0 1 0 5h-3"/><path A d="M3 21h18"/>',
    "fs_text": '<path d="M5 7V5h14v2M12 5v14M9 19h6"/><path A d="M3 22h18"/>',
    "fs_check": '<path A d="m4 12 5 5L20 6"/>',
    "fs_date": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/><path A d="m9 15 2 2 4-4"/>',
    "form": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8"/><path A d="M8 16h4"/>',
    "flatten": '<path d="m12 3 9 5-9 5-9-5z"/><path A d="M3 18h18"/>',
    "ocr": '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path A d="M8 9h8M8 12h8M8 15h5"/>',
    "redact_search": '<circle cx="10" cy="10" r="6"/><path d="m20 20-5.5-5.5"/><rect AF x="7" y="8.5" width="6" height="3" rx=".5"/>',
    # ---- pages ----
    "rotate": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path A d="M21 3v5h-5"/>',
    "rotate_left": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path A d="M3 3v5h5"/>',
    "page_add": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path A d="M12 12v6M9 15h6"/>',
    "page_delete": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path A d="M9 15h6"/>',
    "duplicate": '<rect x="8" y="8" width="13" height="13" rx="2"/><path A d="M4 16a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h11a1 1 0 0 1 1 1"/>',
    "replace": '<rect x="3" y="3" width="8" height="10" rx="1"/><rect A x="13" y="11" width="8" height="10" rx="1"/><path d="M14 4h3a2 2 0 0 1 2 2v2M10 20H7a2 2 0 0 1-2-2v-2"/>',
    "split": '<rect x="3" y="4" width="7" height="16" rx="1"/><rect A x="14" y="4" width="7" height="16" rx="1"/>',
    "extract": '<rect x="3" y="3" width="12" height="16" rx="1.5"/><path A d="M13 15h8M18 12l3 3-3 3"/>',
    "header_footer": '<rect x="5" y="3" width="14" height="18" rx="2"/><path A d="M8 6h8M8 18h8"/>',
    "bookmark": '<path A d="M6 3h12v18l-6-4-6 4z"/>',
    "numbers": '<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>',
    "watermark": '<path A d="M12 3s7 7.6 7 12a7 7 0 0 1-14 0c0-4.4 7-12 7-12z"/>',
    # ---- takeoff ----
    "calibrate": '<path d="M3 8h18v8H3z"/><path A d="M7 8v3M11 8v4M15 8v3M19 8v4"/>',
    "measure_length": '<path d="M4 12h16"/><path A d="M4 8v8M20 8v8"/>',
    "measure_polylength": '<path A d="m3 17 6-8 5 5 7-9"/><path d="M3 21h18"/>',
    "measure_area": '<path AF d="M4 6h12l4 5-3 8H5z"/>',
    "measure_cutout": '<path d="M4 4h16v16H4z"/><path AF d="M9 9h6v6H9z"/>',
    "measure_wall": '<path d="M4 20V9l8-5 8 5v11"/><path A d="M4 14h16M9 20v-6M15 20v-6"/>',
    "measure_volume": '<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9z"/><path A d="m4 7.5 8 4.5 8-4.5M12 12v9"/>',
    "measure_angle": '<path d="M4 20h16M4 20 16 6"/><path A d="M10 20a6 6 0 0 0-1.6-4.1"/>',
    "measure_radius": '<circle cx="12" cy="12" r="9"/><path A d="M12 12h9"/><circle F cx="12" cy="12" r="1.2"/>',
    "measure_diameter": '<circle cx="12" cy="12" r="9"/><path A d="M3 12h18"/>',
    "auto_area": '<path d="M3 3h18v18H3zM12 3v9h9"/><path AF d="M3 12h9v9H3z"/><path d="m6 15 2 2"/>',
    "trace_length": '<path d="M3 6h8v6h10"/><path A d="M3 6h8v6h10"/><circle F cx="11" cy="9" r="1.6"/>',
    "trace_outline": '<path AF d="M4 4h10v6h6v10H4z"/><circle F cx="4" cy="4" r="1.6"/><circle F cx="14" cy="10" r="1.6"/>',
    "wall_roles": '<path d="M3 4h18v16H3z"/><path A d="M3 11h18M12 11v9"/><path d="M7 4v7"/>',
    "count_several": '<circle cx="7" cy="7" r="2.5"/><rect x="14.5" y="4.5" width="5" height="5" rx="0.5"/><path d="m7 14.5 2.8 5H4.2z"/><path A d="m14 17 2 2 4-4"/>',
    "viewport": '<rect x="3" y="3" width="18" height="18" rx="2"/><rect A x="11" y="11" width="8" height="8" rx="1"/>',
    "count": '<circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="7" r="2.5"/><circle cx="7" cy="17" r="2.5"/><circle AF cx="17" cy="17" r="2.5"/>',
    "symbol": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path A d="m14 17 2 2 4-4"/>',
    "count_label": '<path d="M4 6h10M4 10h7"/><path A d="m14 16 2 2 4-4"/><path d="M4 14h6M4 18h6"/>',
    "auto_rooms": '<path d="M3 3h18v18H3zM3 12h8M11 3v18M11 15h10"/><path A d="m14 7 1.5 1.5L18 6"/>',
    "scale": '<path d="m3 21 18-18M7 21l-4-4M21 7l-4-4"/><path A d="m8 12 2 2M12 8l2 2"/>',
    "auto_scale": '<path d="M3 21 21 3"/><path A d="M15 21h6v-6"/><path d="M12 4h-2M4 12v-2"/>',
    "quantities": '<path A d="M18 4H6l6 8-6 8h12"/>',
    "excel": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/><path A d="m13 11 4 4M17 11l-4 4"/>',
    "csv": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path A d="M8 13h8M8 17h8M12 13v4"/>',
    "dxf": '<path d="M3 21 12 3l9 18z"/><path A d="M7.5 13h9"/>',
    # ---- estimate ----
    "assembly": '<path d="M12 3 4 7.5v9L12 21l8-4.5v-9z"/><path A d="M12 12 4 7.5M12 12l8-4.5M12 12v9"/>',
    "crew": '<circle cx="9" cy="8" r="3.5"/><path d="M3 20a6 6 0 0 1 12 0"/><path A d="M16 4a3.5 3.5 0 0 1 0 7M21 20a6 6 0 0 0-4-5.6"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path A d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path A d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "bidtabs": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 9v11"/><path A d="M12 13h6M12 16h4"/>',
    "leveling": '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/><path A d="M2 14h20"/>',
    "scopesheet": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 8h18M9 8v13M15 8v13"/><path A d="M11 12h2M17 12h2M11 16h2M17 16h2"/>',
    "buildup": '<path d="M4 20h16"/><rect x="5" y="14" width="4" height="6"/><rect x="10" y="10" width="4" height="10"/><rect A x="15" y="5" width="4" height="15"/>',
    "dollar": '<path A d="M12 2v20"/><path d="M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "proposal": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path A d="M8 17c1.5 0 2-3 3.5-3s1 3 2.5 3 1.5-1.5 2-1.5"/>',
    "estimate": '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M8 6h8"/><path A d="M8 11h2M14 11h2M8 15h2M14 15h2M8 19h8"/>',
    "trend": '<path d="M3 17 9 11l4 4 8-8"/><path A d="M15 7h6v6"/>',
    # ---- review / project / billing ----
    "rules": '<path d="M9 5h11M9 12h11M9 19h11"/><path A d="m3 5 1.5 1.5L7 4M3 12l1.5 1.5L7 11M3 19l1.5 1.5L7 18"/>',
    "ai": '<path A d="M12 3l1.8 4.9L19 9.7l-5.2 1.8L12 16.4l-1.8-4.9L5 9.7l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "mic": '<rect A x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8"/>',
    "ai_takeoff": '<path d="M3 21h18M5 21V8l7-5 7 5v13"/><path A d="M12 9l.9 2.4 2.4.9-2.4.9L12 15.6l-.9-2.4-2.4-.9 2.4-.9z"/>',
    "rfi": '<circle cx="12" cy="12" r="9"/><path A d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17v.5"/>',
    "submittal": '<path d="M22 2 11 13"/><path A d="M22 2 15 22l-4-9-9-4z"/>',
    "register": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path A d="M7 13h4M7 17h4M14 13h3M14 17h3"/>',
    "transmittal": '<rect x="2" y="5" width="20" height="14" rx="2"/><path A d="m2 7 10 6 10-6"/>',
    "addenda": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path A d="M9 13h6M12 10v6"/>',
    "punch": '<path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle A cx="12" cy="9.5" r="2.5"/>',
    "inspect": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 3h6v3H9z"/><path A d="m9 13 2 2 4-4"/>',
    "ada": '<circle A cx="11" cy="4" r="2"/><path d="M11 7v6h5l2 5"/><path d="M8.5 10.5a5.5 5.5 0 1 0 7 7"/>',
    "code": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path A d="M9 11h6M9 14h4"/>',
    "contract": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8"/><path A d="M8 17h3"/>',
    "sov": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18"/><path A d="M15 4v16"/>',
    "change_order": '<path d="M4 7h13l-3-3M20 17H7l3 3"/><path A d="M17 7l3 3M7 17l-3-3"/>',
    "pay_app": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/><path A d="M6 15h4"/>',
    "waiver": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path A d="m9 15 2 2 4-4"/>',
    "batch": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path A d="m14 17.5 3 2.5 4-5"/>',
    "macro": '<circle cx="12" cy="12" r="9"/><path A d="m10 8 6 4-6 4z"/>',
    "collab": '<circle cx="8" cy="8" r="3"/><circle A cx="17" cy="10" r="2.5"/><path d="M2 20a6 6 0 0 1 12 0"/><path A d="M14 20a4.5 4.5 0 0 1 8 0"/>',
    "relay": '<rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path A d="M7 7h.5M7 17h.5"/>',
    "slipsheet": '<rect x="3" y="3" width="12" height="15" rx="1.5"/><rect A x="9" y="6" width="12" height="15" rx="1.5"/><path A d="m13 13 2 2 3-3"/>',
    "sets": '<rect x="3" y="7" width="14" height="14" rx="1.5"/><path d="M7 3h12a2 2 0 0 1 2 2v12"/><path A d="M7 12h6M7 16h4"/>',
    "carry": '<rect x="2" y="5" width="9" height="14" rx="1"/><rect A x="13" y="5" width="9" height="14" rx="1"/><path d="M6 12h11M14 9l3 3-3 3"/>',
    "audit": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/><path A d="M11 8v3l2 1.5"/>',
    "speed": '<path d="M12 14l4-6"/><path A d="M3.3 17a9 9 0 1 1 17.4 0"/>',
    "accessibility": '<circle A cx="12" cy="4.5" r="1.8"/><path d="M5 8h14M12 8v6M9 21l3-7 3 7"/>',
    "home": '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path A d="M10 20v-6h4v6"/>',
    "package": '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path A d="M3 8l9 5 9-5M12 13v8"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle A cx="12" cy="12" r="3"/>',
    "checklist": '<rect x="4" y="3" width="16" height="18" rx="2"/><path A d="m8 9 1.5 1.5L12 8M8 15l1.5 1.5L12 14"/><path d="M14 9h3M14 15h3"/>',
    "brick": '<rect x="3" y="5" width="18" height="14" rx="1"/><path d="M3 9.7h18M3 14.3h18M9 5v4.7M15 5v4.7M6 9.7v4.6M12 9.7v4.6M18 9.7v4.6M9 14.3V19M15 14.3V19"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/><path A d="M8 14h3v3H8z"/>',
    "meeting": '<circle cx="8" cy="8" r="3"/><circle cx="16" cy="8" r="3"/><path d="M2 20a6 6 0 0 1 12 0"/><path A d="M14 14a6 6 0 0 1 8 6"/>',
    "flag": '<path d="M5 21V4"/><path A d="M5 4h12l-2 4 2 4H5"/>',
    "truck": '<path d="M2 6h12v10H2z"/><path d="M14 10h4l3 3v3h-7"/><circle A cx="6" cy="18" r="2"/><circle A cx="17" cy="18" r="2"/>',
    "people": '<circle cx="9" cy="8" r="3.5"/><path d="M2 20a7 7 0 0 1 14 0"/><path A d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 4 6"/>',
    "mail": '<rect x="2" y="5" width="20" height="14" rx="2"/><path A d="m2 7 10 6 10-6"/>',
    "sync": '<path d="M20 11A8 8 0 0 0 6 6.3L4 8"/><path d="M4 4v4h4"/><path A d="M4 13a8 8 0 0 0 14 4.7l2-1.7M20 20v-4h-4"/>',
    "photo": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle A cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
    "attach": '<path A d="M21 11.5 12.5 20a5 5 0 0 1-7-7L14 4.5a3.3 3.3 0 0 1 4.7 4.7L10.2 17.7a1.7 1.7 0 0 1-2.4-2.4L15.5 7.6"/>',
    "cloud": '<path d="M7 18a5 5 0 0 1-.6-10A6.5 6.5 0 0 1 19 9.5 4.3 4.3 0 0 1 18 18z"/><path A d="m9 13 2.5 2.5L15 12"/>',
    "inbox": '<path d="M3 13h5l2 3h4l2-3h5"/><path d="M5.5 5h13L21 13v6H3v-6z"/>',
    "budget": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path A d="M12 12v6M10 13.5h3a1.2 1.2 0 0 1 0 2.4h-2a1.2 1.2 0 0 0 0 2.4h3"/>',
    "commitment": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path A d="M8 17c1-1.5 2-2 3-1s2 .5 3-1"/>',
    "forecast": '<path d="M3 20h18"/><path d="M4 16l5-5 4 3 7-7"/><path A d="M15 7h5v5"/>',
    "event": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "gavel": '<path d="m14 13-7.5 7.5a2 2 0 0 1-3-3L11 10"/><path A d="m16 16 6-6M8 8l6-6M9 7l8 8"/>',
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.5M10 10h.5M14 10h.5M18 10h.5"/><path A d="M7 14h10"/>',
}

_cache = {}


def _svg(name, ink, accent):
    body = _P.get(name) or _P["info"]
    body = (body.replace("<path AF", f'<path fill="{accent}" fill-opacity="0.22" stroke="{accent}"')
                .replace("<rect AF", f'<rect fill="{accent}" fill-opacity="0.22" stroke="{accent}"')
                .replace("<circle AF", f'<circle fill="{accent}" fill-opacity="0.22" stroke="{accent}"')
                .replace("<path A ", f'<path stroke="{accent}" ')
                .replace("<rect A ", f'<rect stroke="{accent}" ')
                .replace("<circle A ", f'<circle stroke="{accent}" ')
                .replace("<ellipse A ", f'<ellipse stroke="{accent}" ')
                .replace("<circle F ", f'<circle fill="{ink}" stroke="none" '))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="{ink}" stroke-width="1.7" '
            'stroke-linecap="round" stroke-linejoin="round">' + body +
            '</svg>').encode()


def _colors():
    try:
        from . import theme
        t = theme.tokens()
        return t["text"], t["accent"], t["faint"]
    except Exception:
        return "#2d2d32", "#2563eb", "#9aa0ab"


_renderers = {}


def _renderer(name, ink, accent):
    key = (name, ink, accent)
    r = _renderers.get(key)
    if r is None:
        r = _renderers[key] = QSvgRenderer(QByteArray(_svg(name, ink,
                                                           accent)))
    return r


class _Engine(QIconEngine):
    """Draws the icon at any size, in the theme colours of the moment."""

    def __init__(self, name):
        super().__init__()
        self.name = name

    def _draw(self, painter, rect, mode):
        ink, accent, faint = _colors()
        if mode == QIcon.Disabled:
            ink = accent = faint
        r = _renderer(self.name, ink, accent)
        r.render(painter, QRectF(rect))

    def paint(self, painter, rect, mode, state):
        painter.drawPixmap(rect, self.pixmap(rect.size(), mode, state))

    def pixmap(self, size, mode, state):
        key = (self.name, size.width(), size.height(), int(mode.value)
               if hasattr(mode, "value") else int(mode), _colors())
        pm = _cache.get(key)
        if pm is None:
            pm = QPixmap(size)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            self._draw(p, pm.rect(), mode)
            p.end()
            _cache[key] = pm
        return pm

    def actualSize(self, size, mode, state):
        return size

    def clone(self):
        return _Engine(self.name)


def icon(name):
    return QIcon(_Engine(name))


def names():
    return sorted(_P)


def has(name):
    return name in _P
