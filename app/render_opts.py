"""Render settings that only belong on screen.

"Enhance thin lines" (a minimum line width) makes hairlines readable when
a sheet is zoomed out - but the automatic tools read the drawing from
renders too, and fattened hairlines (furniture, hatching, door swings)
would look like walls to them. So the setting is switched on only while
the viewer draws (`with screen():`) and is off for every other render:
auto takeoff, symbol counts, overlays, OCR, exports, printing."""
import logging
from contextlib import contextmanager

import fitz

STATE = {"thin_lines": True}


def set_thin_lines(on):
    STATE["thin_lines"] = bool(on)


def _set(w):
    try:
        fitz.TOOLS.set_graphics_min_line_width(w)
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)


@contextmanager
def screen():
    _set(1.0 if STATE["thin_lines"] else 0.0)
    try:
        yield
    finally:
        _set(0.0)


_set(0.0)
