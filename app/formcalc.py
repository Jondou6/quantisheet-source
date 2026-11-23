"""Form calculations and number formats, like other PDF readers (Nov 17,
Jon: forms should fill in their own totals).

A fillable form often works out its own totals - a line total from its
labor, material and equipment, a subtotal, overhead, profit, the new
contract sum - with small scripts in the form, and shows amounts as
$1,234.00. Those run in MuPDF's own form-script engine, which can only
read and set the form's fields and format their values: it has no files,
no network, no way to start a program. It is switched on for a document
only when a person fills a field (never on open), so nothing in a file
runs until someone types in it. Open actions, launch actions and links
are never run (activecontent.py).

    fill(page, name, value) -> True / False / None
        True filled; False the field turned the value down (a number
        field given letters); None no such field on the page
"""
import logging

log = logging.getLogger(__name__)


def _mu():
    import pymupdf
    return pymupdf, pymupdf.mupdf


def enable(doc):
    """Switch form scripts on for `doc` (once). True when they run."""
    if getattr(doc, "_qs_form_js", None) is not None:
        return doc._qs_form_js
    ok = False
    try:
        pymupdf, mu = _mu()
        pdoc = pymupdf._as_pdf_document(doc)
        mu.pdf_enable_js(pdoc)
        ok = bool(mu.pdf_js_supported(pdoc))
    except Exception:                                     # noqa: BLE001
        log.info("form scripts not available", exc_info=True)
    try:
        doc._qs_form_js = ok
    except Exception:                                     # noqa: BLE001
        pass
    return ok


def has_scripts(doc):
    """True when the form has calculation or format scripts."""
    try:
        for page in doc:
            for w in page.widgets() or []:
                if w.script_calc or w.script_format:
                    return True
    except Exception:                                     # noqa: BLE001
        pass
    return False


def _refresh(doc, also=None):
    """Redraw every field whose value a calculation changed (and every
    formatted one, and the one just filled), read afresh, so the page
    shows what the form worked out."""
    for page in doc:
        for w in page.widgets() or []:
            if w.script_calc or w.script_format or w.field_name == also:
                try:
                    # MuPDF's own drawing runs the field's format script
                    # ($1,234.00); PyMuPDF's would show the bare number
                    _, mu = _mu()
                    mu.pdf_dirty_annot(w._annot)
                    mu.pdf_update_annot(w._annot)
                except Exception:                         # noqa: BLE001
                    log.debug("field redraw", exc_info=True)
                    try:
                        w.update()
                    except Exception:                     # noqa: BLE001
                        pass


def fill(page, name, value):
    import fitz
    doc = page.parent
    for w in page.widgets() or []:
        if w.field_name != name:
            continue
        js = enable(doc) if has_scripts(doc) else False
        ft = w.field_type
        if ft == fitz.PDF_WIDGET_TYPE_TEXT and js:
            pymupdf, mu = _mu()
            text = "" if value is None else str(value)
            try:
                ok = mu.pdf_set_text_field_value(w._annot, text)
            except Exception:                             # noqa: BLE001
                log.info("scripted fill failed; plain fill", exc_info=True)
                ok = None
            if ok == 0:
                return False                    # the keystroke check said no
            if ok is None:
                _plain(page, w, value)
        else:
            _plain(page, w, value)
        if js:
            # work the totals out now, before any field is redrawn (a
            # redraw with the old value would write it back)
            try:
                pymupdf, mu = _mu()
                mu.pdf_calculate_form(pymupdf._as_pdf_document(doc))
            except Exception:                             # noqa: BLE001
                log.info("form calculation", exc_info=True)
        if js:
            _refresh(doc, also=name)
            # the fields now carry their own (formatted) drawing: readers,
            # this one included, show it as it is instead of drawing the
            # bare numbers again when the file is opened
            try:
                cat = doc.pdf_catalog()
                if doc.xref_get_key(cat, "AcroForm/NeedAppearances")[1] \
                        == "true":
                    doc.xref_set_key(cat, "AcroForm/NeedAppearances",
                                     "false")
            except Exception:                             # noqa: BLE001
                pass
        else:
            try:
                w.update()
            except Exception:                             # noqa: BLE001
                pass
        return True
    return None


def _plain(page, w, v):
    import fitz
    if w.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX,
                        fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
        w.field_value = w.on_state() if v else "Off"
    else:
        w.field_value = "" if v is None else str(v)
        if w.field_value == "":
            # PyMuPDF skips empty values, so clear /V ourselves
            page.parent.xref_set_key(w.xref, "V", "()")
    w.update()
