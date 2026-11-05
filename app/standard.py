"""Takeoff Standard (Nov 2, scope list item 17): the office's takeoff
workflow as a checklist kept with each drawing, so every estimator works
the same way - set up the document, columns, tools, take off, legend,
revisions, update, report.

Steps the program can see are checked from the drawing itself (every
sheet with takeoff has a scale, no AI item left unchecked, a legend is
on the sheets...); the rest are ticked by hand. Your office can add its
own steps (Takeoff Standard > Edit Steps), saved for you and offered on
every job. Ticks are saved inside the PDF.
"""
import json
import logging

from . import annotate, embfiles, settings

log = logging.getLogger(__name__)

FILE = "quantisheet_standard.json"

STEPS = [
    ("setup", "Document setup",
     "Every sheet with takeoff has a scale (and the scale was checked)."),
    ("columns", "Columns",
     "The Markups List has the office's columns (unit cost, product...)."),
    ("tools", "Tools",
     "Measurements were made with the office's tool sets, so each has a "
     "name."),
    ("takeoff", "Takeoff",
     "Everything is taken off, and no AI Takeoff item is left unchecked."),
    ("legends", "Legends",
     "A legend is on the sheets with takeoff."),
    ("revisions", "Revisions",
     "New drawings compared with the old ones (Revision Changes)."),
    ("update", "Update takeoff",
     "Quantities changed by the revisions are taken off again."),
    ("report", "Report",
     "The quantities and estimate are exported for the bid."),
]


def read(doc):
    try:
        if FILE in doc.embfile_names():
            d = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(d, dict):
                d.setdefault("ticks", {})
                return d
    except Exception:
        log.warning("could not read the takeoff standard", exc_info=True)
    return {"ticks": {}}


def write(doc, data):
    embfiles.put(doc, FILE, json.dumps(data).encode("utf-8"),
                 "QuantiSheet takeoff standard")


def own_steps():
    """Your office's own steps: [(key, title, what)]."""
    out = []
    for i, s in enumerate(settings.get("standard_steps") or []):
        if isinstance(s, str) and s.strip():
            title, _, what = s.partition(":")
            out.append((f"own{i}", title.strip()[:60], what.strip()[:200]))
    return out


def set_own_steps(lines):
    settings.set("standard_steps", [str(x).strip()[:260] for x in lines
                                    if str(x).strip()][:30])


def auto(doc):
    """{step: (done, what the drawing shows)} for the steps the program
    can check."""
    items = annotate.takeoff_items(doc)
    pages = sorted({it["page"] for it in items})
    out = {}
    scales = annotate.read_scales(doc)
    unscaled = [p + 1 for p in pages if p not in scales]
    if not items:
        out["setup"] = (False, "No takeoff yet.")
    elif unscaled:
        out["setup"] = (False, "No scale on page(s) " + ", ".join(
            map(str, unscaled[:10])) + ".")
    else:
        out["setup"] = (True, f"All {len(pages)} sheet(s) with takeoff "
                        "have a scale.")
    from . import columns
    cols = columns.read(doc)["columns"]
    out["columns"] = (bool(cols), f"{len(cols)} column(s)." if cols else
                      "No Markups List columns yet.")
    plain = [it for it in items if not it["group"]]
    if items:
        out["tools"] = (not plain, "Every measurement has a name." if
                        not plain else f"{len(plain)} measurement(s) have "
                        "no name.")
    pending = [it for it in items if it.get("pending")]
    if items:
        out["takeoff"] = (not pending, "No AI item waiting." if not pending
                          else f"{len(pending)} AI item(s) not checked.")
    with_legend = set()
    for p in pages:
        if any(annotate.is_legend(doc, a)
               for a in annotate.iter_annots(doc[p])):
            with_legend.add(p)
    if pages:
        if any(_all_pages_legend(doc, p) for p in range(doc.page_count)):
            out["legends"] = (True, "A legend totals the whole set.")
        else:
            missing = [p + 1 for p in pages if p not in with_legend]
            out["legends"] = (not missing, "Every sheet with takeoff has a "
                              "legend." if not missing else "No legend on "
                              "page(s) " + ", ".join(map(str, missing[:10]))
                              + ".")
    return out


def _all_pages_legend(doc, pno):
    from . import legend
    return any(annotate.is_legend(doc, a) and
               legend.opts_of(doc, a).get("scope") == "all"
               for a in annotate.iter_annots(doc[pno]))


def status(doc):
    """[{key, title, what, done, auto, note}] for every step: a step is
    done when the drawing shows it, or when it was ticked."""
    data = read(doc)
    checks = auto(doc)
    out = []
    for key, title, what in STEPS + own_steps():
        a = checks.get(key)
        ticked = bool(data["ticks"].get(key))
        out.append({"key": key, "title": title, "what": what,
                    "auto": a is not None, "note": a[1] if a else "",
                    "done": (a[0] if a else False) or ticked,
                    "ticked": ticked})
    return out


def tick(doc, key, on=True):
    data = read(doc)
    if on:
        data["ticks"][key] = True
    else:
        data["ticks"].pop(key, None)
    write(doc, data)
    return data
