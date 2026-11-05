"""Sets: many PDF files worked as one drawing set, and batch slip sheet.

A set is a small JSON file (*.pdfset) next to the drawings listing its
files; the sheet index (sheet number and title of every page) is read from
the title blocks. The Sets panel lists every sheet of every file in
discipline order, so jumping from A-101 in one file to M-201 in another is
one click.

Batch slip sheet: point it at the revised drawings (any number of files, in
any order and grouping) and every sheet in the set that has a revised
version is slip sheeted in place - the newer drawing lined up under your
markups and takeoffs, the old one kept as a hidden layer, takeoffs on
changed areas flagged, the revision recorded in each file's revision log.
Each changed file is backed up first (a "_before <revision>" folder).
"""
import datetime
from . import safeio
import json
import logging
import os
import shutil

import fitz

log = logging.getLogger(__name__)

EXT = ".pdfset"


def _rel(path, base):
    try:
        return os.path.relpath(path, base)
    except ValueError:                   # another drive
        return path


def _abs(path, base):
    return path if os.path.isabs(path) else os.path.normpath(
        os.path.join(base, path))


def new(path, files=(), name=None):
    """Create a set file listing `files`. Returns the set."""
    base = os.path.dirname(os.path.abspath(path))
    s = {"name": name or os.path.splitext(os.path.basename(path))[0],
         "files": [_rel(os.path.abspath(f), base) for f in files],
         "index": [], "path": os.path.abspath(path)}
    refresh(s)
    save(s)
    return s


class SetError(Exception):
    """A set file that can't be read - shown to the user."""


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError) as e:     # ValueError covers bad UTF-8 too
        raise SetError(f"{os.path.basename(path)} isn't a QuantiSheet set "
                       f"(or it's damaged): {e}") from e
    if not isinstance(s, dict):
        raise SetError(f"{os.path.basename(path)} isn't a QuantiSheet set.")
    s["path"] = os.path.abspath(path)
    s.setdefault("files", [])
    s.setdefault("index", [])
    return s


def save(s):
    data = {k: v for k, v in s.items() if k != "path"}
    tmp = s["path"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, s["path"])
    return s["path"]


def files(s):
    base = os.path.dirname(s["path"])
    return [_abs(f, base) for f in s["files"]]


def add_files(s, paths):
    base = os.path.dirname(s["path"])
    have = {os.path.normcase(f) for f in files(s)}
    for p in paths:
        if os.path.normcase(os.path.abspath(p)) not in have:
            s["files"].append(_rel(os.path.abspath(p), base))
    refresh(s)
    save(s)
    return s


def remove_file(s, path):
    s["files"] = [f for f in s["files"] if os.path.normcase(
        _abs(f, os.path.dirname(s["path"]))) != os.path.normcase(path)]
    refresh(s)
    save(s)
    return s


def index_file(path):
    """[{file, page, number, title}] for one PDF."""
    from . import sheets
    out = []
    try:
        doc = fitz.open(path)
    except Exception:
        log.warning("could not open %s", path, exc_info=True)
        return out
    try:
        for info in sheets.scan(doc):
            out.append({"file": path, "page": info["page"],
                        "number": (info["number"] or "").upper(),
                        "title": info["title"] or ""})
    finally:
        doc.close()
    return out


def refresh(s, progress=None):
    """Re-read every file's sheet numbers and titles (skips files whose
    size and date haven't changed)."""
    base = os.path.dirname(s["path"])
    old = {}
    for e in s.get("index") or []:
        old.setdefault(e["file"], []).append(e)
    stamps = s.setdefault("stamps", {})
    index = []
    paths = files(s)
    for k, p in enumerate(paths):
        if progress:
            progress(k, len(paths), os.path.basename(p))
        rel = _rel(p, base)
        try:
            st = os.stat(p)
            stamp = f"{st.st_size}:{int(st.st_mtime)}"
        except OSError:
            continue
        if stamps.get(rel) == stamp and rel in old:
            index.extend(old[rel])
            continue
        for e in index_file(p):
            e["file"] = rel
            index.append(e)
        stamps[rel] = stamp
    s["index"] = index
    return s


def sheets(s):
    """Every sheet of the set, in discipline order: [{file (absolute),
    page, number, title, discipline}]. Pages without a number keep file
    order at the end."""
    from . import doccontrol
    base = os.path.dirname(s["path"])
    rows = []
    for e in s.get("index") or []:
        rows.append(dict(e, file=_abs(e["file"], base),
                         discipline=doccontrol.discipline_of(e["number"])
                         or "Other"))
    numbered = sorted([r for r in rows if r["number"]],
                      key=lambda r: doccontrol._key(r["number"]))
    return numbered + [r for r in rows if not r["number"]]


