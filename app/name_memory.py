"""Item names AI Takeoff learns from you (Nov 1).

When you rename an item AI Takeoff made ("DUPLEX CONVENIENCE OUTLET" to
"Duplex receptacle"), or move AI measurements to one of your items, the
pair is remembered; the next AI Takeoff (on any job) gives what it finds
under that AI name your name straight away.

- Rooms are remembered by their name without the room number: renaming
  "OFFICE 101" to "Office - ACT" names every "OFFICE ###" the same next
  time; a new name that keeps the number ("Office 101 (carpet)") keeps
  each room's own number ("Office 205 (carpet)").
- Only renames of AI measurements teach it - renaming your own items
  changes nothing here.
- The names are one JSON file: beside the price database when that is on
  a shared folder (the office learns together), else in this PC's
  QuantiSheet folder. Setting 'remember_item_names' (on by default) turns
  the renaming at AI Takeoff off; Takeoff > Item Names Learned lists and
  removes pairs.
- The measurement keeps the AI's own name ("ai_name" in its audit), so
  the Review Queue and the audit trail still show where it came from.
"""
import datetime
import json
import logging
import os
import re
import tempfile

from . import settings

log = logging.getLogger(__name__)

FILENAME = "QuantiSheet Item Names.json"
LOCAL = "item_names.json"
MAX_PAIRS = 2000
ROOM_METHOD = "AI takeoff: rooms"
_ROOM_NUM = re.compile(r"\s+([A-Z]?\d{1,4}[A-Z]?(?:[.\-]\d{1,3}[A-Z]?)?)\s*$",
                       re.I)


def path():
    p = settings.get("item_names_file")
    if p:
        return p
    try:
        from . import pricedb
        if pricedb.is_shared():
            return os.path.join(os.path.dirname(pricedb.path()), FILENAME)
    except Exception:                                     # noqa: BLE001
        log.debug("price database location not read", exc_info=True)
    return os.path.join(settings.DIR, LOCAL)


def on():
    return bool(settings.get("remember_item_names", True))


def _read():
    try:
        with open(path(), "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("item names %s not read", path(), exc_info=True)
        return {}
    m = d.get("names") if isinstance(d, dict) else None
    return m if isinstance(m, dict) else {}


def _write(m):
    p = path()
    folder = os.path.dirname(p) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".names_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"kind": "QuantiSheet item names", "version": 1,
                       "names": m}, f, indent=1, sort_keys=True)
        os.replace(tmp, p)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _clean(s):
    return " ".join(str(s or "").split())


def split_room(name):
    """('OFFICE', '101') for 'OFFICE 101'; (name, None) without a number."""
    n = _clean(name)
    m = _ROOM_NUM.search(n)
    if m and m.start() > 0:
        return n[:m.start()], m.group(1)
    return n, None


def key_of(name, mtype="", room=False):
    """The remembered key: 'room|OFFICE|area' for a room (number left
    out), else 'NAME|type'."""
    if room:
        base, _num = split_room(name)
        return f"room|{base.upper()}|{mtype or ''}"
    return f"{_clean(name).upper()}|{mtype or ''}"


def _is_ai(method):
    m = str(method or "")
    return m.startswith(("AI takeoff", "auto"))


def learn(old, new, mtype="", methods=()):
    """Remember AI name `old` -> your name `new` (methods: the audit
    methods of the pieces renamed; nothing is learned unless one is an AI
    measurement). Returns the key learned, or None."""
    old, new = _clean(old), _clean(new)[:60]
    ai = [m for m in methods if _is_ai(m)]
    if not old or not new or old == new or not ai:
        return None
    room = any(str(m).startswith(ROOM_METHOD) for m in ai)
    tmpl = new
    if room:
        _base, num = split_room(old)
        if num and re.search(r"(?<![\w.])" + re.escape(num) + r"(?![\w])",
                             new):
            tmpl = re.sub(r"(?<![\w.])" + re.escape(num) + r"(?![\w])",
                          "{n}", new, count=1)
    k = key_of(old, mtype, room)
    m = _read()
    m[k] = {"from": split_room(old)[0] if room else old, "to": tmpl,
            "room": room, "type": mtype or "",
            "learned": datetime.date.today().isoformat()}
    if len(m) > MAX_PAIRS:
        for kk in sorted(m, key=lambda x: m[x].get("learned", ""))[
                :len(m) - MAX_PAIRS]:
            del m[kk]
    try:
        _write(m)
    except OSError:
        log.warning("item names not saved", exc_info=True)
        return None
    return k


def pairs():
    """[{key, from, to, room, type, learned}] sorted by 'from'."""
    return sorted(({"key": k, **v} for k, v in _read().items()),
                  key=lambda p: str(p.get("from", "")).lower())


def forget(key):
    m = _read()
    if key in m:
        del m[key]
        _write(m)
        return True
    return False


def name_for(name, mtype="", room=False, table=None):
    """Your name for AI name `name`, or None."""
    m = _read() if table is None else table
    hit = m.get(key_of(name, mtype, room))
    if hit is None and not room:
        hit = m.get(key_of(name, "", False))
    if hit is None and room:
        hit = m.get(key_of(name, "", True))
    if not hit:
        return None
    to = hit.get("to") or ""
    if "{n}" in to:
        _base, num = split_room(name)
        to = to.replace("{n}", num or "").strip()
    return _clean(to) or None


_MTYPE = {"area": "area", "length": "length", "count": "count",
          "volume": "volume"}


def rename_marks(marks, table=None):
    """AI Takeoff's marks [(page, kind, payload)], renamed in place where a
    name was learned. Returns {ai name: your name} for what changed."""
    if not on():
        return {}
    table = _read() if table is None else table
    if not table:
        return {}
    done = {}
    for _p, _k, pl in marks:
        meas = pl.get("measure") if isinstance(pl, dict) else None
        if not isinstance(meas, dict):
            continue
        old = meas.get("group")
        if not old or not _is_ai(meas.get("method")):
            continue
        room = str(meas.get("method") or "").startswith(ROOM_METHOD)
        new = name_for(old, _MTYPE.get(meas.get("type"), ""), room, table)
        if not new or new == old:
            continue
        meas["group"] = new
        meas.setdefault("ai_name", old)
        lab = pl.get("label")
        if isinstance(lab, str) and lab.startswith(old):
            pl["label"] = new + lab[len(old):]
        done[old] = new
    return done


def rename_result(res, done):
    """The run's CHECK items and quantity lines under the AI names in
    `done` get your names too, so a room's CHECK item still goes with its
    outline in the Review Queue."""
    if not done or not res:
        return 0
    n = 0
    for key in ("review", "quantities"):
        for x in res.get(key) or ():
            nm = x.get("name")
            if nm in done:
                x.setdefault("ai_name", nm)
                x["name"] = done[nm]
                n += 1
    return n


def methods_of(doc, refs):
    """The audit methods of the pieces [(page, ref)]."""
    from . import annotate
    out = []
    for p, r in refs:
        try:
            for a in annotate.find_annots(doc[p], r):
                out.append(str(annotate.audit_of(doc, a).get("method") or ""))
        except Exception:                                 # noqa: BLE001
            continue
    return out
