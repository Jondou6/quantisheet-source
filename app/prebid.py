"""Pre-bid checklist: what has to be true before a bid is locked.

Three checks:
  * every sheet is marked reviewed;
  * every markup and takeoff is accounted for - priced (a takeoff whose
    assembly is in the estimate counts automatically), excluded with a
    reason, or sent as an RFI;
  * every revision cloud (Compare Revisions changes, or anything marked
    "Check - drawing revised") is accounted for the same way, or has a
    takeoff or markup over it.

The lock records who, when, the bid total (exact cents) and a fingerprint
of the takeoff, so a later change to the takeoff shows the lock is stale.
Kept in the PDF as quantisheet_prebid.json; a markup's scope status is on the
annotation itself (PSScope).
"""
import datetime
import hashlib
import json
import logging
import os

import fitz

from . import annotate, embfiles
from .dmoney import text as money_text
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

FILE = "quantisheet_prebid.json"
SCOPE_KEY = "PSScope"
SCOPES = ("open", "priced", "excluded", "rfi")
SCOPE_NAMES = {"open": "Open", "priced": "Priced",
               "excluded": "Excluded", "rfi": "RFI"}
CHANGE_SUBJECT = "Revision change"          # overlay.CHANGE_SUBJECT


class PrebidError(Exception):
    pass


def _now():
    return datetime.datetime.now().isoformat(timespec="minutes")


def _who(by=None):
    if by:
        return by
    from . import settings
    return settings.author()


# ------------------------------------------------------------- stored data
def read(doc):
    data = {"sheets": {}, "locked": None, "log": []}
    try:
        if FILE in doc.embfile_names():
            saved = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(saved, dict):
                data.update({k: v for k, v in saved.items() if k in data})
    except Exception:
        log.warning("could not read the pre-bid checklist", exc_info=True)
    return data


def write(doc, data):
    embfiles.put(doc, FILE, json.dumps(data, indent=1).encode("utf-8"),
                 "QuantiSheet pre-bid checklist")


def sheet_key(doc, pno, numbers=None):
    """The sheet number printed on the page, or "Page n"."""
    if numbers is not None and pno in numbers:
        return numbers[pno]
    num = ""
    try:
        from . import overlay
        num = overlay.sheet_number(doc[pno]) or ""
    except Exception:
        num = ""
    key = num or f"Page {pno + 1}"
    if numbers is not None:
        numbers[pno] = key
    return key


def _sheet_keys(doc):
    """{page: key}; a sheet number used twice gets the page added."""
    nums = {}
    for p in range(doc.page_count):
        sheet_key(doc, p, nums)
    seen = {}
    for p, k in nums.items():
        seen.setdefault(k, []).append(p)
    for k, ps in seen.items():
        if len(ps) > 1:
            for p in ps:
                nums[p] = f"{k} (page {p + 1})"
    return nums


def set_reviewed(doc, pno, reviewed=True, by=None):
    data = read(doc)
    key = _sheet_keys(doc)[pno]
    if reviewed:
        data["sheets"][key] = {"reviewed": True, "by": _who(by),
                               "at": _now(), "page": pno}
    else:
        data["sheets"].pop(key, None)
    write(doc, data)
    return key


# ------------------------------------------------------------- scope
def scope_of(doc, annot):
    t, v = doc.xref_get_key(annot.xref, SCOPE_KEY)
    if t != "string" or not v:
        return {}
    try:
        s = json.loads(v)
        return s if isinstance(s, dict) else {}
    except ValueError:
        return {}


def make_scope(status, reason="", cost_code="", line_id="", rfi="",
               by=None, old=None):
    """A scope record (checked it's valid). `old` keeps the cost link and
    RFI number when they aren't given again."""
    if status not in SCOPES:
        raise PrebidError(f"Unknown status {status!r}.")
    if status == "excluded" and not str(reason or "").strip():
        raise PrebidError("Say why it's excluded (e.g. \"By owner\").")
    old = old or {}
    return {"status": status, "reason": str(reason or "").strip(),
            "cost_code": cost_code or old.get("cost_code", ""),
            "line_id": line_id or old.get("line_id", ""),
            "rfi": rfi or old.get("rfi", ""),
            "by": _who(by), "at": _now()}


def set_scope(doc, annot, status, reason="", cost_code="", rfi="",
              by=None, line_id=""):
    rec = make_scope(status, reason, cost_code, line_id, rfi, by,
                     scope_of(doc, annot))
    doc.xref_set_key(annot.xref, SCOPE_KEY,
                     fitz.get_pdf_str(json.dumps(rec)))
    return rec


