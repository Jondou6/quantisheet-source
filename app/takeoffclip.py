"""Copy and paste takeoff between sheets (Nov 4, takeoff list #2).

Ctrl+C with markups selected (and no text selected) copies them; Ctrl+V
pastes them on the sheet you're on - in place (same spot), or with
Paste Here at the right-click point. Measurements are worked out again
from the scale of the sheet they land on, so a length copied from a
1/8" sheet to a 1/4" sheet comes out right. Counts, shapes and their
names, colours and Tool Chest settings come along.

The clipboard also gets a plain-text line ("3 QuantiSheet markups"),
and a format of our own so Ctrl+V knows the markups are newer than any
picture copied before them.
"""
import json
import logging

import fitz

from . import annotate, takeoff

log = logging.getLogger(__name__)

MIME = "application/x-quantisheet-markups"
_CLIP = {"items": [], "page": None, "size": None}


def _items_for(v):
    """(kind, payload, meta) for each selected markup."""
    from . import measure_tools
    refs = list(v.selected_refs()) if v.multi else \
        ([v.selected["ref"]] if v.selected else [])
    keep_sel, keep_multi = v.selected, v.multi
    out = []
    try:
        for ref in refs:
            found = annotate.find_annots(v.pg, ref)
            if not found:
                continue
            v.multi = None
            v.select(found[0])
            m = measure_tools.selected_measure(v)
            got = measure_tools.copy_payloads(v, 0.0, 0.0, 1)
            if not got:
                continue
            kind, payload = got[0]
            meta = {}
            if m and m["type"] in ("length", "area", "volume"):
                meta = {"type": "length" if m["run"] else m["type"],
                        "group": m["group"], "extra": dict(m["extra"] or {})}
                if m["type"] == "volume":
                    sc = v.scale(at=[fitz.Point(q) for q in
                                     found[0].vertices or []])
                    area = takeoff.polygon_area([fitz.Point(q) for q in
                                                 found[0].vertices]) / \
                        sc["ppu"] ** 2 if sc else 0
                    meta["depth"] = (m["value"] / area) if area else None
            out.append((kind, payload, meta))
    finally:
        v.multi = keep_multi
        v.selected = keep_sel
        v.update()
    return out


def copy(v, clipboard=None):
    """Copy the selected markups. Returns how many."""
    items = _items_for(v)
    if not items:
        return 0
    _CLIP.update(items=items, page=v.page, size=tuple(v.pg.rect))
    try:
        from PySide6.QtCore import QMimeData
        from PySide6.QtWidgets import QApplication
        md = QMimeData()
        md.setText(f"{len(items)} QuantiSheet markup(s)")
        md.setData(MIME, json.dumps({"n": len(items)}).encode("utf-8"))
        (clipboard or QApplication.clipboard()).setMimeData(md)
    except Exception:                                     # noqa: BLE001
        log.debug("markup clipboard", exc_info=True)
    return len(items)


def ready(clipboard=None):
    """True when Ctrl+V should paste markups (they were copied last)."""
    if not _CLIP["items"]:
        return False
    try:
        from PySide6.QtWidgets import QApplication
        md = (clipboard or QApplication.clipboard()).mimeData()
        return md is not None and md.hasFormat(MIME)
    except Exception:                                     # noqa: BLE001
        return True


def _bbox(items):
    r = None
    for kind, p, _m in items:
        pts = p.get("pts") or ([p["pt"]] if p.get("pt") else []) or \
            ([p["rect"][:2], p["rect"][2:]] if p.get("rect") else [])
        for q in pts:
            pr = fitz.Rect(q[0], q[1], q[0], q[1])
            r = pr if r is None else r | pr
    return r


def _moved(p, dx, dy):
    p = json.loads(json.dumps(p))
    if p.get("pts"):
        p["pts"] = [[q[0] + dx, q[1] + dy] for q in p["pts"]]
    if p.get("pt"):
        p["pt"] = [p["pt"][0] + dx, p["pt"][1] + dy]
    if p.get("rect"):
        r = p["rect"]
        p["rect"] = [r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy]
    return p


def paste(v, at=None):
    """Paste the copied markups on v's page: in place, or centred on
    `at` (page point). Measurements are worked out from this sheet's
    scale. Returns how many were added."""
    items = _CLIP["items"]
    if not items:
        return 0
    dx = dy = 0.0
    if at is not None:
        bb = _bbox(items)
        if bb is not None:
            c = fitz.Point((bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2)
            dx, dy = at.x - c.x, at.y - c.y
    marks, skipped = [], 0
    for kind, p, meta in items:
        p = _moved(p, dx, dy)
        if meta and p.get("pts"):
            pts = [fitz.Point(q) for q in p["pts"]]
            sc = v.scale(at=pts)
            if not sc:
                skipped += 1
                continue
            keep = dict(v.style)
            try:
                v.style["subject"] = meta["group"]
                for k in ("rise", "height", "openings", "unit"):
                    v.style.pop(k, None)
                np_ = v._measure_payload(meta["type"], pts, sc,
                                         dict(meta["extra"]),
                                         depth=meta.get("depth"))
            finally:
                v.style = keep
            if np_ is None:
                skipped += 1
                continue
            kind = np_.pop("_kind")
            for k in ("color", "fill", "width"):
                if k in p:
                    np_[k] = p[k]
            p = np_
        marks.append((v.page, kind, p))
    n = v.apply_marks(marks) if marks else 0
    if skipped:
        v.status.emit(f"Pasted {n}; {skipped} measurement(s) need this "
                      "sheet's scale first (Set Scale)")
    elif n:
        v.status.emit(f"Pasted {n} markup(s)")
    return n
