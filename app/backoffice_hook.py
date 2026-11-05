"""The one hook between QuantiSheet and the optional QuantiSheet Back
Office program (quantisheet_backoffice). Same pattern as claims_hook.py:
QuantiSheet never imports that package; it starts it as a separate
process and hands it one read-only JSON snapshot. A crash over there
can't take QuantiSheet down, and the open PDF is never written.

- launcher(): the command that starts Back Office, or None when it isn't
  installed (then the Module menu item is not shown).
- snapshot(doc, store): the job as interface v1 (spec in
  quantisheet_backoffice/interface.py): project, cost codes, budget,
  contract and schedule of values, change orders, pay applications with
  their certified numbers, commitments, direct costs, timecards,
  directory and Daily Log manpower (head count and hours only). From
  the open PDF's billing data and, when a Project Center project is
  open, from its records. Read-only: no save, no embedded-file write,
  the document stays clean.
- write_snapshot(doc, store) / launch(doc, store): write it to a
  quantisheet-backoffice-* temp folder and start the program.
- add_menu_item(window, menu) / open_from_window(window): the only two
  things main_window.py calls (one import line + one call after the
  ClaimIT item in the Module menu), so the host edit stays two lines.

All money and quantities cross as decimal STRINGS: no floats.
"""
import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from . import __version__, dmoney, settings

log = logging.getLogger(__name__)

INTERFACE_VERSION = 1
EXE_NAME = "QuantiSheetBackOffice.exe"
PACKAGE = "quantisheet_backoffice"
_C = Decimal("0.01")
_Q4 = Decimal("0.0001")
_CAT = {"labor": "L", "material": "M", "equipment": "E",
        "subcontractor": "S", "subcontract": "S", "other": "O",
        "overhead": "O"}


def launcher():
    """[command...] that starts Back Office, or None if absent."""
    exe = settings.get("backoffice_exe")
    # an override may only point at Back Office itself, not any program
    # (threat model T-010)
    if isinstance(exe, str) and exe and os.path.isfile(exe) and \
            os.path.basename(exe).lower() == EXE_NAME.lower():
        return [exe]
    if getattr(sys, "frozen", False):
        install = os.path.dirname(os.path.abspath(sys.executable))
        sib = os.path.join(os.path.dirname(install), "QuantiSheetBackOffice",
                           EXE_NAME)
        return [sib] if os.path.isfile(sib) else None
    try:
        found = importlib.util.find_spec(PACKAGE) is not None
    except (ImportError, ValueError):
        found = False
    return [sys.executable, "-m", PACKAGE] if found else None


def _m(v):
    """Money -> '1234.50' (half up)."""
    return str(dmoney.D(v).quantize(_C, rounding=ROUND_HALF_UP))


def _q(v):
    return str(dmoney.D(v).quantize(_Q4, rounding=ROUND_HALF_UP))


def _s(v):
    return "" if v is None else str(v).strip()


def _cat(v):
    v = _s(v).lower()
    return _CAT.get(v, v[:1].upper() if v[:1].upper() in "LMESO" else "")


def _billing(doc, store):
    """(money data, computed apps) from Project Center or the open PDF."""
    from . import money
    data = None
    if store is not None:
        from .pm import cost
        data = cost.money_data(store)
    elif doc is not None:
        data = money.read(doc)
    if not data:
        return None, []
    apps = []
    for a in data.get("payapps") or []:
        try:
            apps.append((a, money.compute(doc, a["no"], data)))
        except Exception:                                 # noqa: BLE001
            log.warning("pay app %s left out of the snapshot", a.get("no"),
                        exc_info=True)
    return data, apps


