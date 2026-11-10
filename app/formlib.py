"""Form Library: your blank forms (AIA agreements and G-forms, bid
invitations, accident reports...) kept in one place, opened as a fresh
copy so the blank is never overwritten, and filled from the job.

The forms live in your own folder (~/.quantisheet/forms, one sub-folder per
category) with an index (forms.json). They are your licensed copies and
are not part of the QuantiSheet installer. Word and Excel forms are
converted to PDF when added (the original is kept next to it).
"""
import datetime as _dt
import json
import logging
import os
import re
import shutil
import uuid

import fitz

from . import settings

log = logging.getLogger(__name__)

INDEX = "forms.json"
OFFICE = (".doc", ".docx", ".rtf", ".odt", ".xls", ".xlsx", ".xlsm",
          ".ods")


def folder():
    path = os.path.join(settings.DIR, "forms")
    os.makedirs(path, exist_ok=True)
    return path


def _index_path():
    return os.path.join(folder(), INDEX)


def _load():
    try:
        with open(_index_path(), encoding="utf-8") as f:
            data = json.load(f)
        return [e for e in data if isinstance(e, dict)]
    except (OSError, ValueError):
        return []


def _save(entries):
    tmp = _index_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=1)
    os.replace(tmp, _index_path())


def _safe(name):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")
    return s[:120] or "Form"


def inspect(path):
    """{pages, fields, filled: [(field, value)]} of a PDF."""
    out = {"pages": 0, "fields": 0, "filled": []}
    with fitz.open(path) as d:
        out["pages"] = d.page_count
        for pg in d:
            for w in pg.widgets() or []:
                out["fields"] += 1
                v = w.field_value
                if v not in (None, "", "Off", False) and \
                        not str(w.field_name).startswith("DOD_"):
                    out["filled"].append((w.field_name, str(v)[:60]))
    return out


def entries():
    """Every form in the library, sorted by category and name. PDFs
    dropped into the folder by hand are picked up too."""
    items = _load()
    known = {os.path.normcase(e["file"]) for e in items}
    root = folder()
    changed = False
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            if not f.lower().endswith(".pdf"):
                continue
            rel = os.path.relpath(os.path.join(dp, f), root)
            if os.path.normcase(rel) in known:
                continue
            cat = os.path.dirname(rel) or "General"
            try:
                info = inspect(os.path.join(root, rel))
            except Exception:
                continue
            items.append({"id": uuid.uuid4().hex[:12],
                          "name": os.path.splitext(f)[0], "category": cat,
                          "file": rel, "pages": info["pages"],
                          "fields": info["fields"],
                          "filled": len(info["filled"]), "source": "",
                          "added": _dt.date.today().isoformat(),
                          "notes": ""})
            changed = True
    keep = [e for e in items
            if os.path.exists(os.path.join(root, e["file"]))]
    if changed or len(keep) != len(items):
        _save(keep)
    return sorted(keep, key=lambda e: (e["category"].lower(),
                                       e["name"].lower()))


def categories():
    return sorted({e["category"] for e in entries()}, key=str.lower)


def path_of(entry):
    return os.path.join(folder(), entry["file"])


def add(path, category="General", name=None, notes=""):
    """Copy a form into the library (Word/Excel converted to PDF).
    Returns its entry."""
    ext = os.path.splitext(path)[1].lower()
    name = name or os.path.splitext(os.path.basename(path))[0]
    cat = _safe(category or "General")
    dest_dir = os.path.join(folder(), cat)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, _safe(name) + ".pdf")
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(dest_dir, f"{_safe(name)} ({n}).pdf")
        n += 1
    source = ""
    if ext == ".pdf":
        shutil.copyfile(path, dest)
    elif ext in OFFICE:
        from . import acrobat2
        doc = acrobat2.create_pdf(path)
        try:                       # closed even when the save fails (L6)
            doc.save(dest, garbage=3, deflate=True)
        finally:
            doc.close()
        keep = os.path.join(dest_dir, "originals")
        os.makedirs(keep, exist_ok=True)
        source = os.path.join(keep, os.path.basename(path))
        shutil.copyfile(path, source)
        source = os.path.relpath(source, folder())
    else:
        raise ValueError(f"Forms must be PDF, Word or Excel files "
                         f"({os.path.basename(path)}).")
    info = inspect(dest)
    entry = {"id": uuid.uuid4().hex[:12], "name": name, "category": cat,
             "file": os.path.relpath(dest, folder()),
             "pages": info["pages"], "fields": info["fields"],
             "filled": len(info["filled"]), "source": source,
             "added": _dt.date.today().isoformat(), "notes": notes}
    items = [e for e in _load() if e["file"] != entry["file"]]
    items.append(entry)
    _save(items)
    return entry


