"""The one hook between QuantiSheet and the optional ClaimIT
program (quantisheet_claims). QuantiSheet never imports that package: it
starts it as a separate process and hands it one JSON file. Nothing else
is shared, and a crash over there can't take QuantiSheet down.

- launcher(): the command that starts the claims program, or None when it
  isn't installed (then the Estimate menu item is not shown).
- snapshot(doc): the takeoff quantities as the interface dict. Read-only:
  no embedded-file writes, no save, the document stays clean.
- write_snapshot(doc) / launch(doc): write it to a quantisheet-claims-* temp
  folder (settings._is_temp treats it as throwaway) and start the program.

Interface (copied word for word from quantisheet_claims/interface.py):

QuantiSheet -> module, one way, as a JSON file:

{"interface_version": 1,
 "source": {"file": "Smith Residence.pdf", "taken_at": "2026-10-20T11:40"},
 "items": [{"name": "Interior Wall", "qty": "1234.5000", "unit": "sf",
            "page_label": "A-101", "color": "#ff0000"}]}

- qty is a decimal STRING (no floats cross the line).
- One item per (name, unit, page_label, color), summed by QuantiSheet.
- load_snapshot() checks: interface_version == 1, at most 20,000 items,
  every field a string, name <= 120 chars, qty >= 0 and readable, color
  "" or "#rrggbb". A bad item is listed as rejected, never set to 0.
- The module copies items into a claim; it never re-reads the PDF, never
  writes to it, and never touches ~/.quantisheet.
"""
import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from . import annotate, dmoney, estimate, settings

log = logging.getLogger(__name__)

INTERFACE_VERSION = 1
MAX_ITEMS = 20_000
MAX_NAME = 120
EXE_NAME = "ClaimIT.exe"
DIR_NAME = "ClaimIT"                 # its install folder, beside QuantiSheet's
_COLOR = re.compile(r"^#[0-9a-f]{6}$")
_Q4 = Decimal("0.0001")


def launcher():
    """[command...] that starts the claims program, or None if absent."""
    exe = settings.get("claims_exe")
    # an override may only point at ClaimIT itself (threat model T-010)
    if isinstance(exe, str) and exe and os.path.isfile(exe) and \
            os.path.basename(exe).lower() == EXE_NAME.lower():
        return [exe]
    if getattr(sys, "frozen", False):
        install = os.path.dirname(os.path.abspath(sys.executable))
        sib = os.path.join(os.path.dirname(install), DIR_NAME, EXE_NAME)
        return [sib] if os.path.isfile(sib) else None
    try:
        found = importlib.util.find_spec("quantisheet_claims") is not None
    except (ImportError, ValueError):
        found = False
    return [sys.executable, "-m", "quantisheet_claims"] if found else None


def _page_label(doc, page):
    try:
        lab = doc[page].get_label()
    except Exception:                                     # noqa: BLE001
        lab = ""
    return lab or str(page + 1)


def _ref_key(r):
    """annotate.ref() is {"target": tag} or {"xref": n}: make it hashable."""
    return tuple(sorted(r.items())) if isinstance(r, dict) else r


def _qty_text(v):
    return str(dmoney.D(v).quantize(_Q4, rounding=ROUND_HALF_UP))


def snapshot(doc):
    """The takeoff as the interface dict (see the module docstring)."""
    colors = {}
    for m in annotate.markup_items(doc):
        c = (m.get("color") or "").lower()
        colors[(m["page"], _ref_key(m.get("ref")))] = \
            c if _COLOR.match(c) else ""
    sums, order = {}, []

    def add(name, qty, unit, page, color):
        name = (str(name).strip() or "Item")[:MAX_NAME]
        k = (name, str(unit or ""), _page_label(doc, page), color)
        if k not in sums:
            sums[k] = Decimal(0)
            order.append(k)
        sums[k] += dmoney.D(qty)

    for it in annotate.totals_items(doc):
        name = it.get("group") or it["type"].title()
        if isinstance(it.get("roof"), dict) and not it.get("group"):
            from . import roof
            name = roof.name_of(it)
        qty = (it.get("multiplier") or 1) if it["type"] == "count" else \
            (it.get("value") or 0)
        add(name, qty, it.get("unit"), it["page"],
            colors.get((it["page"], _ref_key(it.get("ref"))), ""))
    for r in estimate.roof_rows(doc):
        add(r["name"], r["quantity"], r["unit"], r["page"], "")
    for r in estimate.set_items(doc):
        add(r["item"], r["quantity"], r["unit"], r["page"], "")
    items = [{"name": k[0], "qty": _qty_text(sums[k]), "unit": k[1],
              "page_label": k[2], "color": k[3]}
             for k in order if sums[k] >= 0][:MAX_ITEMS]
    return {"interface_version": INTERFACE_VERSION,
            "source": {"file": os.path.basename(getattr(doc, "name", "") or ""),
                       "taken_at": datetime.now().isoformat(timespec="minutes")},
            "items": items}


def write_snapshot(doc):
    """Write snapshot(doc) to a new quantisheet-claims-* temp folder."""
    folder = tempfile.mkdtemp(prefix="quantisheet-claims-")
    path = os.path.join(folder, "takeoff.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot(doc), fh, indent=1, ensure_ascii=False)
    return path


def launch(doc, popen=subprocess.Popen):
    """Start the claims program as its own process (no shell)."""
    cmd = launcher()
    if cmd is None:
        raise RuntimeError("ClaimIT is not installed")
    args = list(cmd)
    if doc is not None:
        args += ["--takeoff", write_snapshot(doc)]
    log.info("starting ClaimIT: %s", args)
    return popen(args, shell=False, close_fds=True)