def scope_mark(doc, pno, annot, status, **kw):
    """(page, "set_annot", payload) that sets the scope through the normal
    edit path (undo, live collaboration)."""
    rec = make_scope(status, old=scope_of(doc, annot), **kw)
    return (pno, "set_annot", dict(annotate.ref(annot), scope=rec))


# ------------------------------------------------------------- cost lines
def estimate_lines(doc):
    """What a markup can be priced against: {"lines": {assembly name},
    "codes": {cost code}} - the job's assemblies and those the takeoff
    uses, and their parts' cost codes."""
    from . import assemblies
    lines, codes = set(), set()
    try:
        job = assemblies.read_job(doc)
        lib = assemblies.library()
        found = dict(job.get("assemblies") or {})
        for it in annotate.totals_items(doc):
            g = it.get("group")
            if g and g not in found:
                a = assemblies.find(doc, g, job, lib)
                if a:
                    found[g] = a
        for name, a in found.items():
            lines.add(name)
            for part in a.get("parts") or []:
                if part.get("code"):
                    codes.add(str(part["code"]))
            if a.get("csi"):
                codes.add(str(a["csi"]))
    except Exception:
        log.warning("couldn't read the estimate", exc_info=True)
    return {"lines": lines, "codes": codes}


def link(doc, annot, line_id="", cost_code="", by=None):
    """Price a markup by pointing it at an estimate line (an assembly) or a
    cost code."""
    if not (line_id or cost_code):
        raise PrebidError("Pick an estimate line or a cost code.")
    return set_scope(doc, annot, "priced", line_id=line_id,
                     cost_code=cost_code, by=by)


def _link_ok(sc, est):
    if sc.get("line_id"):
        return sc["line_id"] in est["lines"]
    if sc.get("cost_code"):
        return sc["cost_code"] in est["codes"]
    return True


# ------------------------------------------------------------- RFIs
def send_to_rfi(doc, pno, annot, by=None):
    """Mark a markup "RFI" and log the RFI (one per markup). Returns the
    RFI number."""
    from . import rfilog
    sc = scope_of(doc, annot)
    num = sc.get("rfi")
    if num and any(it.get("number") == num for it in rfilog.items(doc)):
        set_scope(doc, annot, "rfi", rfi=num, by=by)
        return num
    it = rfilog.add(doc, "RFI", **rfilog.from_markup(doc, pno, annot))
    set_scope(doc, annot, "rfi", rfi=it["number"], by=by)
    return it["number"]


def _accounted(sc):
    st = sc.get("status")
    return st in ("priced", "rfi") or (st == "excluded" and
                                        bool(sc.get("reason")))


def _skip(doc, a):
    """Not a markup the checklist asks about."""
    if a.type[0] in (fitz.PDF_ANNOT_POPUP, fitz.PDF_ANNOT_WIDGET,
                     fitz.PDF_ANNOT_LINK):
        return True
    try:
        if annotate.is_label(doc, a) or annotate.is_hatch(doc, a):
            return True
    except Exception:
        pass
    subj = (a.info or {}).get("subject", "")
    return subj.startswith(annotate.TAKEOFF + ":cutout")


def _is_cloud(doc, a):
    subj = (a.info or {}).get("subject", "")
    return subj == CHANGE_SUBJECT or \
        annotate.status_of(doc, a) == annotate.REVISED


def _priced_refs(doc):
    """Takeoffs whose assembly is in the estimate (priced automatically)."""
    from . import assemblies
    out = set()
    try:
        job = assemblies.read_job(doc)
        lib = assemblies.library()
        for it in annotate.totals_items(doc):
            if it.get("group") and assemblies.find(doc, it["group"], job,
                                                   lib):
                out.add((it["page"], json.dumps(it["ref"],
                                                sort_keys=True)))
    except Exception:
        log.warning("couldn't read the estimate", exc_info=True)
    return out


class Report:
    def __init__(self):
        self.unreviewed_sheets = []
        self.open_markups = []
        self.unaccounted_clouds = []
        self.sheets = []
        self.markups = 0
        self.clouds = 0
        # spec sections with no takeoff or cost line (Phase 3); None = the
        # spec check hasn't been run, so it doesn't block the lock
        self.spec_gaps = None

    @property
    def ok(self):
        return not (self.unreviewed_sheets or self.open_markups or
                    self.unaccounted_clouds)

    def counts(self):
        return {"sheets": len(self.sheets),
                "unreviewed_sheets": len(self.unreviewed_sheets),
                "markups": self.markups,
                "open_markups": len(self.open_markups),
                "clouds": self.clouds,
                "unaccounted_clouds": len(self.unaccounted_clouds)}

    def items(self):
        """Everything still open, each with its "section"."""
        out = []
        for sec, items in (("Sheet not reviewed", self.unreviewed_sheets),
                           ("Markup open", self.open_markups),
                           ("Revision cloud", self.unaccounted_clouds),
                           ("Spec gap", self.spec_gaps or [])):
            out += [dict(it, section=sec) for it in items]
        return out

    def to_dict(self):
        return {"ok": self.ok, "counts": self.counts(),
                "spec_gaps": "not run" if self.spec_gaps is None else
                self.spec_gaps,
                "unreviewed_sheets": self.unreviewed_sheets,
                "open_markups": self.open_markups,
                "unaccounted_clouds": self.unaccounted_clouds}


