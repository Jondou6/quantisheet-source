"""Receive -> validate -> diff -> classify -> (auto-)apply, plus approve,
decline and revert (design 3.2-3.7, 4.7-4.9, 4.13, 4.15).

receive() is the single intake seam: the watched folder, "Add
submission…" and (later) a hub upload page all hand a FILE to it.
receive_manual() is the GC's "Enter update for sub" form: same checks,
same queue."""
import copy
import datetime as _dt
import hashlib
import os
import shutil

from .. import schedule_record
from . import diff, drafts, model, validate
from . import match
from .formats import common, excel, msp, pdfsched, xer

READERS = {".xml": ("msp", msp.read), ".xer": ("xer", xer.read),
           ".pdf": ("pdf", pdfsched.read)}   # a printout (Jon, 0.13.12)

CHANNELS = ("folder", "manual", "web", "gc-entry")
APPROVERS = ("admin", "pm")


class ApplyRefused(RuntimeError):
    pass


def _now(now=None):
    return (now or _dt.datetime.now()).replace(microsecond=0).isoformat()


def quarantine_dir(store):
    # beside project.json (the job's data folder - one definition)
    d = os.path.join(os.path.dirname(store.path), "master", "received")
    os.makedirs(d, exist_ok=True)
    return d


def find_sha(store, sha):
    return next((s for s in model.submissions(store)
                 if s.get("sha256") == sha), None)


def receive(store, path, company, channel="manual", now=None):
    """One received file -> one submission record (returned). A file
    already received (same SHA-256) is not processed again: the earlier
    record comes back with "duplicate_of" set."""
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}")
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    size = os.path.getsize(path)
    fmt = READERS[ext][0] if ext in READERS else ext.lstrip(".") or "?"
    rec = {"company": company, "channel": channel, "file_name": name,
           "received": _now(now), "format": fmt,
           "status": "Received", "reasons": [], "drafts": []}
    cap = excel.MAX_BYTES if ext == ".xlsx" else common.MAX_BYTES
    if size > cap:
        rec["reasons"] = [{"where": name, "text": f"The file is too big "
                           f"({size:,} bytes)."}]
        return _finish_rejected(store, rec)
    with open(path, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    old = find_sha(store, sha)
    if old is not None:
        out = copy.deepcopy(old)
        out["duplicate_of"] = old["_id"]
        return out
    q = os.path.join(quarantine_dir(store), sha + ext)
    if not os.path.exists(q):
        tmp = q + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, q)
    rec.update(sha256=sha, evidence=os.path.relpath(q, store.folder))
    return _process(store, rec, _parse(store, q, ext, name, company, now),
                    company, now)


def _parse(store, q, ext, name, company, now):
    if ext == ".xlsx":
        return excel.read(store, q)
    if ext in READERS:
        return READERS[ext][1](store, q, company, now=now)
    if ext in (".mpp", ".mpt"):
        # Jon's call: no Java / MPXJ - the sub saves the file as XML
        return {"errors": [{"where": name, "text": "A Microsoft Project "
                            ".mpp file can't be read directly. In MS "
                            "Project use File > Save As > 'XML Format "
                            "(*.xml)' and send that file (or print the "
                            "schedule to PDF)."}]}
    return {"errors": [{"where": name, "text": "Not a schedule update file "
                        "(.xlsx template, MS Project .xml, P6 .xer or a "
                        "schedule printed to PDF)."}]}


def remap(store, sid, pairs, by=None, now=None):
    """Jon maps unmatched MS Project / P6 rows once (design 3.4): the
    mapping is saved for later cycles and the received file is processed
    again as a new submission; the old one becomes Superseded."""
    sub = store.get(model.SUBS, sid)
    if sub is None or sub.get("status") != "Pending review" or \
            sub.get("format") not in ("msp", "xer", "pdf"):
        raise ApplyRefused("Only a pending MS Project / P6 submission can be "
                           "mapped.")
    match.save(store, sub["company"], dict(pairs))
    q = evidence_path(store, sub)
    ext = os.path.splitext(q)[1].lower()
    rec = {k: sub.get(k) for k in ("company", "channel", "file_name",
                                   "format", "sha256", "evidence")}
    rec.update(received=_now(now), status="Received", reasons=[], drafts=[],
               remapped_from=sid, mapped_by=by if by is not None
               else store.me)
    parsed = _parse(store, q, ext, sub.get("file_name"), sub["company"],
                    now)
    return _process(store, rec, parsed, sub["company"], now)


