"""One path through the estimate, nothing typed twice:

  takeoff groups -> linked cost items / quantity formulas (costlink) and
  takeoff groups priced by a unit cost -> civil activities tied to
  takeoff groups (their quantity follows the markups) -> crew hours by
  pay item -> Estimate Error Check -> customer quote with options ->
  material order list -> estimate vs actual

Every step reads the same estimate, items.collect(doc, job, lib), so a
markup drawn on the plans shows up in every one of them. run() changes
nothing in the document: the civil activities take their takeoff
quantities in the copy it prices (the Civil window saves them as usual).
"""
import copy
import logging

from . import (actuals, checks, crewhours, items, materials, quotes,
               safedb)

log = logging.getLogger(__name__)


def item_id_of_group(name, mtype, unit):
    """The estimate item id of a takeoff group priced by a unit cost."""
    return items.takeoff_id(name, mtype, unit)


@safedb.read_only
def civil(doc, lib=None, ask=None):
    """(job, lib) of the drawing's civil estimate with the activities'
    takeoff quantities brought up to date (a copy), or (None, lib) when
    there is none. The company library is only read when there is a
    civil job and no `lib` is given - read-only (safedb.civil_library):
    an empty price database is filled with the starter civil library
    only when ask(question) says Yes (v2 step 5; 0.13.9's
    heavy.library() filled it without asking)."""
    from .. import annotate, heavy
    if doc is None or heavy.FILE not in doc.embfile_names():
        return None, lib
    job = copy.deepcopy(heavy.read(doc))
    if not job.get("activities") and not job.get("pay_items"):
        return None, lib
    with annotate.scan_cache():          # one takeoff scan, not one per activity
        heavy.refresh_quantities(doc, job)
    return job, (lib if lib is not None else safedb.civil_library(ask))


@safedb.read_only
def run(doc, lib=None, spec=None, pricelists=(), history=None):
    """{"estimate", "crew_hours", "checks", "summary", "quote",
    "materials", "actuals", "job"} - all from one estimate (the drawing's
    takeoff is scanned once for all of them: annotate.scan_cache)."""
    from .. import annotate
    with annotate.scan_cache():
        return _run(doc, lib, spec, pricelists, history)


def _run(doc, lib, spec, pricelists, history):
    job, lib = civil(doc, lib)
    est = items.collect(doc, job, lib)
    found = checks.run(doc, job=job, lib=lib, history=history)
    out = {"job": job, "estimate": est,
           "crew_hours": crewhours.by_pay_item(job, lib) if job else
           {"items": [], "unassigned": None, "total_hours": 0,
            "problems": []},
           "checks": found, "summary": checks.summary(found)}
    try:
        out["quote"] = quotes.compute(doc, spec, job, lib)
    except quotes.QuoteError as e:
        out["quote"] = None
        out["quote_problem"] = str(e)
    out["materials"] = materials.order_list(doc, pricelists, job, lib)
    out["actuals"] = actuals.compare(doc, job, lib)
    return out
