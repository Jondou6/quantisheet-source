"""The water district's own backflow form, filled in as an overlay
(QuantiSheet 1.2, #5; Jon, Nov 5: use the GSWSA "Backflow Device Test
Report Form" exactly as it is).

- The form itself is the user's own copy, read at run time from wherever
  it is kept. QuantiSheet never ships it, copies it into its install or
  changes the original: each fill writes a new PDF with the entries laid
  on top of the scanned page.
- Where each entry goes is a template (a data file in the data folder:
  service_district_form.json), made once with "Map the form…": pick an
  entry, click its place on the page. A revised form is re-mapped the
  same way - no code changes.
- A calibration print draws every mapped box and its name on the form,
  to check the alignment on paper. Print at actual size (no "fit").
- Text that doesn't fit its box is shrunk (down to 6 pt), then wrapped,
  and if it still doesn't fit the box says "see attached" and the full
  text goes on an extra page.
- A form page that is rotated, or a different size than the one mapped,
  is handled: positions are kept as they look on screen and scaled to
  the page.
"""
import json
import os

from . import files
from ..dmoney import c2 as _c2

FILE = "service_district_form.json"
MAP_SUFFIX = ".qsmap.json"
MIN_PT = 6.0

# key, label, what it is filled from (a report key, or (report key, value)
# for an X mark), default box size (w, h) in points
FIELDS = [
    ("date", "Test date", "test_date", (90, 14)),
    ("acct_name", "Account name", "acct_name", (220, 14)),
    ("acct_address", "Address", "acct_address", (260, 14)),
    ("acct_no", "Account no.", "acct_no", (110, 14)),
    ("meter_no", "Meter no.", "meter_no", (110, 14)),
    ("dev_name", "Device name / make", "dev_name", (150, 14)),
    ("dev_model", "Model", "dev_model", (100, 14)),
    ("dev_serial", "Serial", "dev_serial", (110, 14)),
    ("dev_size", "Size", "dev_size", (50, 14)),
    ("app_domestic", "Application: Domestic (X)",
     ("dev_application", "Domestic"), (12, 12)),
    ("app_fire", "Application: Fire Line (X)",
     ("dev_application", "Fire Line"), (12, 12)),
    ("app_irrigation", "Application: Irrigation (X)",
     ("dev_application", "Irrigation"), (12, 12)),
    ("app_other", "Application: Other (X)",
     ("dev_application", "Other"), (12, 12)),
    ("dev_location", "Location", "dev_location", (220, 14)),
]
_PTS = (("c1", "Check 1"), ("c2", "Check 2"), ("rv", "Air inlet / relief"),
        ("so1", "Gate valve 1"), ("so2", "Gate valve 2"))
for _pid, _lab in _PTS:
    for _ph, _plab in (("before", "before"), ("after", "after")):
        if _pid != "rv":
            FIELDS += [
                (f"{_pid}_{_ph}_leaked", f"{_lab} {_plab}: leaked (X)",
                 (f"{_pid}_{_ph}_leaked", True), (12, 12)),
                (f"{_pid}_{_ph}_tight", f"{_lab} {_plab}: tight / closed "
                 "tight (X)", (f"{_pid}_{_ph}_tight", True), (12, 12))]
        if _pid not in ("so1", "so2"):
            FIELDS += [(f"{_pid}_{_ph}_psi", f"{_lab} {_plab}: psid",
                        f"{_pid}_{_ph}_psi", (50, 14))]
for _pid, _lab in _PTS:
    FIELDS += [(f"rep_{_pid}", f"{_lab}: repairs / new materials",
                f"{_pid}_repair_note", (98, 52))]
FIELDS += [
    ("repairs", "Repairs and materials (all)", "repair_materials", (380, 40)),
    ("comments", "Comments (and repairs when they have no box)",
     "comments", (505, 52)),
    ("tester", "Tester", "tester", (180, 14)),
    ("signature", "Tester signature", "signature", (180, 14)),
    ("cert_no", "Certification no.", "cert_no", (110, 14)),
    ("company", "Company", "cert_company", (200, 14)),
    ("phone", "Phone", "cert_phone", (110, 14)),
    ("cat_general", "Tester category: General (X)", ("category", "General"),
     (12, 12)),
    ("cat_limited", "Tester category: Limited (X)", ("category", "Limited"),
     (12, 12)),
    ("cat_inspector", "Tester category: Inspector (X)",
     ("category", "Inspector"), (12, 12)),
    ("method_flow", "Test method: Direction of flow (X)",
     ("method", "Direction of flow"), (12, 12)),
    ("method_diff", "Test method: Differential (X)",
     ("method", "Differential"), (12, 12)),
    ("kit", "Test kit", "kit", (130, 14)),
    ("so1_gate", "#1 shutoff: Gate (ring)", ("so1_type", "Gate"), (12, 12)),
    ("so1_ball", "#1 shutoff: Ball (ring)", ("so1_type", "Ball"), (12, 12)),
    ("so2_gate", "#2 shutoff: Gate (ring)", ("so2_type", "Gate"), (12, 12)),
    ("so2_ball", "#2 shutoff: Ball (ring)", ("so2_type", "Ball"), (12, 12)),
    ("kit_vertical", "Test kit: Vertical tube (X)", ("kit", "Vertical tube"),
     (12, 12)),
    ("kit_diff", "Test kit: Differential (X)", ("kit", "Differential gauge"),
     (12, 12)),
]
# "circle one" entries: a ring is drawn round the word instead of an X
CIRCLE = {"app_domestic", "app_fire", "app_irrigation", "app_other",
          "cat_general", "cat_limited", "cat_inspector", "method_flow",
          "method_diff", "kit_vertical", "kit_diff", "so1_gate", "so1_ball",
          "so2_gate", "so2_ball"}