def _payapp(a, v, store_rec=None):
    st = _s(a.get("status")).lower() or "draft"
    if st not in ("draft", "submitted", "certified", "paid"):
        st = "draft"
    out = {"number": str(a["no"]), "period_to": _s(a.get("period_to")),
           "status": st,
           "lines": [{"item": _s(r["item"]), "previous": _m(r["previous"]),
                      "this_period": _m(r["this"]),
                      "stored": _m(r["stored"])} for r in v["rows"]],
           "summary": {k: _m(x) for k, x in v["g702"].items()}}
    rec = store_rec or a
    if rec.get("received") not in (None, ""):
        out["received"] = _m(rec.get("received"))
        out["received_on"] = _s(rec.get("received_on"))[:10]
    return out


def _from_billing(snap, data, apps, store):
    info = data.get("info") or {}
    p = snap["project"]
    p["name"] = p["name"] or _s(info.get("project"))
    p["number"] = p["number"] or _s(info.get("project_no")) or \
        _s(info.get("contract_no"))
    for k_snap, k_info in (("address", "project_address"),
                           ("owner", "owner"), ("contractor", "contractor"),
                           ("architect", "architect"),
                           ("contract_no", "contract_no"),
                           ("contract_date", "contract_date")):
        p[k_snap] = p[k_snap] or _s(info.get(k_info))
    snap["contract"] = {
        "retainage_work": _q(data.get("retainage_work") or 0),
        "retainage_stored": _q(data.get("retainage_stored") or 0),
        "sov": [{"item": _s(l["item"]), "cost_code": _s(l.get("csi")),
                 "description": _s(l.get("desc")),
                 "scheduled": _m(l.get("scheduled"))}
                for l in data.get("sov") or [] if not l.get("co")]}
    for c in data.get("changes") or []:
        snap["changes"].append({
            "id": _s(c.get("id")), "pco": _s(c.get("id")) if
            _s(c.get("id")).startswith("PCO") else "",
            "cor": _s(c.get("cor_no")), "co": _s(c.get("co_no")),
            "title": _s(c.get("title")), "stage": _s(c.get("stage")) or "pco",
            "amount": _m(c.get("amount") if c.get("amount") is not None
                         else c.get("approved_amount")),
            "approved_amount": _m(c.get("approved_amount") or 0),
            "days": str(int(c.get("approved_days") or c.get("days") or 0)),
            "executed": _s(c.get("executed"))[:10]})
    recs = {}
    if store is not None:
        from .pm import cost
        recs = {i: r for i, r in enumerate(cost.payapps_in_order(store), 1)}
    for a, v in apps:
        snap["payapps"].append(_payapp(a, v, recs.get(int(a["no"]))))