def update(entry_id, **fields):
    items = _load()
    for e in items:
        if e["id"] == entry_id:
            if "category" in fields and fields["category"] != e["category"]:
                cat = _safe(fields["category"])
                new_dir = os.path.join(folder(), cat)
                os.makedirs(new_dir, exist_ok=True)
                new = os.path.join(new_dir, os.path.basename(e["file"]))
                shutil.move(os.path.join(folder(), e["file"]), new)
                e["file"] = os.path.relpath(new, folder())
                e["category"] = cat
            for k in ("name", "notes"):
                if k in fields:
                    e[k] = str(fields[k])
            _save(items)
            return e
    raise KeyError(entry_id)


def remove(entry_id):
    items = _load()
    keep = []
    for e in items:
        if e["id"] == entry_id:
            try:
                os.remove(os.path.join(folder(), e["file"]))
            except OSError:
                pass
        else:
            keep.append(e)
    _save(keep)


def open_copy(entry, clear=False):
    """A new in-memory document from the form (the library file is never
    touched). clear=True empties every filled-in field."""
    with open(path_of(entry), "rb") as f:
        doc = fitz.open("pdf", f.read())
    if clear:
        clear_fields(doc)
    return doc


def clear_fields(doc):
    """Empty every filled-in field (text to blank, boxes unticked). The
    value is removed in the PDF itself (and from a parent field that holds
    it), then the field's look is redrawn."""
    n = 0
    for pg in doc:
        hits = []
        for w in pg.widgets() or []:
            if str(w.field_name).startswith("DOD_"):
                continue
            if w.field_value in (None, "", "Off", False):
                continue
            box = w.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX,
                                   fitz.PDF_WIDGET_TYPE_RADIOBUTTON)
            targets = [w.xref]
            t, v = doc.xref_get_key(w.xref, "Parent")
            if t == "xref":
                targets.append(int(v.split()[0]))
            for x in targets:
                if doc.xref_get_key(x, "V")[0] != "null" or x == w.xref:
                    doc.xref_set_key(x, "V", "/Off" if box else "()")
            if box:
                doc.xref_set_key(w.xref, "AS", "/Off")
            hits.append(w.xref)
            n += 1
        # redraw the cleared fields from their new (empty) values
        for w in pg.widgets() or []:
            if w.xref in hits:
                try:
                    w.update()
                except Exception:
                    logging.getLogger(__name__).debug("ignored error", exc_info=True)
    return n


# ---- fill from the job ------------------------------------------------------

def job_values(job_doc=None):
    """What we know about the job and your company, by meaning."""
    vals = {"date": _dt.date.today().strftime("%m/%d/%Y")}
    try:
        from . import proposal
        c = proposal.company()
        lines = [x.strip() for x in c.get("address", "").splitlines()
                 if x.strip()]
        vals.update({"contractor": c.get("name", ""),
                     "contractor_address": lines[0] if lines else "",
                     "contractor_city": lines[1] if len(lines) > 1 else "",
                     "contractor_phone": c.get("phone", ""),
                     "contractor_email": c.get("email", ""),
                     "license": c.get("license", "")})
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    if job_doc is not None:
        try:
            from . import money
            info = money.read(job_doc)["info"]
            vals.update({k: v for k, v in {
                "project": info.get("project"),
                "project_address": info.get("project_address"),
                "owner": info.get("owner"),
                "architect": info.get("architect"),
                "contract_date": info.get("contract_date"),
                "project_number": info.get("contract_no"),
                "contract_for": info.get("contract_for"),
            }.items() if v})
            if info.get("contractor"):
                vals["contractor"] = info["contractor"]
        except Exception:
            log.warning("no billing info for form fill", exc_info=True)
    return {k: v for k, v in vals.items() if v}


# field-name patterns -> meaning (checked in order; whole name, no case)
_FIELD_MAP = [
    (r"^project ?name$|^project$|^projectname$", "project"),
    (r"^project ?(location|address)$|^projectlocation$|^address$",
     "project_address"),
    (r"^owner ?name$|^ownername$", "owner"),
    (r"^architect ?name$|^architectname$", "architect"),
    (r"^contractor ?name(\.\d+)?$|^contractorname(\.\d+)?$", "contractor"),
    (r"^contractor ?address$|^contractoraddress$", "contractor_address"),
    (r"^contractor ?city ?state ?zip$|^contractorcitystatezip$",
     "contractor_city"),
    (r"^project ?number$|^projectnumber$", "project_number"),
    (r"^contract ?date$|^contractdate$", "contract_date"),
    (r"^date$|^date of report$", "date"),
]


_TEXTLIKE = ("text", "combobox", "combo box", "combo")