def receive_manual(store, company, cycle, entries, by=None, now=None):
    """Q11: the GC types a sub's update. entries: [{"no", "duration",
    "percent", "actual_start", "actual_finish", "expected_finish",
    "note"}] - only the keys given change."""
    from .values import Bad, base_of, date, num, text
    acts = {a.get("_no"): a for a in store.list("activity")}
    rows, errors = [], []
    for k, e in enumerate(entries, 1):
        where = f"Entry row {k}"
        a = acts.get(str(e.get("no") or "").strip())
        if a is None:
            errors.append({"where": where, "text": f"No activity "
                           f"'{e.get('no')}'."})
            continue
        base = base_of(a)
        vals = dict(base)
        for f, v in e.items():
            if f == "no":
                continue
            if f not in base:
                errors.append({"where": where, "text": f"{a['_no']}: "
                               f"'{f}' can't be entered here."})
                continue
            try:
                vals[f] = date(v) if f in excel.DATES else \
                    text(v) if f == "note" else num(v)
            except Bad as ex:
                errors.append({"where": where, "text": f"{a['_no']} {f}: "
                               f"{ex}."})
        rows.append({"key": a["_id"], "no": a["_no"], "name": a.get("name"),
                     "ctx": False, "values": vals, "base": base,
                     "where": {f: where for f in vals}, "row": k})
    mine = set(model.slice_ids(store, company))
    for r in rows:
        if r["key"] not in mine:
            errors.append({"where": r["where"]["duration"], "text":
                           f"{r['no']} isn't {company}'s activity - it "
                           "isn't yours to update for them."})
    rows = [r for r in rows if r["key"] in mine]
    parsed = {"format": "form", "errors": errors, "warnings": [],
              "rows": rows, "new": [],
              "meta": {"company": company, "cycle": str(cycle)[:10],
                       "project": model.project_id(store),
                       "rev": model.config(store)["rev"]}}
    rec = {"company": company, "channel": "gc-entry", "file_name": "",
           "received": _now(now), "format": "form", "status": "Received",
           "reasons": [], "drafts": [], "entered_by":
           by if by is not None else store.me}
    sub = _process(store, rec, parsed, company, now, partial_ok=True)
    return sub


def _process(store, rec, parsed, company, now, partial_ok=False):
    checked = validate.check(store, parsed, company)
    meta = parsed.get("meta") or {}
    rec["cycle"] = meta.get("cycle") or ""
    rec["based_on"] = meta.get("rev", "unknown")
    if not checked["errors"]:
        # a manual entry lists only the rows it gives: no "not reported"
        built = diff.build(store, company, checked, meta)
        checked["errors"] += built["errors"]
    if checked["errors"]:
        rec["reasons"] = checked["errors"]
        rec["warnings"] = checked["warnings"]
        return _finish_rejected(store, rec)
    closed = _closed(store, company, rec["cycle"])
    if closed:
        checked["warnings"].append({"where": "file", "text": closed})
    dd = _dt.date.fromisoformat(meta["cycle"])
    imp = diff.impact(store, built["proposed"], dd)
    if imp["new_problems"]:
        rec["reasons"] = [{"where": "logic", "text": p}
                          for p in imp["new_problems"]]
        return _finish_rejected(store, rec)
    rec.update(unmatched=parsed.get("unmatched") or [],
               logic_requests=parsed.get("logic_requests") or [])
    rec.update(rows=checked["own"], warnings=checked["warnings"],
               ignored=checked["ignored"], new=checked["new"],
               not_reported=[] if partial_ok else checked["not_reported"],
               changes=_strip(built["changes"]),
               conflicts=built["conflicts"], impact=imp,
               why=diff.classify(model.config(store), built, checked, imp),
               rev_checked=model.config(store)["rev"])
    if rec.get("format") in ("msp", "xer") and \
            model.config(store).get("review_msp_xer", True):
        # Q6 (Jon): no real sub exports to test with - the PM always
        # looks at an MS Project / P6 file before it goes in
        rec["why"].append("MS Project / P6 file: always checked by the "
                          "project manager.")
    if rec.get("format") == "pdf":
        # a PDF printout carries no proof of which sub sent it (the Excel
        # template is signed for its sub and cycle) - anyone who can drop
        # a file in that sub's folder could send one (threat model T-008)
        rec["why"].append("PDF printout: not signed like the Excel "
                          "template, so the project manager checks it.")
    _supersede(store, rec)
    rec["status"] = "Pending review"
    rec = store.save_record(model.SUBS, rec)
    if not rec["why"]:
        try:
            return _apply(store, rec, by="auto-rule", status="Auto-accepted",
                          now=now)
        except ApplyRefused as ex:
            rec["why"] = [f"Not applied on its own: {ex}"]
            return store.save_record(model.SUBS, rec)
    rec["drafts"].append(drafts.for_submission(store, rec, "received"))
    return store.save_record(model.SUBS, rec)