def find(s, number):
    number = (number or "").upper()
    return next((r for r in sheets(s) if r["number"] == number), None)


def neighbor(s, file, page, step=1):
    """The next (or previous) sheet in set order from (file, page)."""
    rows = sheets(s)
    for i, r in enumerate(rows):
        if os.path.normcase(r["file"]) == os.path.normcase(file) and \
                r["page"] == page:
            j = i + step
            return rows[j] if 0 <= j < len(rows) else None
    return rows[0] if rows else None


# ---- batch slip sheet -------------------------------------------------------------

def plan(s, revised_paths):
    """Which sheets of the set have a revised version in `revised_paths`.
    Returns {matches: [{number, file, page, new_file, new_page}], new_only:
    [{number, file, page}] (sheets only in the revision), unchanged:
    [numbers in the set with no revision], unmatched: [{file, page}]
    (revised pages whose sheet number couldn't be read - never skipped
    silently: batch_slip refuses until they're dealt with), duplicates:
    [{number, file, page}] (a second copy of a number; the first wins)}."""
    rev = []
    for p in revised_paths:
        rev.extend(index_file(p))
    by_num = {}
    unmatched, duplicates = [], []
    for r in rev:
        if not r["number"]:
            unmatched.append({"file": r["file"], "page": r["page"]})
        elif r["number"] in by_num:
            duplicates.append({"number": r["number"], "file": r["file"],
                               "page": r["page"]})
        else:
            by_num[r["number"]] = r
    mine = {r["number"]: r for r in sheets(s) if r["number"]}
    matches, new_only = [], []
    for num, r in by_num.items():
        if num in mine:
            m = mine[num]
            matches.append({"number": num, "file": m["file"],
                            "page": m["page"], "new_file": r["file"],
                            "new_page": r["page"]})
        else:
            new_only.append({"number": num, "file": r["file"],
                             "page": r["page"]})
    from . import doccontrol
    matches.sort(key=lambda m: doccontrol._key(m["number"]))
    unchanged = sorted(set(mine) - set(by_num), key=doccontrol._key)
    return {"matches": matches, "new_only": new_only,
            "unchanged": unchanged, "unmatched": unmatched,
            "duplicates": duplicates}


class SlipError(ValueError):
    pass


