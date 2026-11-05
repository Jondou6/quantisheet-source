"""What a PDF carries that could act on its own (review 2, Nov 4 - Venice
#1): JavaScript, open/close actions, launch actions and XFA forms.

QuantiSheet never runs a PDF's scripts: PyMuPDF/MuPDF here doesn't
execute them (tests/test_active_content.py proves a form calculation
script doesn't run), links open only web and email after asking (see
main_window.LINK_SCHEMES), and launch actions are never followed. So the
policy is fixed at "Off"; there is no "On". What changes is that people
are told: one line on open, and the log says what was found.

XFA (dynamic) forms: shown as the static pages the file carries (often a
"please wait" page). They're not rendered, flattened or filled here; the
message says to fill them in the program the form was made for.
"""
import logging
import re

log = logging.getLogger(__name__)

POLICY = "off"                   # the only one: scripts are never run
_JS = re.compile(r"/S\s*/JavaScript|/JS\s*[(<]|/JS\s+\d+\s+\d+\s+R|"
                 r"/JavaScript\s*(?:<<|\d+\s+\d+\s+R)")
_LAUNCH = re.compile(r"/S\s*/Launch")


def scan(doc, limit=20000):
    """{"javascript": n, "auto_actions": n, "launch": n, "xfa": bool}."""
    out = {"javascript": 0, "auto_actions": 0, "launch": 0, "xfa": False}
    try:
        n = min(doc.xref_length(), limit)
    except Exception:                                     # noqa: BLE001
        return out
    for x in range(1, n):
        try:
            obj = doc.xref_object(x, compressed=False)
        except Exception:                                 # noqa: BLE001
            continue
        if _JS.search(obj):
            out["javascript"] += 1
        if _LAUNCH.search(obj):
            out["launch"] += 1
    try:
        cat = doc.pdf_catalog()
        if doc.xref_get_key(cat, "AA")[0] not in ("null", ""):
            out["auto_actions"] += 1
        if doc.xref_get_key(cat, "OpenAction")[0] not in ("null", ""):
            out["auto_actions"] += 1
        out["xfa"] = doc.xref_get_key(cat, "AcroForm/XFA")[0] != "null"
    except Exception:                                     # noqa: BLE001
        pass
    return out


def message(found):
    """One plain line for the open file, or ''."""
    bits = []
    if found.get("javascript") or found.get("auto_actions"):
        bits.append("scripts (QuantiSheet never runs them)")
    if found.get("launch"):
        bits.append("a 'launch a program' action (never followed)")
    if found.get("xfa"):
        bits.append("an XFA form - only its static pages show here; fill "
                    "it in the program the form was made for")
    if not bits:
        return ""
    return "This PDF contains " + "; ".join(bits) + "."


def note_on_open(doc, path=""):
    """Scan, log what was found, and return the message ('' if none)."""
    found = scan(doc)
    msg = message(found)
    if msg:
        log.info("active content in %s: %s", path or "a PDF", found)
    return msg