def _label(doc, a, kind):
    info = a.info or {}
    subj = info.get("subject", "")
    if subj.startswith(annotate.TAKEOFF + ":"):
        parts = subj.split(":")
        grp = parts[4] if len(parts) > 4 else ""
        txt = info.get("content") or ""
        return f"Takeoff {grp or parts[1]}" + (f" - {txt}" if txt else "")
    txt = (info.get("content") or "").strip().replace("\n", " ")
    return (subj or kind) + (f": {txt[:60]}" if txt else "")


class _LazyKeys(dict):
    """Sheet keys read only for the pages asked about."""

    def __init__(self, doc):
        super().__init__()
        self.doc = doc

    def __missing__(self, pno):
        return sheet_key(self.doc, pno, self)


class _PageKeys(dict):
    """"Page n" for every page, without reading the sheet's text: the
    unpriced count and highlights (sheets=False) never show the sheet
    number, and reading it froze opening a 99-sheet set full of markups
    (Nov 3: get_text on every page with a markup, on the window thread)."""

    def __missing__(self, pno):
        return f"Page {pno + 1}"


def check(doc, sheets=True):
    """The checklist as it stands (no changes made).

    sheets=False skips the per-sheet review list: reading the sheet number
    printed on every page is most of the work (17 s on a 309-sheet set),
    and the unpriced count and highlights don't need it - only the pages
    that have an open markup get their sheet number read."""
    rep = Report()
    data = read(doc)
    keys = _sheet_keys(doc) if sheets else _PageKeys()
    priced = _priced_refs(doc)
    est = None
    for pno in range(doc.page_count if sheets else 0):
        key = keys[pno]
        st = data["sheets"].get(key) or {}
        rep.sheets.append({"page": pno, "sheet": key,
                           "reviewed": bool(st.get("reviewed")),
                           "by": st.get("by", ""), "at": st.get("at", "")})
        if not st.get("reviewed"):
            rep.unreviewed_sheets.append({"page": pno, "sheet": key,
                                          "label": f"{key} not reviewed",
                                          "rect": list(doc[pno].rect)})
    for pno in range(doc.page_count):
        page = doc[pno]
        marks, clouds = [], []
        for a in annotate.iter_annots(page):
            if _skip(doc, a):
                continue
            (clouds if _is_cloud(doc, a) else marks).append(a)
        mark_rects = [fitz.Rect(a.rect) for a in marks]
        for a in marks:
            rep.markups += 1
            sc = scope_of(doc, a)
            ref = annotate.ref(a)
            auto = (pno, json.dumps(ref, sort_keys=True)) in priced
            if sc.get("status") == "priced" and (sc.get("line_id") or
                                                 sc.get("cost_code")):
                if est is None:
                    est = estimate_lines(doc)
                if _link_ok(sc, est):
                    continue
                rep.open_markups.append({
                    "page": pno, "sheet": keys[pno], "ref": ref,
                    "rect": list(a.rect), "status": "unpriced",
                    "label": f"{_label(doc, a, 'Markup')} - linked to "
                             f"{sc.get('line_id') or sc.get('cost_code')},"
                             " which isn't in the estimate"})
                continue
            if auto and not sc.get("status"):
                continue
            if _accounted(sc) or (auto and sc.get("status") != "open"):
                continue
            why = "excluded - give a reason" if sc.get("status") == \
                "excluded" else "not priced, excluded or sent as an RFI"
            rep.open_markups.append({
                "page": pno, "sheet": keys[pno], "ref": ref,
                "rect": list(a.rect),
                "label": f"{_label(doc, a, 'Markup')} - {why}",
                "status": sc.get("status") or "open"})
        for a in clouds:
            rep.clouds += 1
            sc = scope_of(doc, a)
            if _accounted(sc):
                continue
            r = fitz.Rect(a.rect)
            if any(r.intersects(m) for m in mark_rects):
                continue
            rep.unaccounted_clouds.append({
                "page": pno, "sheet": keys[pno], "ref": annotate.ref(a),
                "rect": list(a.rect),
                "label": f"{_label(doc, a, 'Revision cloud')} - no "
                         "takeoff or decision"})
    return rep


