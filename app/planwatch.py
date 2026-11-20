"""Watched plan folder (Nov 19): point a job at the folder its plan sets
are downloaded into; when new sheets or addenda show up there, QuantiSheet
says so and offers the next step - log an addendum in the Addenda Gate
(so the bid can't go out until it's priced), compare the new sheets with
this set (Compare Revisions, then Slip Sheet), or open them.

Any plan room works: it's an ordinary folder. Only PDFs count; a file
still downloading (a .crdownload / .part / .tmp beside it, or changed in
the last few seconds) waits for the next look. The folder and the files
already seen are kept in the PDF (quantisheet_plan_watch.json); nothing
is moved, renamed or changed in the folder.

    watch(doc, folder)          start watching; files there now count as
                                seen (only new arrivals are offered)
    stop(doc)
    folder_of(doc) -> path or ""
    new_files(doc) -> [item]    {path, rel, kind, size} new or changed
    mark_seen(doc, items)
    log_addenda(doc, items) -> [addendum id]
"""
import datetime as _dt
import json
import logging
import os
import time

from . import embfiles

log = logging.getLogger(__name__)

FILE = "quantisheet_plan_watch.json"
SETTLE_S = 5.0             # a file changed this recently may be downloading
MAX_FILES = 5000           # a folder bigger than this isn't a plan folder
_PARTIAL = (".crdownload", ".part", ".partial", ".tmp", ".download")


def _read(doc):
    try:
        if FILE in doc.embfile_names():
            d = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(d, dict):
                seen = d.get("seen") if isinstance(d.get("seen"), dict) \
                    else {}
                return {"folder": str(d.get("folder") or ""),
                        "seen": {str(k): list(v)[:2] for k, v in seen.items()
                                 if isinstance(v, (list, tuple))}}
    except Exception:                                     # noqa: BLE001
        log.warning("plan folder watch unreadable", exc_info=True)
    return {"folder": "", "seen": {}}


def _write(doc, data):
    embfiles.put(doc, FILE, json.dumps(data).encode("utf-8"),
                 "QuantiSheet watched plan folder")


def folder_of(doc):
    return _read(doc)["folder"]


def _scan(folder):
    """{rel: (size, mtime_ns, path)} of the PDFs under `folder`."""
    out = {}
    if not folder or not os.path.isdir(folder):
        return out
    n = 0
    for dirpath, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        names = set(files)
        for f in files:
            n += 1
            if n > MAX_FILES:
                return out
            if not f.lower().endswith(".pdf"):
                continue
            if any((f + ext) in names for ext in _PARTIAL):
                continue                          # still downloading
            p = os.path.join(dirpath, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            rel = os.path.relpath(p, folder).replace("\\", "/")
            out[rel] = (st.st_size, st.st_mtime_ns, p)
    return out


def watch(doc, folder):
    """Watch `folder` for this job; what is there now counts as seen."""
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise ValueError(f"No such folder: {folder}")
    seen = {rel: [s, m] for rel, (s, m, _p) in _scan(folder).items()}
    _write(doc, {"folder": folder, "seen": seen})
    return len(seen)


def stop(doc):
    _write(doc, {"folder": "", "seen": {}})


def kind_of(path):
    """Drawings, Specs, Addenda or Other (the bid download sorter's
    rules: names first, then the first pages)."""
    from . import bidzip
    try:
        with open(path, "rb") as f:
            data = f.read(60_000_000)
    except OSError:
        return "Other"
    return bidzip.classify(path.replace("\\", "/"), data)


def new_files(doc, now=None):
    """New or changed PDFs in the watched folder, settled (not still
    being written), oldest first."""
    d = _read(doc)
    if not d["folder"]:
        return []
    now = time.time() if now is None else now
    out = []
    for rel, (size, mtime, path) in _scan(d["folder"]).items():
        if d["seen"].get(rel) == [size, mtime]:
            continue
        if now - mtime / 1e9 < SETTLE_S:
            continue                       # may still be downloading
        out.append({"path": path, "rel": rel, "size": size,
                    "mtime": mtime, "kind": kind_of(path)})
    out.sort(key=lambda x: (x["mtime"], x["rel"]))
    return out


def mark_seen(doc, items):
    d = _read(doc)
    for it in items:
        d["seen"][it["rel"]] = [it["size"], it["mtime"]]
    _write(doc, d)


def log_addenda(doc, items, today=None):
    """Each addendum file becomes an addendum in the Addenda Gate - not
    priced, so the bid form and proposal wait until it is. Returns the
    new addenda's ids."""
    from . import doccontrol
    day = (today or _dt.date.today()).isoformat()
    have = {a.get("desc", "") for a in doccontrol.addenda(doc)}
    ids = []
    for it in items:
        desc = f"Arrived in the plan folder: {it['rel']}"
        if desc in have:
            continue                       # logged already
        title = os.path.splitext(os.path.basename(it["rel"]))[0][:120]
        ids.append(doccontrol.add_addendum(doc, title, issued=day,
                                           desc=desc))
    return ids
