"""Default depth / drop per takeoff item and auto labels (v15).

Set once per item (group): a label prefix (MH, CB...), a default depth for
counted structures, and a drop added to every length run (e.g. a 4 ft
service drop). Then each count click of that item is labelled MH-1, MH-2...
(numbering continues after the highest label in the whole job) and
carries the default depth, which can be changed per structure later.
Kept in the PDF (embedded file quantisheet_itemdefaults.json). civiltakeoff
still reads tags and depths printed on the drawings; this covers items
you count by hand. Wire with `item_defaults.install(win)`."""
import json
import logging
import re

from . import annotate, embfiles

log = logging.getLogger(__name__)
FILE = "quantisheet_itemdefaults.json"
KNOWN = {"manhole": "MH", "sanitary manhole": "SMH", "storm manhole": "STMH",
         "catch basin": "CB", "hydrant": "FH", "fire hydrant": "FH",
         "valve": "GV", "gate valve": "GV", "cleanout": "CO",
         "inlet": "IN", "headwall": "HW", "light pole": "LP"}


def prefix_for(group):
    g = str(group or "").strip()
    if g.lower() in KNOWN:
        return KNOWN[g.lower()]
    words = re.findall(r"[A-Za-z0-9]+", g)
    if not words:
        return "IT"
    if len(words) == 1:
        return words[0][:2].upper()
    return "".join(w[0] for w in words[:4]).upper()


def _read(doc):
    data = {"items": {}, "tags": {}}
    try:
        if FILE in doc.embfile_names():
            saved = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(saved, dict):
                data.update({k: v for k, v in saved.items() if k in data})
    except Exception:
        log.warning("could not read item defaults", exc_info=True)
    return data


def _write(doc, data):
    embfiles.put(doc, FILE, json.dumps(data, indent=1).encode("utf-8"),
                 "QuantiSheet item defaults")


def defaults(doc):
    return _read(doc)["items"]


def set_default(doc, group, prefix=None, depth=None, drop=None):
    data = _read(doc)
    cur = data["items"].get(group) or {"prefix": prefix_for(group),
                                       "depth": None, "drop": 0.0}
    if prefix:
        cur["prefix"] = str(prefix).strip().upper()[:12]
    if depth is not None:
        cur["depth"] = float(depth)
    if drop is not None:
        cur["drop"] = float(drop)
    data["items"][group] = cur
    _write(doc, data)
    return cur


def _labels(doc, prefix):
    pat = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    nums = []
    for it in annotate.takeoff_items(doc):
        m = pat.match(str(it.get("label") or "").strip())
        if m:
            nums.append(int(m.group(1)))
    return nums


def next_label(doc, group):
    d = defaults(doc).get(group)
    prefix = (d or {}).get("prefix") or prefix_for(group)
    return f"{prefix}-{max(_labels(doc, prefix), default=0) + 1}"


def decorate(doc, page, kind, payload):
    """The op payload with the item's defaults applied (a copy)."""
    m = payload.get("measure") if isinstance(payload, dict) else None
    if not isinstance(m, dict):
        return payload
    d = defaults(doc).get(m.get("group") or "")
    if not d:
        return payload
    p = dict(payload, measure=dict(m))
    if kind == "add_count" and m.get("type") == "count":
        label = next_label(doc, m["group"])
        p["n"] = label
        p["label"] = label
        data = _read(doc)
        data["tags"][label] = {"group": m["group"], "page": page,
                               "depth": d.get("depth")}
        _write(doc, data)
    elif m.get("type") == "length" and d.get("drop"):
        p["measure"]["value"] = round(float(m.get("value") or 0) +
                                      float(d["drop"]), 4)
        p["measure"]["drop"] = float(d["drop"])
    return p


def set_depth(doc, label, depth):
    data = _read(doc)
    rec = data["tags"].setdefault(label, {"group": "", "page": None})
    rec["depth"] = None if depth is None else float(depth)
    _write(doc, data)


def structures(doc):
    """[{label, group, page, depth, band}] for labelled counts still in
    the document, in label order."""
    data = _read(doc)
    present = {str(it.get("label") or "").strip(): it
               for it in annotate.takeoff_items(doc) if it["type"] == "count"}
    try:
        from .civiltakeoff import band_of
    except Exception:
        band_of = None
    rows = []
    for label, rec in data["tags"].items():
        if label not in present:
            continue
        dep = rec.get("depth")
        rows.append({"label": label, "group": rec.get("group", ""),
                     "page": present[label]["page"], "depth": dep,
                     "band": band_of(dep) if band_of else ""})

    def key(r):
        pre, _, n = r["label"].rpartition("-")
        return (pre, int(n) if n.isdigit() else 0)
    rows.sort(key=key)
    return rows


def install(win):
    """Apply defaults to every takeoff placed in the viewer."""
    from . import viewer
    cls = viewer.PdfView
    if getattr(cls, "_idf_patched", False):
        return
    orig = cls.do_op

    def do_op(self, kind, page, **payload):
        try:
            payload = decorate(self.doc, page, kind, payload)
        except Exception:
            log.exception("item defaults")
        return orig(self, kind, page, **payload)

    cls.do_op = do_op
    cls._idf_patched = True