KEYS = [f[0] for f in FIELDS]
LABELS = {f[0]: f[1] for f in FIELDS}
SOURCES = {f[0]: f[2] for f in FIELDS}
SIZES = {f[0]: f[3] for f in FIELDS}
SIZES.update({k: (50, 18) for k in CIRCLE})          # a ring round a word


class FormError(ValueError):
    pass


def template_path():
    return files.path_for(FILE)


def load_template():
    p = template_path()
    if not os.path.isfile(p):
        return {"form_path": "", "page": 0, "page_size": None,
                "fields": {}, "nudge": [0, 0]}
    with open(p, encoding="utf-8") as f:
        t = json.load(f)
    t.setdefault("fields", {})
    t.setdefault("nudge", [0, 0])
    return t


def save_template(t):
    return files.write(template_path(), t)


def _open_form(t, path=None):
    import fitz
    path = path or t.get("form_path")
    if not path or not os.path.isfile(path):
        raise FormError("Pick your copy of the district's form first "
                        "(Map the form…). It isn't stored in QuantiSheet.")
    doc = fitz.open(path)
    if doc.page_count <= int(t.get("page") or 0):
        raise FormError("The form has fewer pages than the template.")
    return doc


def set_form(t, path, page=0):
    """Start (or restart) a template on the user's own form file."""
    import fitz
    if not os.path.isfile(path):
        raise FormError("That file isn't there.")
    with fitz.open(path) as d:
        r = d[page].rect                    # as it looks (rotation applied)
    t.update(form_path=os.path.abspath(path), page=page,
             page_size=[_c2(r.width), _c2(r.height)])
    side = path + MAP_SUFFIX
    if not t.get("fields") and os.path.isfile(side):
        with open(side, encoding="utf-8") as f:
            saved = json.load(f)
        t["fields"] = saved.get("fields", {})
        t["nudge"] = saved.get("nudge", [0, 0])
        if saved.get("page_size"):
            t["page_size"] = saved["page_size"]
    return t


def save_beside(t):
    """Keep a copy of the mapping next to the user's form (so a new data
    folder or another PC picks it up with the form)."""
    p = t["form_path"] + MAP_SUFFIX
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"fields": t["fields"], "nudge": t.get("nudge", [0, 0]),
                   "page_size": t.get("page_size")}, f, indent=1)
    return p


def place(t, key, x, y, w=None, h=None):
    """A field's box, top-left at (x, y) in points as the page looks."""
    if key not in LABELS:
        raise FormError(f"Unknown entry {key!r}.")
    dw, dh = SIZES[key]
    t["fields"][key] = {"x": _c2(float(x)), "y": _c2(float(y)),
                        "w": _c2(float(w or dw)),
                        "h": _c2(float(h or dh))}
    return t["fields"][key]


def missing(t):
    return [LABELS[k] for k in KEYS if k not in t.get("fields", {})]


def _value(report, key, t=None):
    if key == "comments" and t is not None and "repairs" not in \
            t.get("fields", {}) and (report.get("repair_materials") or
                                     "").strip():
        return ("Repairs / materials: " + " ".join(
            report["repair_materials"].split()) + ". " +
            " ".join(str(report.get("comments") or "").split())).strip()
    src = SOURCES[key]
    if isinstance(src, tuple):
        rk, want = src
        v = report.get(rk)
        hit = (bool(v) and str(v).lower() not in ("0", "false", "off")) \
            if want is True else (str(v or "") == want)
        return "X" if hit else ""
    return " ".join(str(report.get(src) or "").split()) \
        if key != "repairs" else str(report.get(src) or "").strip()


def _to_page(page, t, box):
    """Screen-view box (as mapped) -> the page's own coordinates, scaled
    when this page isn't the size that was mapped."""
    import fitz
    view = page.rect
    sx = sy = 1.0
    if t.get("page_size"):
        sx = view.width / t["page_size"][0]
        sy = view.height / t["page_size"][1]
    nx, ny = t.get("nudge") or (0, 0)
    r = fitz.Rect(box["x"] * sx + nx, box["y"] * sy + ny,
                  (box["x"] + box["w"]) * sx + nx,
                  (box["y"] + box["h"]) * sy + ny)
    return r * page.derotation_matrix, (sx, sy)