def _closed(store, company, cyc):
    """4.8: a template from a cycle that's already closed is accepted but
    flagged. Closed = a later cycle's packet already went to this sub, or
    a later cycle's update from it was accepted."""
    later = [i.get("cycle") for i in model.config(store).get("issued") or []
             if model.same_company(i.get("company"), company)] + \
        [x.get("cycle") for x in model.submissions(store)
         if model.same_company(x.get("company"), company) and
         x.get("status") in ("Approved", "Auto-accepted")]
    later = sorted(c for c in later if c and str(c) > str(cyc))
    if later:
        return (f"This update is for the {cyc} cycle, which is closed (the "
                f"{later[-1]} cycle is already out) - check it's still "
                "current.")
    return ""


def _strip(changes):
    return [{k: c[k] for k in ("_id", "_no", "name", "field", "before",
                               "after")} for c in changes]


def _finish_rejected(store, rec):
    rec["status"] = "Rejected"
    rec["changes"] = []
    rec = store.save_record(model.SUBS, rec)
    rec["drafts"].append(drafts.for_submission(store, rec, "rejected"))
    return store.save_record(model.SUBS, rec)


def _supersede(store, rec):
    for s in model.submissions(store):
        if s.get("status") == "Pending review" and \
                model.same_company(s.get("company"), rec["company"]) and \
                s.get("cycle") == rec["cycle"]:
            s["status"] = "Superseded"
            store.save_record(model.SUBS, s)


def _guard(store, ids):
    if store.connected:
        if store.role not in APPROVERS:
            raise ApplyRefused("Only a PM or admin on the shared project "
                               "can approve schedule updates.")
        busy = sorted({p["id"] for p in store.data.get("pending") or []
                       if p.get("coll") == "activity" and p["id"] in ids})
        if busy:
            raise ApplyRefused("Some of these activities have changes not "
                               "yet synced - Sync first, then approve.")


def _write(store, values):
    """values {id: {field: value}} - all or nothing: on any error every
    touched record gets its pre-image back and the error is raised."""
    pre = {i: store.get("activity", i) for i in values}
    done = []
    try:
        for i, fields in values.items():
            a = store.get("activity", i)
            a.update(fields)
            store.save_record("activity", a)
            done.append(i)
    except Exception:
        for i in done + [x for x in values if x not in done]:
            old = pre[i]
            try:
                cur = store.get("activity", i)
                put = {k: v for k, v in old.items()}
                for k in cur:
                    if not k.startswith("_") and k not in old:
                        put[k] = None
                store.save_record("activity", put)
            except Exception:                        # noqa: BLE001
                store.coll("activity")[i] = copy.deepcopy(old)
        raise