def batch_slip(s, revised_paths, label, backup=True, add_new=True,
               progress=None, open_docs=None, allow_unmatched=False):
    """Slip sheet every sheet of the set that has a revised version.
    `open_docs` maps an absolute path to an already open fitz document
    (changed in memory instead of on disk; the caller saves it). Returns
    {files: [{file, sheets, flagged, at_risk}], new_sheets: [...],
    backup: folder, unmatched, duplicates}. Raises SlipError when some
    revised pages have no readable sheet number, unless allow_unmatched
    (they are then listed in the report, never dropped silently)."""
    from . import annotate, overlay, revisions
    p = plan(s, revised_paths)
    if p["unmatched"] and not allow_unmatched:
        raise SlipError(
            f"{len(p['unmatched'])} revised page(s) have no sheet number "
            "that could be read: " + ", ".join(
                f"{os.path.basename(u['file'])} page {u['page'] + 1}"
                for u in p["unmatched"][:10]) +
            ". Slip sheet them by hand, or go ahead without them.")
    by_file = {}
    for m in p["matches"]:
        by_file.setdefault(m["file"], []).append(m)
    base = os.path.dirname(s["path"])
    stamp = datetime.date.today().isoformat()
    bdir = os.path.join(base, f"_before {label} {stamp}".strip()) \
        if backup else None
    report = {"files": [], "new_sheets": [], "backup": bdir,
              "unmatched": p["unmatched"], "duplicates": p["duplicates"]}
    new_docs = {}
    open_docs = open_docs or {}
    try:
        for k, (path, ms) in enumerate(by_file.items()):
            if progress and progress(k, len(by_file), os.path.basename(path)):
                report["stopped"] = True      # files already done stay done
                break
            in_memory = path in open_docs
            doc = open_docs.get(path) or fitz.open(path)
            sub = fitz.open()
            doc2 = None
            try:
                for m in ms:
                    nd = new_docs.get(m["new_file"])
                    if nd is None:
                        nd = new_docs[m["new_file"]] = fitz.open(m["new_file"])
                    sub.insert_pdf(nd, from_page=m["new_page"],
                                   to_page=m["new_page"])
                # pair exactly the planned pages, then line up and find changes
                results = []
                for n, m in enumerate(ms):
                    r = {"old": m["page"], "new": n, "sheet": m["number"],
                         "align": overlay.IDENTITY, "changes": [],
                         "changed_pct": 0.0}
                    try:
                        r["align"] = overlay.align(doc[m["page"]], sub[n])
                        r["changes"], r["changed_pct"] = overlay.changes(
                            doc[m["page"]], sub[n], r["align"])
                    except Exception:
                        log.exception("comparing %s", m["number"])
                    results.append(r)
                before = revisions.snapshot(doc)
                if bdir and not in_memory:
                    os.makedirs(bdir, exist_ok=True)
                    shutil.copy2(path, os.path.join(bdir, os.path.basename(path)))
                overlay.slip_sheet(doc, sub, results, label, add_new_sheets=False)
                doc2 = overlay.reopen(doc)
                flags = overlay.flag_ops(doc2, results, "old")
                for pno, kind, payload in flags:
                    annotate.apply_op(doc2, annotate.new_op(kind, pno, **payload))
                for pno, kind, payload in overlay.cloud_ops(
                        results, "old", f"Changed in {label}"):
                    annotate.apply_op(doc2, annotate.new_op(kind, pno, **payload))
                refs = [{k2: v for k2, v in f[2].items() if k2 != "status"}
                        for f in flags]
                entry = revisions.record(
                    doc2, label, [m["number"] for m, r in zip(ms, results)
                                  if r["changes"]], refs, before)
                if in_memory:
                    open_docs[path] = doc2
                else:
                    tmp = path + ".slip.tmp"
                    doc2.save(tmp, garbage=safeio.gc_level(doc2), deflate=True)
                    doc2.close()
                    doc.close()
                    os.replace(tmp, path)
            except BaseException:          # don't leave the files open
                if not in_memory:
                    for d in (doc2, doc):
                        if d is not None and not d.is_closed:
                            d.close()
                elif doc2 is not None and open_docs.get(path) is not doc2:
                    doc2.close()               # the tab keeps its own doc
                raise
            finally:
                sub.close()
            report["files"].append({"file": path, "sheets": len(ms),
                                    "changed": sum(1 for r in results
                                                   if r["changes"]),
                                    "flagged": len(flags),
                                    "at_risk": entry.get("at_risk", 0.0),
                                    "doc": doc2 if in_memory else None})
        if add_new and p["new_only"] and not report.get("stopped"):
            out = fitz.open()
            for r in p["new_only"]:
                nd = new_docs.get(r["file"]) or fitz.open(r["file"])
                new_docs[r["file"]] = nd
                out.insert_pdf(nd, from_page=r["page"], to_page=r["page"])
            dest = os.path.join(base, f"{label} - new sheets.pdf")
            out.save(dest)
            out.close()
            add_files(s, [dest])
            report["new_sheets"] = [r["number"] for r in p["new_only"]]
            report["new_file"] = dest
    finally:                  # cancelled or failed: close the new set
        for nd in new_docs.values():
            nd.close()
    refresh(s)
    save(s)
    return report


# ---- drawing log (P1: "drawing log with revisions, current set") ---------

def drawing_log(s):
    """[{number, title, discipline, file, page, current, date, history}]
    for every sheet of the set: the revision it is at now (the last
    revision that changed it, from each file's revision log - "Original"
    when none has), and every earlier one (superseded), newest first."""
    from . import revisions
    by_file = {}
    out = []
    for r in sheets(s):
        f = r["file"]
        if f not in by_file:
            try:
                with fitz.open(f) as d:
                    by_file[f] = revisions.read(d).get("revisions") or []
            except Exception:                             # noqa: BLE001
                log.warning("revision log of %s not read", f, exc_info=True)
                by_file[f] = []
        hist = [{"label": e.get("label"), "date": str(e.get("date") or
                                                       "")[:10]}
                for e in reversed(by_file[f])
                if r["number"] and r["number"] in (e.get("sheets") or [])]
        out.append({"number": r["number"], "title": r.get("title") or "",
                    "discipline": r["discipline"], "file": f,
                    "page": r["page"],
                    "current": hist[0]["label"] if hist else "Original",
                    "date": hist[0]["date"] if hist else "",
                    "history": hist})
    return out


def drawing_log_csv(s, path):
    """The drawing log as CSV: one row per sheet, then its superseded
    revisions."""
    import csv
    from . import safecell
    rows = drawing_log(s)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Sheet", "Title", "Discipline", "Current revision",
                    "Date", "Superseded revisions", "File"])
        for r in rows:
            w.writerow([safecell.safe_cell(x) for x in (
                r["number"], r["title"], r["discipline"], r["current"],
                r["date"], "; ".join(f"{h['label']} ({h['date']})"
                                     for h in r["history"][1:]),
                os.path.basename(r["file"]))])
    return len(rows)
