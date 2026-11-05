"""The takeoff checked against the plan's own schedules (r36 v2 step 6).

The door, window, fixture, equipment and finish schedules are read from
the PDF's own text with the host's table reader (app/schedules.py) - no
OCR service, nothing sent anywhere. Each schedule's types and counts are
compared with the takeoff's count groups (and, for a finish schedule, the
room areas):

  missing  a type (or room) on a schedule with nothing in the takeoff
  count    a type whose takeoff count differs from the schedule's count
           (the QTY column; one per row on a door schedule; the door
           schedule's hardware column for hardware sets)
  extra    a takeoff item that looks like a scheduled kind (its prefix or
           its key's family) but isn't on any schedule read

Advisory only: every finding carries a confidence (high / medium / low)
and the takeoff is never changed. Quantities only - no prices.
"""
import logging
import re
import weakref

from .. import schedules

log = logging.getLogger(__name__)

KINDS = ("door", "window", "finish", "plumbing fixtures", "light fixtures",
         "toilet accessories", "equipment", "plumbing equipment",
         "mechanical equipment")
LABEL = {"door": "door", "hardware": "hardware set", "window": "window",
         "finish": "room", "plumbing fixtures": "plumbing fixture",
         "light fixtures": "light fixture",
         "toilet accessories": "toilet accessory", "equipment": "equipment",
         "plumbing equipment": "plumbing equipment",
         "mechanical equipment": "mechanical equipment"}
_KEY_FAMILY = re.compile(r"^([A-Z]{1,4})-?\d{1,3}[A-Z]?$")
_ROOM_NO = re.compile(r"\b(\d{2,4}(?:\.\d{1,2})?[A-Z]?)$")
_CACHE = {}
_SKIPPED = {}


def clear_cache():
    _CACHE.clear()
    _SKIPPED.clear()


def _doc_key(doc):
    return (id(doc), getattr(doc, "name", ""), doc.page_count)


def _discipline(txt):
    from .. import aitakeoff
    try:
        return aitakeoff.discipline("", "", txt[:3000])
    except Exception:                                     # noqa: BLE001
        return ""


def _sheet_no(page):
    """The sheet number from the title block (largest short code text)."""
    best = ("", 0.0)
    try:
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln.get("spans", []):
                    t = sp["text"].strip()
                    if re.match(r"^[A-Z]{1,2}-?\d{1,3}(?:\.\d+)?[A-Z]?$", t) \
                            and sp["size"] > best[1]:
                        best = (t, sp["size"])
    except Exception:                                     # noqa: BLE001
        pass
    return best[0] or f"page {page.number + 1}"


def read_schedules(doc, cache=None):
    """[table] of the kinds checked, with page / sheet; a schedule printed
    twice (a sheet issued again) is kept once, from its last copy."""
    key = _doc_key(doc)
    hit = _CACHE.get("last")
    if hit and hit[0] == key and hit[1]() is doc:
        return hit[2]
    cache = {} if cache is None else cache
    found = {}
    numbers = []                  # this set's sheet numbers, when needed
    skipped = []
    for p in range(doc.page_count):
        try:
            txt = doc[p].get_text()
        except Exception:                                 # noqa: BLE001
            continue
        if not txt.strip() or not schedules._SCHED_WORD.search(txt):
            continue
        try:
            ts = schedules.read_page(doc[p], _discipline(txt), cache)
        except Exception:                                 # noqa: BLE001
            log.warning("schedules on page %d not read", p + 1,
                        exc_info=True)
            continue
        sheet = _sheet_no(doc[p])
        for t in ts:
            if t.get("kind") not in KINDS or t.get("skip"):
                continue
            if not t.get("rows"):
                skipped.append({"kind": t["kind"], "title": t.get("title", ""),
                                "sheet": sheet, "page": p,
                                "why": t.get("why") or "no rows read"})
                continue
            if not numbers:
                numbers.append({_sheet_no(doc[i]).upper()
                                for i in range(doc.page_count)})
            if _is_index(t, numbers[0]):
                skipped.append({"kind": t["kind"], "title": t.get("title", ""),
                                "sheet": sheet, "page": p,
                                "why": "a drawing index (its rows are sheet "
                                       "numbers)"})
                continue
            t = dict(t, page=p, sheet=sheet)
            sig = (t["kind"], tuple(_norm(r.get(t.get("key") or "", ""))
                                    for r in t.get("rows") or ()))
            found[sig] = t                       # last copy wins
    out = sorted(found.values(), key=lambda t: (t["page"], t["kind"]))
    _SKIPPED.clear()
    _SKIPPED[key] = skipped
    try:
        ref = weakref.ref(doc)
    except TypeError:
        ref = (lambda d: (lambda: d))(doc)
    _CACHE["last"] = (key, ref, out)       # one drawing: the open one
    return out