def _apply(store, sub, by, status, now=None):
    ids = {c["_id"] for c in sub.get("changes") or []}
    _guard(store, ids)
    values = {}
    for c in sub.get("changes") or []:
        values.setdefault(c["_id"], {})[c["field"]] = c["after"]
    if values:
        try:
            _write(store, values)
        except Exception as ex:                      # noqa: BLE001
            sub["status"] = "Apply failed"
            sub["error"] = str(ex)
            return store.save_record(model.SUBS, sub)
        rev = model.bump_rev(store)
        e = schedule_record.snapshot(
            store, "update", f"{model.label(sub)} {sub['company']}, cycle "
            f"{sub.get('cycle')}" + (" (auto-accepted)" if
                                     by == "auto-rule" else ""),
            now=now)
        sub["snapshot_n"] = e["n"]
        sub["rev_applied"] = rev
    sub["applied"] = [dict(c) for c in sub.get("changes") or []]
    sub.update(status=status, decided_by=by, decided_at=_now(now))
    sub.setdefault("drafts", []).append(
        drafts.for_submission(store, sub, "accepted"))
    sub["drafts"] += drafts.slip_notices(store, sub)
    sub = store.save_record(model.SUBS, sub)
    if values:
        recheck_pending(store, skip=sub["_id"])
    return sub


def _fresh(store, sub):
    """Re-run the diff of a pending submission against the master now."""
    rows = copy.deepcopy(sub.get("rows") or [])
    checked = {"own": rows, "warnings": sub.get("warnings") or [],
               "ignored": sub.get("ignored") or [],
               "new": sub.get("new") or [], "errors": []}
    meta = {"cycle": sub["cycle"]}
    built = diff.build(store, sub["company"], checked, meta)
    if built["errors"]:
        return None, built["errors"]
    imp = diff.impact(store, built["proposed"],
                      _dt.date.fromisoformat(sub["cycle"]))
    return {"changes": _strip(built["changes"]),
            "conflicts": built["conflicts"], "impact": imp,
            "why": diff.classify(model.config(store), built, checked,
                                 imp)}, []


def recheck_pending(store, skip=None):
    """4.7: after an apply, every other pending submission's impact is
    worked out again on the new master before it can be approved."""
    n = 0
    for s in model.submissions(store):
        if s["_id"] == skip or s.get("status") != "Pending review":
            continue
        fr, errs = _fresh(store, s)
        if fr is None:
            s.update(status="Rejected", reasons=errs, changes=[])
        else:
            s.update(fr)
        s["rechecked"] = _now()
        s["rev_checked"] = model.config(store)["rev"]
        store.save_record(model.SUBS, s)
        n += 1
    return n


def _with_edits(store, sub, edits):
    """Edit and approve (3.7): Jon's values replace the sub's on its own
    rows; every one is checked like a file value and recorded as a GC
    override. Nothing is written here."""
    from .values import Bad, date, num
    rows = copy.deepcopy(sub.get("rows") or [])
    by_no = {r["no"]: r for r in rows}
    acts = {a["_id"]: a for a in store.list("activity")}
    dd = _dt.date.fromisoformat(str(sub["cycle"])[:10])
    errors, overrides = [], []
    for no, fields in (edits or {}).items():
        r = by_no.get(no)
        if r is None:
            errors.append(f"{no} isn't one of this submission's activities.")
            continue
        for f, v in fields.items():
            if f not in diff.SUB_FIELDS:
                errors.append(f"{no}: '{f}' can't be edited here.")
                continue
            try:
                val = date(v) if f in excel.DATES else num(v)
            except Bad as ex:
                errors.append(f"{no} {f}: {ex}.")
                continue
            overrides.append({"_no": no, "field": f,
                              "sub": r["values"].get(f), "gc": val})
            r["values"][f] = val
    for r in rows:
        if r["no"] in (edits or {}) and r["key"] in acts:
            errs = []
            validate._row(r, acts[r["key"]], dd, errs, [])
            errors += [e["text"] for e in errs]
    if errors:
        raise ValueError("Not approved: " + " ".join(errors))
    return rows, overrides