def _is_textlike(w):
    """A text or combo box field. Compared by number and, failing that,
    by PyMuPDF's type name (constants changed shape between versions)."""
    try:
        if int(w.field_type) in (int(fitz.PDF_WIDGET_TYPE_TEXT),
                                 int(fitz.PDF_WIDGET_TYPE_COMBOBOX)):
            return True
    except (TypeError, ValueError, AttributeError):
        pass
    return str(getattr(w, "field_type_string", "") or "").strip().lower() \
        in _TEXTLIKE


def _field_head(doc, xref):
    """The object holding the field's value: the widget itself, or the
    first parent with a /T name (as MuPDF's pdf_set_field_value does)."""
    x, seen = xref, set()
    while x and x not in seen:
        seen.add(x)
        if doc.xref_get_key(x, "T")[0] != "null":
            return x
        t, v = doc.xref_get_key(x, "Parent")
        if t != "xref":
            break
        x = int(v.split()[0])
    return xref


def _stored_value(doc, xref):
    """The text value as stored in the PDF (/V on the widget, else
    inherited from its parents), or None."""
    x, seen = xref, set()
    while x and x not in seen:
        seen.add(x)
        t, v = doc.xref_get_key(x, "V")
        if t != "null":
            return v if t == "string" else (v.lstrip("/") if t == "name"
                                             else v)
        t, v = doc.xref_get_key(x, "Parent")
        if t != "xref":
            break
        x = int(v.split()[0])
    return None


def _need_appearances(doc):
    try:
        doc.need_appearances(True)
        return
    except Exception:                                # noqa: BLE001
        log.debug("need_appearances failed", exc_info=True)
    try:
        cat = doc.pdf_catalog()
        t, v = doc.xref_get_key(cat, "AcroForm")
        if t == "xref":
            doc.xref_set_key(int(v.split()[0]), "NeedAppearances", "true")
        elif t == "dict":
            doc.xref_set_key(cat, "AcroForm/NeedAppearances", "true")
    except Exception:                                # noqa: BLE001
        log.debug("could not set NeedAppearances", exc_info=True)


def _pdf_str(text):
    try:
        return fitz.get_pdf_str(text)
    except Exception:                                # noqa: BLE001
        if all(32 <= ord(c) < 127 for c in text):
            return "(" + text.replace("\\", "\\\\").replace(
                "(", "\\(").replace(")", "\\)") + ")"
        return "<FEFF" + text.encode("utf-16-be").hex().upper() + ">"


def set_text(doc, w, value):
    """Give a text field `value`: Widget.update() as usual, then check the
    PDF really holds it. When it doesn't (PyMuPDF 2.0 left filled fields
    empty), /V is written directly on the field (and on the widget when it
    carries its own /V) and the look is redrawn, or left to the viewer
    with NeedAppearances."""
    value = str(value)
    w.field_value = value
    try:
        w.update()
    except Exception:                                # noqa: BLE001
        log.warning("could not update field %s", w.field_name,
                    exc_info=True)
    if _stored_value(doc, w.xref) == value:
        return True
    log.info("field %s: value not stored by Widget.update(); writing /V",
             w.field_name)

    def write_v():
        pdf = _pdf_str(value)
        head = _field_head(doc, w.xref)
        doc.xref_set_key(head, "V", pdf)
        if head != w.xref and doc.xref_get_key(w.xref, "V")[0] != "null":
            doc.xref_set_key(w.xref, "V", pdf)
    write_v()
    try:                                  # redraw from the stored value
        page = w.parent if getattr(w, "parent", None) is not None else None
        w2 = page.load_widget(w.xref) if page is not None else w
        w2.field_value = value
        w2.update()
    except Exception:                                # noqa: BLE001
        log.debug("redraw of %s failed", w.field_name, exc_info=True)
    if _stored_value(doc, w.xref) != value:
        write_v()
        _need_appearances(doc)
    return _stored_value(doc, w.xref) == value


def _widgets(pg):
    """The page's widgets as a list (made up front, so updating one can't
    disturb the iteration)."""
    return list(pg.widgets() or [])


def fill_from_job(doc, job_doc=None, overwrite=False):
    """Fill fields whose names say what they are (Project Name, Owner,
    Contractor...). Returns {field: value} of what was filled."""
    vals = job_values(job_doc)
    done = {}
    for pg in doc:
        for w in _widgets(pg):
            if not _is_textlike(w):
                continue
            name = re.sub(r"\s+", " ", str(w.field_name or "")).strip()
            if not overwrite and w.field_value not in (None, ""):
                continue
            for pat, key in _FIELD_MAP:
                if re.search(pat, name, re.I) and vals.get(key):
                    set_text(doc, w, vals[key])
                    done[name] = vals[key]
                    break
    return done