def _put(page, rect, text, size=9.0):
    """Shrink, then wrap (insert_textbox wraps; nothing is written when
    it doesn't fit). Returns (fits, size used).

    A box only one line tall is never wrapped: a second line drawn in it
    sat on the form's printed rule (Chief's estimator test, Nov 7). It is
    shrunk to fit on one line, or reported as not fitting."""
    import fitz
    s, floor = size, min(MIN_PT, size)
    one_line = (rect.height if not page.rotation % 180 else rect.width) \
        < 2 * max(size, 9.0) * 1.1           # under two 9 pt lines
    if one_line and "\n" not in text:
        across = rect.width if not page.rotation % 180 else rect.height
        while s >= floor:
            if fitz.get_text_length(text, "helv", s) <= across - 2:
                rc = page.insert_textbox(rect, text, fontsize=s,
                                         fontname="helv",
                                         rotate=page.rotation,
                                         color=(0, 0, 0.55))
                if rc >= 0:
                    return True, s
            s -= 0.5
        return False, floor
    while s >= floor:
        rc = page.insert_textbox(rect, text, fontsize=s, fontname="helv",
                                 rotate=page.rotation, color=(0, 0, 0.55))
        if rc >= 0:
            return True, s
        s -= 0.5
    return False, floor


def fill(report, out_path, t=None, form_path=None):
    """The district form with this report laid on it, as a new PDF.
    Returns {"file", "overflow": [labels], "not_mapped": [labels],
    "scaled": bool}."""
    import fitz
    t = t or load_template()
    if not t.get("fields"):
        raise FormError("The form isn't mapped yet - use Map the form…")
    if os.path.abspath(out_path) == os.path.abspath(form_path or
                                                     t.get("form_path") or
                                                     ""):
        raise FormError("Save the filled form as a new file - the blank "
                        "form is never written over.")
    doc = _open_form(t, form_path)
    page = doc[int(t.get("page") or 0)]
    overflow, scaled = [], False
    for key in KEYS:
        box = t["fields"].get(key)
        if not box:
            continue
        text = _value(report, key, t)
        if not text:
            continue
        rect, (sx, sy) = _to_page(page, t, box)
        scaled = scaled or abs(sx - 1) > 0.01 or abs(sy - 1) > 0.01
        if key in CIRCLE and box.get("style", "circle") == "circle":
            page.draw_oval(rect, color=(0, 0, 0.55), width=1.2)
            continue
        ok, _s = _put(page, rect, text, 10.0 if text == "X" else 9.0)
        if not ok:
            _put(page, rect, "see attached", MIN_PT + 1)
            overflow.append((LABELS[key], text))
    if overflow:
        extra = doc.new_page(width=612, height=792)
        y = 60
        extra.insert_text((54, y), "Continued from the test report form",
                          fontsize=12, fontname="hebo")
        for label, text in overflow:
            y += 24
            rc = extra.insert_textbox(fitz.Rect(54, y, 558, y + 300),
                                      f"{label}: {text}", fontsize=9,
                                      fontname="helv")
            y += 300 + rc if rc < 0 else 300 - rc
            y = min(y, 740)
    del page                    # before the document closes (PyMuPDF)
    if overflow:
        del extra
    doc.save(out_path, garbage=3, deflate=True)
    doc.close()
    return {"file": out_path, "overflow": [lab for lab, _t in overflow],
            "not_mapped": missing(t), "scaled": scaled}


def calibration(out_path, t=None, form_path=None):
    """Every mapped box outlined, with its name, on a copy of the form -
    print at actual size and hold it to the light against a blank."""
    t = t or load_template()
    if os.path.abspath(out_path) == os.path.abspath(form_path or
                                                     t.get("form_path") or
                                                     ""):
        raise FormError("Save the calibration print as a new file.")
    doc = _open_form(t, form_path)
    page = doc[int(t.get("page") or 0)]
    for key, box in t.get("fields", {}).items():
        rect, _s = _to_page(page, t, box)
        page.draw_rect(rect, color=(0.9, 0.1, 0.1), width=0.6)
        _put(page, rect, LABELS[key], 5.5)
    page.insert_text(page.rect.tl * page.derotation_matrix + (20, 20),
                     "CALIBRATION - print at actual size (no fit / shrink)",
                     fontsize=8, color=(0.9, 0.1, 0.1),
                     rotate=page.rotation)
    del page
    doc.save(out_path)
    doc.close()
    return out_path


def page_image(t, zoom=1.5, form_path=None):
    """(png bytes, zoom) of the form page as it looks, for mapping."""
    doc = _open_form(t, form_path)
    import fitz
    try:
        pix = doc[int(t.get("page") or 0)].get_pixmap(
            matrix=fitz.Matrix(zoom, zoom))
        png = pix.tobytes("png")
        del pix
    finally:
        doc.close()
    return png, zoom