def approve(store, sid, by=None, now=None, edits=None):
    """edits {activity no.: {field: value}} = Edit and approve: Jon's
    values are applied (recorded as GC overrides) after the impact is
    worked out again. Project manager only (Q7)."""
    model.need_approver(store)
    sub = store.get(model.SUBS, sid)
    if sub is None or sub.get("status") != "Pending review":
        raise ApplyRefused("Only a submission waiting for review can be "
                           "approved.")
    _guard(store, {c["_id"] for c in sub.get("changes") or []})
    if edits:
        rows, overrides = _with_edits(store, sub, edits)
        trial = dict(sub, rows=rows)
        fr, errs = _fresh(store, trial)
        if fr is None:
            raise ValueError("Not approved: " + " ".join(
                e["text"] for e in errs))
        sub.update(fr, rows=rows, gc_overrides=overrides,
                   rev_checked=model.config(store)["rev"])
        _guard(store, {c["_id"] for c in sub.get("changes") or []})
        return _apply(store, sub, by if by is not None else store.me,
                      "Approved", now=now)
    if sub.get("rev_checked") != model.config(store)["rev"]:
        fr, errs = _fresh(store, sub)
        if fr is None:
            sub.update(status="Rejected", reasons=errs, changes=[])
            return store.save_record(model.SUBS, sub)
        moved = fr["changes"] != sub.get("changes") or \
            fr["impact"] != sub.get("impact")
        sub.update(fr, rev_checked=model.config(store)["rev"])
        if moved:
            sub["rechecked"] = _now(now)
            return store.save_record(model.SUBS, sub)   # look again first
    return _apply(store, sub, by if by is not None else store.me,
                  "Approved", now=now)


def decline(store, sid, reason, by=None, now=None):
    model.need_approver(store)
    sub = store.get(model.SUBS, sid)
    if sub is None or sub.get("status") != "Pending review":
        raise ApplyRefused("Only a submission waiting for review can be "
                           "declined.")
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("Give the reason (it goes in the draft reply).")
    sub.update(status="Declined", decision=reason,
               decided_by=by if by is not None else store.me,
               decided_at=_now(now))
    sub.setdefault("drafts", []).append(
        drafts.for_submission(store, sub, "declined", reason))
    return store.save_record(model.SUBS, sub)


def revert(store, sid, by=None, now=None):
    """Undo an auto-accepted (or approved) submission while the fields it
    set still hold the values it set."""
    model.need_approver(store)
    sub = store.get(model.SUBS, sid)
    if sub is None or sub.get("status") not in ("Auto-accepted",
                                                 "Approved"):
        raise ApplyRefused("Only an accepted submission can be reverted.")
    moved = []
    values = {}
    for c in sub.get("applied") or []:
        a = store.get("activity", c["_id"])
        if a is None or a.get(c["field"]) != c["after"]:
            moved.append(f"{c['_no']} {c['field']}")
        values.setdefault(c["_id"], {})[c["field"]] = c["before"]
    if moved:
        raise ValueError("Changed since it was applied, so it can't be "
                         "reverted: " + ", ".join(moved))
    _guard(store, set(values))
    if values:
        _write(store, values)
        model.bump_rev(store)
        e = schedule_record.snapshot(
            store, "update", f"Revert {model.label(sub)} {sub['company']}",
            now=now)
        sub["revert_snapshot_n"] = e["n"]
    sub.update(status="Reverted", reverted_by=by if by is not None
               else store.me, reverted_at=_now(now))
    sub = store.save_record(model.SUBS, sub)
    if values:
        recheck_pending(store, skip=sub["_id"])
    return sub


def evidence_path(store, sub):
    p = sub.get("evidence")
    return os.path.join(store.folder, p) if p else None


def copy_out(src, folder, name):
    """Move a handled inbox file into Processed / Rejected (never
    overwriting another file)."""
    os.makedirs(folder, exist_ok=True)
    base, ext = os.path.splitext(name)
    dst = os.path.join(folder, name)
    k = 1
    while os.path.exists(dst):
        dst = os.path.join(folder, f"{base} ({k}){ext}")
        k += 1
    shutil.move(src, dst)
    return dst