def _is_index(t, numbers):
    """A table whose keys are mostly this set's own sheet numbers is the
    cover sheet's drawing index (titles like 'HVAC SCHEDULES')."""
    keys = [_norm(r.get(t.get("key") or "", "")) for r in t["rows"]]
    keys = [k for k in keys if k]
    hit = sum(1 for k in keys if k in numbers)
    return len(keys) >= 2 and hit * 2 >= len(keys)


def _norm(k):
    return schedules.norm_key(k or "")


def _prefix_strip(name):
    for pre in sorted({v for v in schedules.PREFIX.values() if v},
                      key=len, reverse=True):
        if name.lower().startswith(pre.lower()):
            return name[len(pre):], pre
    return name, ""


def _groups(doc):
    from .. import estimate
    try:
        return estimate.lines(doc)
    except Exception:                                     # noqa: BLE001
        log.warning("takeoff groups unreadable", exc_info=True)
        return []


def _qty(g):
    try:
        return int(round(float(g.get("quantity") or 0)))
    except (TypeError, ValueError):
        return 0


def _conf(t, known_qty, how="key"):
    if not t.get("confident"):
        return "low"
    if how != "key":
        return "low" if how == "family" and not known_qty else "medium"
    return "high" if known_qty else "medium"


def _item(t, check, key, sched_qty, take_qty, group, conf, msg):
    return {"check": check, "kind": t["kind"] if isinstance(t, dict) else t,
            "key": key, "schedule_qty": sched_qty, "takeoff_qty": take_qty,
            "group": group, "sheet": t.get("sheet", "") if isinstance(
                t, dict) else "", "confidence": conf,
            "message": msg + f" (confidence: {conf})"}