# ------------------------------------------------------------- lock
def fingerprint(doc):
    """A hash of the takeoff (what's measured and how much)."""
    items = []
    for it in annotate.totals_items(doc):
        items.append([it["page"], it["type"], round(float(it["value"]), 4),
                      it["unit"], it.get("group", "")])
    items.sort()
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:24]


def lock(doc, total, by=None, report=None):
    rep = report or check(doc)
    if not rep.ok:
        c = rep.counts()
        raise PrebidError(
            f"Not ready to lock: {c['unreviewed_sheets']} sheet(s) not "
            f"reviewed, {c['open_markups']} markup(s) open, "
            f"{c['unaccounted_clouds']} revision cloud(s) unaccounted.")
    from . import coverage            # second-person check, when required
    left = coverage.lock_blockers(doc, total)
    if left:
        raise PrebidError("Not ready to lock: " + "; ".join(left) + ".")
    data = read(doc)
    data["locked"] = {"by": _who(by), "at": _now(),
                      "total": money_text(total),
                      "hash": fingerprint(doc)}
    try:                 # the estimate as bid, for bid-vs-actual later
        from . import pricehistory
        data["locked"]["estimate"] = [
            dict(x, qty=str(x["qty"]), unit_cost=str(x["unit_cost"]))
            for x in pricehistory.estimate_lines(doc)]
    except Exception:
        log.warning("estimate not snapshotted", exc_info=True)
    data["log"].append({"action": "locked", "by": data["locked"]["by"],
                        "at": data["locked"]["at"],
                        "total": data["locked"]["total"]})
    write(doc, data)
    return data["locked"]


def unlock(doc, by=None, reason=""):
    data = read(doc)
    if not data["locked"]:
        return None
    if not str(reason or "").strip():
        raise PrebidError("Say why you're unlocking the bid.")
    data["log"].append({"action": "unlocked", "by": _who(by), "at": _now(),
                        "reason": str(reason).strip(),
                        "was": data["locked"]})
    data["locked"] = None
    write(doc, data)
    return True


def lock_state(doc):
    """None (not locked), or the lock with "stale": True when the takeoff
    changed after locking."""
    lk = read(doc)["locked"]
    if not lk:
        return None
    return dict(lk, stale=lk.get("hash") != fingerprint(doc))