def _from_store(snap, store):
    from .pm import cost
    p = snap["project"]
    p["name"] = _s(store.name)
    p["number"] = _s(store.setting("number"))
    p["address"] = _s(store.setting("address"))
    p["state"] = _s(store.setting("state"))[:2].upper()
    rows = cost.by_code(store)
    for code, r in rows.items():
        cat = _cat(r.get("category"))
        snap["cost_codes"].append({"code": code,
                                   "description": _s(r.get("description")),
                                   "category": cat})
        snap["budget"].append({"code": code,
                               "description": _s(r.get("description")),
                               "category": cat, "original": _m(r["original"]),
                               "revised": _m(r["revised"])})
    events = store.list("event")
    comm_no = {}
    for c in store.list("commitment"):
        if c.get("status") == "Void":
            continue
        number = _s(c.get("_no")) or _s(c.get("_id"))
        comm_no[c.get("_id")] = number
        vendor = _s(c.get("vendor")).lower()
        lines = [{"cost_code": cost.code_key(l.get("cost_code")),
                  "description": _s(l.get("description")),
                  "amount": _m(l.get("amount"))}
                 for l in c.get("lines") or []]
        for e in events:     # approved change lines with this vendor
            if e.get("status") != "Approved" and \
                    e.get("commitments_approved") != "Yes":
                continue
            for l in e.get("lines") or []:
                if vendor and _s(l.get("vendor")).lower() == vendor:
                    lines.append({"cost_code": cost.code_key(l.get("cost_code")),
                                  "description": f"{_s(e.get('_no'))} "
                                                 f"{_s(e.get('title'))}".strip(),
                                  "amount": _m(l.get("cost"))})
        snap["commitments"].append({
            "number": number, "vendor": _s(c.get("vendor")),
            "type": _s(c.get("type")), "lines": lines,
            "retainage": _q(c.get("retainage") or 0),
            "insurance_expires": _s(c.get("insurance_expires"))[:10],
            "license_expires": _s(c.get("license_expires"))[:10], "w9": ""})
    for x in store.list("cost"):
        snap["direct_costs"].append({
            "id": _s(x.get("_no")) or _s(x.get("_id")),
            "date": _s(x.get("date"))[:10] or _s(x.get("_created"))[:10],
            "vendor": _s(x.get("vendor")),
            "cost_code": cost.code_key(x.get("cost_code")),
            "category": _cat(x.get("category")), "amount": _m(x.get("amount")),
            "invoice": _s(x.get("invoice")), "status": _s(x.get("status")),
            "paid_on": "", "commitment": comm_no.get(x.get("commitment"), ""),
            "description": _s(x.get("description"))})
    for t in store.list("timecard"):
        if not _s(t.get("date")):
            continue
        snap["timecards"].append({
            "id": _s(t.get("_no")) or _s(t.get("_id")),
            "date": _s(t.get("date"))[:10], "foreman": _s(t.get("foreman")),
            "crew": [{"name": _s(c.get("name")) or "?",
                      "class": _s(c.get("class")),
                      "hours": _q(c.get("hours") or 0)}
                     for c in t.get("crew") or []],
            "equipment": [{"code": _s(c.get("code")) or "?",
                           "hours": _q(c.get("hours") or 0)}
                          for c in t.get("equipment") or []],
            "production": [{"cost_code": cost.code_key(c.get("cost_code")),
                            "qty": _q(c.get("qty") or 0),
                            "unit": _s(c.get("unit")),
                            "hours": _q(c.get("hours") or 0)}
                           for c in t.get("production") or []]})
    for dl in store.list("daily"):       # P2-10: manpower only, no free text
        if not _s(dl.get("date")):
            continue
        snap["daily_logs"].append({
            "id": _s(dl.get("_no")) or _s(dl.get("_id")),
            "date": _s(dl.get("date"))[:10], "status": _s(dl.get("status")),
            "manpower": [{"company": _s(m.get("company")),
                          "trade": _s(m.get("trade")),
                          "workers": str(int(dmoney.D(m.get("workers") or 0)
                                             .to_integral_value(
                                                 rounding=ROUND_HALF_UP))),
                          "hours": _q(m.get("hours") or 0)}
                         for m in dl.get("manpower") or []
                         if isinstance(m, dict)]})
    for m in store.list("member"):
        snap["directory"].append({"name": _s(m.get("name")),
                                  "company": _s(m.get("company")),
                                  "email": _s(m.get("email")),
                                  "phone": _s(m.get("phone")),
                                  "role": _s(m.get("role"))})
    # pending changes Project Center tracks as Open/Pending events
    for e in events:
        if e.get("status") in ("Open", "Pending"):
            snap["changes"].append({
                "id": _s(e.get("_no")) or _s(e.get("_id")), "pco": "",
                "cor": "", "co": "", "title": _s(e.get("title")),
                "stage": "pco", "amount": _m(cost.event_price(e)),
                "approved_amount": "0.00", "days": str(int(e.get("days") or 0)),
                "executed": ""})