def check(doc, cache=None):
    """{"schedules": [{kind, title, sheet, page, rows, confident,
    qty_column}], "findings": [...]} - nothing on the drawing changes."""
    tables = read_schedules(doc, cache)
    groups = _groups(doc)
    counts = [g for g in groups if g.get("type") == "count"]
    areas = [g for g in groups if g.get("type") == "area"]
    by_key = {}                    # normalized key -> [count groups]
    for g in counts:
        rest, pre = _prefix_strip(g["name"].strip())
        tok = rest.split()
        if tok:
            by_key.setdefault(_norm(tok[0]), []).append((g, pre))
        if pre and rest.strip():                  # 'Hardware set ACCESS CTRL'
            by_key.setdefault(_norm(rest.strip()), []).append((g, pre))
    used = set()
    found = []
    summary = []
    for t in tables:
        summary.append({"kind": t["kind"], "title": t.get("title", ""),
                        "sheet": t["sheet"], "page": t["page"],
                        "rows": len(t.get("rows") or ()),
                        "confident": bool(t.get("confident")),
                        "qty_column": t.get("qty") or ""})
        if t["kind"] == "door":
            found += _doors(t, counts, by_key, used)
        elif t["kind"] == "finish":
            found += _finish(t, areas, used)
        else:
            found += _keyed(t, by_key, used)
    found += _extras(tables, counts, areas, by_key, used)
    seen, uniq = set(), []
    for f in found:
        k = (f["check"], f["kind"], f["key"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    found = uniq
    order = {"count": 0, "missing": 1, "extra": 2}
    found.sort(key=lambda f: (order[f["check"]], f["kind"], f["key"]))
    return {"schedules": summary, "findings": found,
            "not_read": list(_SKIPPED.get(_doc_key(doc), []))}


def _match(by_key, key, kinds_pre=None):
    out = []
    for g, pre in by_key.get(_norm(key), ()):
        if kinds_pre is not None and pre and pre not in kinds_pre:
            continue
        if all(g is not x for x, _p in out):
            out.append((g, pre))
    return [g for g, _p in out]


def _pre_for(kind):
    pre = schedules.PREFIX.get(kind, "")
    return {pre} if pre else set()


def _keyed(t, by_key, used):
    out = []
    kind = t["kind"]
    pre = _pre_for(kind)
    for r in t.get("rows") or ():
        key = (r.get(t.get("key") or "") or "").strip()
        if not key:
            continue
        sq = schedules._row_qty(r, t)
        gs = [g for g in _match(by_key, key)
              if not _prefix_strip(g["name"])[1] or
              _prefix_strip(g["name"])[1] in pre]
        for g in gs:
            used.add(id(g))
        what = LABEL[kind]
        if not gs:
            out.append(_item(t, "missing", key, sq, 0, "",
                             _conf(t, sq is not None),
                             f"{what} {key} is on the {t.get('title') or kind}"
                             f" ({t['sheet']})" + (f" x {sq}" if sq else "")
                             + " but nothing in the takeoff is named for it"))
            continue
        tq = sum(_qty(g) for g in gs)
        if sq is not None and sq != tq:
            out.append(_item(t, "count", key, sq, tq,
                             ", ".join(g["name"] for g in gs),
                             _conf(t, True),
                             f"{what} {key}: the schedule says {sq}, the "
                             f"takeoff has {tq}"))
    return out


def _doors(t, counts, by_key, used):
    out = []
    rows = [r for r in t.get("rows") or ()
            if (r.get(t.get("key") or "") or "").strip()]
    n = len(rows)
    door_gs = [g for g in counts if re.search(r"\bdoors?\b", g["name"], re.I)
               and not g["name"].lower().startswith("hardware")]
    for g in door_gs:
        used.add(id(g))
    tq = sum(_qty(g) for g in door_gs)
    if not door_gs:
        out.append(_item(t, "missing", "Doors", n, 0, "", _conf(t, True),
                         f"the {t.get('title') or 'door schedule'} "
                         f"({t['sheet']}) lists {n} doors but the takeoff "
                         "has no door count"))
    elif tq != n:
        out.append(_item(t, "count", "Doors", n, tq,
                         ", ".join(g["name"] for g in door_gs),
                         _conf(t, True),
                         f"the door schedule lists {n} doors, the takeoff "
                         f"counts {tq}"))
    hw = t.get("hw")
    if hw:
        sets = {}
        for r in rows:
            v = schedules.hw_value(r.get(hw) or "")
            if v:
                sets[v] = sets.get(v, 0) + 1
        ht = dict(t, kind="hardware")
        hw_gs = [g for g in counts
                 if g["name"].lower().startswith("hardware set ")]
        by_g = {}                 # takeoff group -> [schedule sets]
        for v, k in sorted(sets.items()):
            nv = _norm(v)
            g = next((g for g in hw_gs if _norm(g["name"][13:]) == nv),
                     None) or next(
                (g for g in hw_gs if g["name"][13:].strip() and
                 re.sub(r"\s+", " ", v.upper()).startswith(
                     re.sub(r"\s+", " ", g["name"][13:].strip().upper())
                     + " ")), None)
            if g is None:
                out.append(_item(ht, "missing", v, k, 0, "",
                                 _conf(t, True),
                                 f"hardware set {v} is on {k} door(s) in the"
                                 " door schedule but not in the takeoff"))
                continue
            used.add(id(g))
            by_g.setdefault(id(g), (g, []))[1].append((v, k))
        for g, vs in by_g.values():
            k = sum(n for _v, n in vs)
            if _qty(g) != k:
                v = " + ".join(v for v, _n in vs)
                out.append(_item(ht, "count", v, k, _qty(g), g["name"],
                                 _conf(t, True),
                                 f"hardware set {v}: {k} door(s) on the "
                                 f"door schedule, {_qty(g)} in the takeoff"))
    return out


def _room_no(name):
    m = _ROOM_NO.search((name or "").strip())
    return m.group(1).upper() if m else ""


def _finish(t, areas, used):
    out = []
    rooms = {}
    for r in t.get("rows") or ():
        k = (r.get(t.get("key") or "") or "").strip().upper()
        if k:
            rooms[k] = r
    t["_rooms"] = set(rooms)
    by_no = {}
    for g in areas:
        no = _room_no(g["name"])
        if no:
            by_no.setdefault(no, []).append(g)
    for k in sorted(rooms):
        gs = by_no.get(k, [])
        for g in gs:
            used.add(id(g))
        if not gs:
            out.append(_item(t, "missing", k, None, 0, "",
                             "medium" if t.get("confident") else "low",
                             f"room {k} is on the finish schedule "
                             f"({t['sheet']}) but has no floor area in the "
                             "takeoff"))
    return out


def _extras(tables, counts, areas, by_key, used):
    """Count groups that look scheduled (a schedule kind's prefix, or a
    key in the family of a schedule's keys) but match no schedule row."""
    out = []
    kinds = {t["kind"] for t in tables}
    fam = {}
    for t in tables:
        if t["kind"] in ("door", "finish"):
            continue
        for r in t.get("rows") or ():
            m = _KEY_FAMILY.match(_norm(r.get(t.get("key") or "") or ""))
            if m:
                fam.setdefault(m.group(1), t)
    pre_kind = {schedules.PREFIX[k]: k for k in kinds
                if schedules.PREFIX.get(k)}
    for g in counts:
        if id(g) in used:
            continue
        rest, pre = _prefix_strip(g["name"].strip())
        tok = (rest.split() or [""])[0]
        if pre and pre in pre_kind:
            t = next(x for x in tables if x["kind"] == pre_kind[pre])
            out.append(_item(t, "extra", _norm(tok), None, _qty(g),
                             g["name"], _conf(t, True, "prefix"),
                             f"{g['name']!r} ({_qty(g)}) is in the takeoff "
                             f"but {LABEL[t['kind']]} {tok} is not on the "
                             f"{t.get('title') or 'schedule'}"))
            continue
        m = _KEY_FAMILY.match(_norm(tok))
        if not pre and m and m.group(1) in fam:
            t = fam[m.group(1)]
            out.append(_item(t, "extra", _norm(tok), None, _qty(g),
                             g["name"], _conf(t, True, "family"),
                             f"{g['name']!r} ({_qty(g)}) is in the takeoff "
                             f"but {_norm(tok)} is not on the "
                             f"{t.get('title') or 'schedule'}, which lists "
                             f"the other {m.group(1)}- marks"))
    rooms = set()
    fin = [t for t in tables if t["kind"] == "finish"]
    for t in fin:
        rooms |= t.get("_rooms") or set()
    if fin and rooms:
        for g in areas:
            no = _room_no(g["name"])
            if no and no not in rooms and id(g) not in used:
                t = fin[0]
                out.append(_item(t, "extra", no, None, None, g["name"],
                                 "medium" if t.get("confident") else "low",
                                 f"floor area {g['name']!r} is in the "
                                 f"takeoff but room {no} is not on the "
                                 "finish schedule"))
    return out


def report(res):
    """Plain text: the schedules read and the findings (quantities only)."""
    lines = ["Schedules read (quantities only; advisory - the takeoff is "
             "not changed):"]
    for s in res["schedules"]:
        lines.append(f"  {s['sheet']}: {s['title']} - {s['kind']}, "
                     f"{s['rows']} row(s), "
                     f"{'read with confidence' if s['confident'] else 'NOT read with confidence'}"
                     + (f", QTY column {s['qty_column']!r}"
                        if s["qty_column"] else ", no QTY column"))
    if not res["schedules"]:
        lines.append("  (none found)")
    for s in res.get("not_read") or ():
        lines.append(f"  {s['sheet']}: {s['title']} - {s['kind']}, left "
                     f"out: {s['why']}")
    lines.append("")
    lines.append(f"Findings: {len(res['findings'])}")
    for f in res["findings"]:
        lines.append(f"  [{f['check']}] [{f['confidence']}] {f['kind']} "
                     f"{f['key']}: schedule {f['schedule_qty']}, takeoff "
                     f"{f['takeoff_qty']} - {f['message']}")
    return "\n".join(lines) + "\n"