# ------------------------------------------------------------- print
def print_pdf(doc, path, report=None, title=""):
    """One-page checklist for the bid file: PASS or NOT READY, the counts,
    and the first items still open."""
    from . import safeio
    rep = report or check(doc)
    c = rep.counts()
    lk = lock_state(doc)
    out = fitz.open()
    W, H, M = 612, 792, 54
    pg = out.new_page(width=W, height=H)
    y = M + 6
    pg.insert_text((M, y), "PRE-BID CHECKLIST", fontsize=16,
                   fontname="hebo")
    y += 20
    pg.insert_text((M, y), (title or doc.name or "")[-90:], fontsize=9)
    y += 14
    pg.insert_text((M, y), f"Printed {_now().replace('T', ' ')} by "
                   f"{_who()}", fontsize=9)
    y += 30
    verdict = "PASS" if rep.ok else "NOT READY"
    col = (0.05, 0.5, 0.15) if rep.ok else (0.75, 0.05, 0.05)
    pg.insert_text((M, y), verdict, fontsize=28, fontname="hebo", color=col)
    y += 34
    rows = [("Sheets reviewed", c["sheets"] - c["unreviewed_sheets"],
             c["sheets"]),
            ("Markups accounted for", c["markups"] - c["open_markups"],
             c["markups"]),
            ("Revision clouds accounted for",
             c["clouds"] - c["unaccounted_clouds"], c["clouds"])]
    for label, done, tot in rows:
        mark = "OK" if done == tot else "X"
        pg.insert_text((M, y), f"[{mark}]  {label}: {done} of {tot}",
                       fontsize=11, fontname="hebo" if mark == "X" else
                       "helv", color=(0, 0, 0) if mark == "OK" else col)
        y += 18
    y += 8
    if lk:
        pg.insert_text((M, y), f"Locked {lk['at'].replace('T', ' ')} by "
                       f"{lk['by']} at ${_c2(float(lk['total'])):,.2f}" +
                       (" - TAKEOFF CHANGED SINCE" if lk["stale"] else ""),
                       fontsize=10, fontname="hebo")
        y += 18
    left = rep.unreviewed_sheets + rep.open_markups + \
        rep.unaccounted_clouds
    if left:
        y += 6
        pg.insert_text((M, y), "Still open:", fontsize=11, fontname="hebo")
        y += 16
        room = int((H - M - y) // 13)
        for it in left[:room - 1]:
            pg.insert_text((M + 8, y), f"{it['sheet']}: {it['label']}"[:105],
                           fontsize=8.5)
            y += 13
        if len(left) > room - 1:
            pg.insert_text((M + 8, y), f"... and {len(left) - room + 1} "
                           "more", fontsize=8.5)
    out.set_metadata({"title": "Pre-bid checklist", "creator": "QuantiSheet"})
    safeio.atomic_save(out, path, garbage=3, deflate=True)
    out.close()
    return path


# ------------------------------------------------------------- revisions
def _covered_rects(doc, pno):
    out = []
    for a in annotate.iter_annots(doc[pno]):
        if _skip(doc, a) or _is_cloud(doc, a):
            continue
        out.append(fitz.Rect(a.rect))
    return out


def uncovered_change_marks(doc, results, note=""):
    """After Compare Revisions (overlay.compare(old, doc)): a revision
    cloud for every change on `doc` that no markup or takeoff covers yet.
    Changes you've already taken off or marked aren't flagged."""
    from . import overlay
    marks = []
    for r in results:
        pno = r.get("new")
        if pno is None:
            continue
        have = _covered_rects(doc, pno)
        have += [fitz.Rect(a.rect) for a in annotate.iter_annots(doc[pno])
                 if _is_cloud(doc, a)]
        for n, c in enumerate(r.get("changes") or [], 1):
            rect = fitz.Rect(c)
            if any(rect.intersects(h) for h in have):
                continue
            marks.append((pno, "add_cloud", {
                "rect": list(rect), "color": [0.85, 0.1, 0.6],
                "subject": overlay.CHANGE_SUBJECT,
                "layer": overlay.CHANGE_LAYER,
                "note": (note or "Changed in the revision - not taken off "
                         "yet") + f" ({r.get('sheet') or 'page ' + str(pno + 1)}"
                f", change {n})"}))
    return marks


# ------------------------------------------------------------- report
def export_report(doc, path, report=None):
    """The missed-item report: every sheet, markup, cloud (and spec gap)
    still open, as Excel (.xlsx) or PDF."""
    from . import safeio
    rep = report or check(doc)
    rows = rep.items()
    c = rep.counts()
    summary = [["Pre-bid check", "PASS" if rep.ok else "NOT READY"],
               ["Sheets reviewed", f"{c['sheets'] - c['unreviewed_sheets']}"
                f" of {c['sheets']}"],
               ["Markups accounted for", f"{c['markups'] - c['open_markups']}"
                f" of {c['markups']}"],
               ["Revision clouds accounted for",
                f"{c['clouds'] - c['unaccounted_clouds']} of {c['clouds']}"],
               ["Spec gaps", "not run" if rep.spec_gaps is None else
                str(len(rep.spec_gaps))],
               ["Printed", f"{_now().replace('T', ' ')} by {_who()}"]]
    table = [["Section", "Sheet", "Page", "Item"]] + [
        [r["section"], r.get("sheet", ""), r.get("page", 0) + 1,
         r.get("label", "")] for r in rows]
    if str(path).lower().endswith(".xlsx"):
        import tempfile
        from . import acrobat
        fd, tmp = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        acrobat.write_xlsx(tmp, [("Summary", summary),
                                 ("Missed items", table)])
        with open(tmp, "rb") as f:
            safeio.atomic_write(path, f.read())
        os.remove(tmp)
        return path
    out = fitz.open()
    W, H, M = 612, 792, 50
    pg = out.new_page(width=W, height=H)
    y = M + 10
    pg.insert_text((M, y), "MISSED-ITEM REPORT", fontsize=15,
                   fontname="hebo")
    y += 24
    for k, v in summary:
        pg.insert_text((M, y), f"{k}: {v}", fontsize=10)
        y += 14
    y += 10
    for r in table[1:]:
        if y > H - M:
            pg = out.new_page(width=W, height=H)
            y = M
        pg.insert_text((M, y), f"{r[0]} - {r[1]} (p. {r[2]}): {r[3]}"[:118],
                       fontsize=8.5)
        y += 12
    if len(table) == 1:
        pg.insert_text((M, y), "Nothing open.", fontsize=10)
    safeio.atomic_save(out, path, garbage=3, deflate=True)
    out.close()
    return path