def snapshot(doc=None, store=None):
    """The job as the interface v1 dict (see the module docstring)."""
    snap = {"interface_version": INTERFACE_VERSION,
            "source": {"app": f"QuantiSheet {__version__}",
                       "file": os.path.basename(getattr(doc, "name", "") or ""),
                       "folder": getattr(store, "folder", "") or "",
                       "taken_at": datetime.now().isoformat(timespec="minutes")},
            "project": {k: "" for k in ("name", "number", "address", "owner",
                                        "contractor", "architect",
                                        "contract_no", "contract_date",
                                        "state")},
            "cost_codes": [], "budget": [], "estimate": [], "activities": [],
            "contract": {"retainage_work": "0", "retainage_stored": "0",
                         "sov": []},
            "changes": [], "payapps": [], "commitments": [],
            "direct_costs": [], "timecards": [], "directory": [],
            "daily_logs": []}
    if store is not None:
        _from_store(snap, store)
    data, apps = _billing(doc, store)
    if data:
        _from_billing(snap, data, apps, store)
    p = snap["project"]
    p["number"] = p["number"] or p["name"] or "(no number)"
    return snap


def cleanup_snapshots(max_age=24 * 3600, now=None):
    """Delete quantisheet-backoffice-* temp folders older than a day: Back
    Office deletes the one it imports, but one it never opened (it didn't
    start, or was closed first) held job data in %TEMP% (threat model
    T-011). Returns folders removed."""
    import shutil
    import time
    now = now or time.time()
    base = tempfile.gettempdir()
    n = 0
    try:
        names = os.listdir(base)
    except OSError:
        return 0
    for name in names:
        if not name.startswith("quantisheet-backoffice-"):
            continue
        p = os.path.join(base, name)
        try:
            if os.path.isdir(p) and not os.path.islink(p) and \
                    now - os.path.getmtime(p) > max_age:
                shutil.rmtree(p, ignore_errors=True)
                n += 1
        except OSError:
            pass
    return n


def write_snapshot(doc=None, store=None):
    """Write snapshot() to a new quantisheet-backoffice-* temp folder."""
    cleanup_snapshots()
    folder = tempfile.mkdtemp(prefix="quantisheet-backoffice-")
    path = os.path.join(folder, "snapshot.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot(doc, store), fh, indent=1, ensure_ascii=False)
    return path


def launch(doc=None, store=None, popen=subprocess.Popen, extra=()):
    """Start Back Office as its own process (no shell)."""
    cmd = launcher()
    if cmd is None:
        raise RuntimeError("QuantiSheet Back Office is not installed")
    args = list(cmd)
    if doc is not None or store is not None:
        args += ["--snapshot", write_snapshot(doc, store)]
    args += list(extra)
    log.info("starting QuantiSheet Back Office: %s", args)
    return popen(args, shell=False, close_fds=True)


MENU_TEXT = "QuantiSheet Back Office…"


def add_menu_item(window, menu):
    """Add 'QuantiSheet Back Office…' to `menu` only when the program is
    installed. Returns the QAction or None. The WHOLE body is guarded: any
    error here is logged and QuantiSheet's menu build carries on."""
    act = None
    try:
        if launcher() is None:
            return None
        act = menu.addAction(MENU_TEXT)
        act.triggered.connect(lambda *_: open_from_window(window))
        return act
    except Exception:                                     # noqa: BLE001
        log.warning("Back Office menu item not added", exc_info=True)
        if act is not None:
            try:
                menu.removeAction(act)
            except Exception:                             # noqa: BLE001
                pass
        return None


def _store_for(window):
    path = getattr(window, "_path", None)
    if not path:
        return None
    from .pm.store import ProjectStore, open_store
    d = os.path.dirname(os.path.abspath(path))
    for folder in (d, os.path.dirname(d)):
        if ProjectStore.exists(folder):
            return open_store(folder)
    return None


def open_from_window(window, popen=subprocess.Popen):
    """Start Back Office with a read-only snapshot of the window's open
    drawing and its Project Center records (both optional)."""
    view = getattr(window, "_view", None)
    doc = getattr(view, "doc", None) if view is not None else None
    try:
        return launch(doc, _store_for(window), popen=popen)
    except Exception as e:                                # noqa: BLE001
        log.warning("could not start Back Office", exc_info=True)
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(window, "QuantiSheet Back Office",
                            f"Could not start Back Office:\n{e}")
        return None
