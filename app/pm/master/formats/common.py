"""Shared by the MS Project XML and P6 XER readers: hostile-file checks,
data date, and the step from matched file rows to the neutral rows that
validate / diff already take (design 3.3-3.4, 4.1, 4.10, 4.11, 4.14).
Pure: reads the store, writes nothing."""
import datetime as _dt

from .. import cycle, match, model
from ..values import base_of

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 5000
EVIL = (b"<!doctype", b"<!entity")


def err(where, text):
    return {"where": where, "text": text}


def load(path, out):
    """The file's bytes, or None with the reason in out["errors"]."""
    import os
    name = os.path.basename(path)
    try:
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            out["errors"].append(err(name, f"The file is too big ({size:,} "
                                     f"bytes; the limit is {MAX_BYTES:,})."))
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError as ex:
        out["errors"].append(err(name, f"Can't read the file: {ex}"))
        return None
    low = data.lower()
    evil = any(e in low for e in EVIL)
    if not evil and data.lstrip()[:1] in (b"<", b"\xef", b"\xff", b"\xfe"):
        # XML in any encoding (UTF-16 hides "<!doctype" from a byte
        # search): expat itself refuses a declaration (threat model T-007)
        from .... import safexml
        try:
            safexml.check_bytes(data, MAX_BYTES)
        except safexml.HostileFile:
            evil = True
        except Exception:                                 # noqa: BLE001
            pass                    # not well-formed: the reader says so
    if evil:
        out["errors"].append(err(name, "The file contains a DOCTYPE / ENTITY "
                                 "declaration, so it isn't read (protects "
                                 "against entity-expansion attacks)."))
        return None
    return data


def data_date(store, status, out, now=None):
    """The file's status / data date, or the latest cycle date (warned)."""
    cfg = model.config(store)["cycle"]
    if status:
        try:
            d = _dt.date.fromisoformat(str(status)[:10])
        except ValueError:
            d = None
        if d is not None:
            try:
                cd = cycle.data_date(cfg, d.year, d.month)
            except ValueError:
                cd = None
            if cd != d:
                out["warnings"].append(err(
                    "file", f"The file's status date {d.isoformat()} isn't "
                    f"a cycle date (this month's is "
                    f"{cd.isoformat() if cd else '?'}); its dates are "
                    "checked against the file's own status date."))
            return d
    today = (now or _dt.datetime.now()).date()
    d = cycle.previous_date(cfg, today)
    out["warnings"].append(err("file", "The file has no status date; the "
                               f"latest cycle date {d.isoformat()} is used "
                               "as its data date."))
    return d


def build(store, company, items, out, how_label):
    """items: [{"ref", "ids", "ext", "name", "where", "values", "links",
    "row"}] (values: duration in workdays, percent, actual dates).
    Fills out["rows"], ["unmatched"], ["logic_requests"], warnings and
    the company-mismatch error."""
    mine = set(model.slice_ids(store, company))
    seen, ref_to = {}, {}
    matched = []
    for it in items:
        a, how = match.find(store, company, it)
        if how == match.IGNORE:
            continue
        if a is None:
            out["unmatched"].append({"ref": it["ref"], "name": it["name"],
                                     "where": it["where"]})
            continue
        if a["_id"] in seen:
            out["errors"].append(err(it["where"], f"{a['_no']} is matched "
                                     f"twice ({seen[a['_id']]} and "
                                     f"{it['where']})."))
            continue
        seen[a["_id"]] = it["where"]
        ref_to[it.get("link_key", it["ref"])] = a
        matched.append((it, a, how))
    if out["unmatched"]:
        out["warnings"].append(err("file", f"{len(out['unmatched'])} row(s) "
                                   "couldn't be matched to a master "
                                   "activity - map them once (Map rows…); "
                                   "they aren't used until then."))
    owners = {model.owner_of(a) for _i, a, _h in matched}
    if matched and not any(a["_id"] in mine for _i, a, _h in matched):
        others = sorted(o for o in owners if o and o != "GC")
        if len(others) == 1:
            out["errors"].append(err("file", f"This file reports "
                                     f"{others[0]}'s activities, but it "
                                     f"came in as {company}'s. It was not "
                                     "used."))
    for it, a, how in matched:
        cur = base_of(a)
        v = dict(cur)
        v.update({k: it["values"].get(k) for k in
                  ("duration", "percent", "actual_start", "actual_finish")})
        v["expected_finish"], v["note"] = None, ""
        if not cur["percent"] and v["percent"] == 0:
            v["percent"] = cur["percent"]      # blank and 0 % are the same
        own = a["_id"] in mine
        if own:
            kept = []
            if cur["percent"] is not None and v["percent"] is not None and \
                    v["percent"] < cur["percent"]:
                kept.append(f"% complete {v['percent']:g} (master has "
                            f"{cur['percent']:g})")
                v["percent"] = cur["percent"]
            for f in ("actual_start", "actual_finish"):
                if cur[f] and not v[f]:
                    kept.append(f"blank {f.replace('_', ' ')} (master has "
                                f"{cur[f]})")
                    v[f] = cur[f]
            if kept:
                out["warnings"].append(err(it["where"], f"{a['_no']}: the "
                                           "file is behind the master - "
                                           "master values kept: " +
                                           "; ".join(kept) + "."))
            if how == "task code" and model._key(it["name"]) != \
                    model._key(a.get("name")):
                out["warnings"].append(err(it["where"], f"{a['_no']} matched "
                                           "by task code, but the name "
                                           f"differs ('{it['name']}' vs "
                                           f"'{a.get('name')}')."))
        out["rows"].append({"key": a["_id"], "no": a.get("_no"),
                            "name": a.get("name"), "ctx": not own,
                            "values": v, "base": dict(cur),
                            "where": {f: it["where"] for f in v},
                            "row": it.get("row", 0), "matched_by": how})
        links = it.get("links")
        if own and links:
            file_p = sorted((ref_to[x].get("_no") if x in ref_to else x)
                            for x in links)
            master_p = sorted(str(p.get("id")) for p in a.get("preds") or [])
            if file_p != master_p:
                out["logic_requests"].append({
                    "_id": a["_id"], "_no": a.get("_no"),
                    "name": a.get("name"), "file": file_p,
                    "master": master_p})
    return out


def new_out(fmt):
    return {"format": fmt, "meta": {}, "rows": [], "new": [], "errors": [],
            "warnings": [], "unmatched": [], "logic_requests": []}


def duration(hours, per_day):
    if hours is None:
        return None
    return round(hours / per_day, 6) if per_day else None
