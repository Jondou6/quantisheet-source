"""Checks around saving (Nov 4, review QS-001 / QS-004 / QS-005).

is_signed(doc): the PDF carries digital signatures (a save that rewrites
the file makes them invalid; one that adds to it keeps them, with the
changes shown as made after signing).
"""
import logging

import fitz

log = logging.getLogger(__name__)


def _signed_in_field_list(doc, limit=5000):
    """Walk /Root/AcroForm/Fields (and /Kids) for a /FT /Sig field whose
    /V is set. Reads objects only, never pages."""
    cat = doc.pdf_catalog()
    kind, val = doc.xref_get_key(cat, "AcroForm")
    if kind == "null":
        return False
    if kind == "xref":
        form = int(val.split()[0])
        kind, val = doc.xref_get_key(form, "Fields")
    else:
        return False
    if kind != "array":
        return False
    import re
    refs = re.compile(r"(\d+)\s+\d+\s+R")
    todo = [int(x) for x in refs.findall(val)]
    seen = set()
    while todo and len(seen) < limit:
        x = todo.pop()
        if x in seen or x <= 0:
            continue
        seen.add(x)
        ft = doc.xref_get_key(x, "FT")
        v = doc.xref_get_key(x, "V")
        if ft[1] == "/Sig" and v[0] not in ("null", "none"):
            return True
        k = doc.xref_get_key(x, "Kids")
        if k[0] == "array":
            todo += [int(n) for n in refs.findall(k[1])]
    return False


def is_signed(doc):
    """True when the PDF has a signed signature field."""
    # the form's SigFlags say so without reading any page (a 1,000-sheet
    # set must not load every page to find out - Nov 4)
    try:
        flags = doc.get_sigflags()
    except Exception:                                     # noqa: BLE001
        return False
    if flags is None or flags <= 0:
        return False                     # no form, or no signatures in it
    if flags & 1:
        return True
    # any size (review 2, Nov 4): the form's own field list, read from the
    # catalog - a signed field has a /V signature dictionary - no pages
    try:
        if _signed_in_field_list(doc):
            return True
    except Exception:                                     # noqa: BLE001
        log.debug("signature field list", exc_info=True)
    if doc.page_count > 50:
        return False
    try:                                 # a small form: look at its fields
        for pg in doc:
            for w in pg.widgets() or []:
                if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE and \
                        getattr(w, "is_signed", False):
                    return True
    except Exception:                                     # noqa: BLE001
        log.debug("signature scan", exc_info=True)
    return False
