"""Compile a schedule. The model is optional and never writes durations.

Order: read and segment, deterministic facts, optional model facts, merge,
build the network from the template and the rule table, run the critical
path, score completeness, score schedule health, write the narrative and
the review queue.
"""
import datetime as _dt

from . import ai_extract, buildnet, cpm, extract, health, ingest, merge
from . import bidset, narrative, reviewq, rubric
from .model import as_date
from .options import FALLBACK_MODEL, RECOMMENDED_MODEL, load as load_settings


def _progress(cb, stage, message, index=1, total=1):
    if cb:
        cb({"stage": stage, "index": index, "total": total, "message": message})


def compile_schedule(spec_pages=None, drawings=None, spec_pdf=None,
                     drawings_pdf=None, project_type=None, takeoff=None,
                     cost_book=None, productivity=None, actuals=None,
                     ntp=None, data_date=None, project_name="Project",
                     template_dir=None, settings=None, ask=None,
                     progress=None, holidays=None, area_sf=None, stories=1,
                     ocr=None, weather_months=None, bid_set=None):
    """bid_set: the bid documents in the order issued - bid form, sheets,
    addenda, Q&A ({"kind", "id", "text"}, see bidset). Later documents
    win; removed scope is kept on doc["scope"]["removed"]."""
    cfg = dict(load_settings(template_dir))
    bid = bidset.resolve(bid_set) if bid_set else None
    if bid is not None and not project_type:
        project_type = "tenant_improvement"
    if isinstance(settings, dict):
        cfg.update(settings)
    _progress(progress, "ingest", "Reading specs and drawings")
    if spec_pdf and not spec_pages:
        sections, spec_q = ingest.ingest_pdf(spec_pdf, "spec", ocr=True)
        spec_pages = _pages_from_sections(sections)
        drawn, draw_q = [], []
        if drawings_pdf:
            drawn, draw_q = ingest.ingest_pdf(drawings_pdf, "drawings", ocr=True)
        bundle = {
            "spec_sections": sections,
            "drawings": drawings or drawn,
            "blank_pages": (ingest.blank_report(spec_q, "spec")
                            + ingest.blank_report(draw_q, "drawings")),
            "divisions": sorted({s["division"] for s in sections
                                 if s.get("division")}),
        }
    else:
        bundle = ingest.ingest(spec_pages, drawings, ocr=ocr)
    _progress(progress, "extract", "Reading durations, long-lead items and Division 01")
    facts, ct = extract.extract(bundle.get("spec_sections"), spec_pages)
    allow = bool(cfg.get("allow_ai", True))
    if allow:
        caller = ask or _default_ask
        model = cfg.get("model") or RECOMMENDED_MODEL
        fallback = cfg.get("fallback_model") or FALLBACK_MODEL
        more, errors = ai_extract.extract_sections(
            bundle.get("spec_sections"), caller, model, fallback,
            cfg.get("chunk_chars") or 3500,
            progress=progress, allow=True)
        facts.extend(more)
    else:
        errors = []
        _progress(progress, "model", "AI is off; using templates and the deterministic read")
    merged, conflicts = merge.merge(facts)
    _progress(progress, "network", "Building activities, logic and calendars")
    if holidays is None:
        holidays = _holidays(ntp)
    doc = buildnet.assemble(
        merged, ct, bundle, project_type=project_type, takeoff=takeoff,
        cost_book=cost_book, productivity=productivity, actuals=actuals,
        ntp=ntp, data_date=data_date, holidays=holidays, name=project_name,
        template_dir=template_dir, area_sf=area_sf, stories=stories,
        weather_months=weather_months, bid=bid)
    doc["model_errors"] = errors
    doc["conflicts"] = conflicts
    doc["options"]["near_critical_days"] = cfg.get("near_critical_days") or 10
    doc["settings"] = {
        "model": cfg.get("model") or RECOMMENDED_MODEL,
        "fallback_model": cfg.get("fallback_model") or FALLBACK_MODEL,
        "allow_ai": allow,
        "recommended_model": RECOMMENDED_MODEL,
    }
    _progress(progress, "cpm", "Calculating the critical path")
    cpm.schedule(doc)
    _release_dates(doc)
    _progress(progress, "rubric", "Checking completeness")
    rubric.evaluate(doc)
    _progress(progress, "health", "Checking schedule health")
    health.check(doc)
    narrative.render(doc)
    reviewq.queue(doc)
    _progress(progress, "done",
              "Schedule compiled" if doc["status"] == "finished"
              else "Schedule compiled with gaps")
    return doc


def _pages_from_sections(sections):
    pages = {}
    for sec in sections or ():
        for p in sec.get("pages") or []:
            pages.setdefault(p, [])
            pages[p].append(sec.get("text") or "")
    return [(n, "\n".join(pages[n])) for n in sorted(pages)]


def _holidays(ntp):
    start = as_date(ntp) or _dt.date.today()
    from .. import autoschedule
    return [d if isinstance(d, str) else d.isoformat()   # strings already
            for d in autoschedule.default_holidays(
        start, start + _dt.timedelta(days=366 * 3))]


def _default_ask(prompt, model):
    from ...ai.review import _ollama
    return _ollama(prompt, model=model, json_mode=True)


def _release_dates(doc):
    by_chain = {}
    for a in doc.get("activities") or ():
        if a.get("chain_id"):
            by_chain.setdefault(a["chain_id"], []).append(a)
    for fact in doc.get("facts") or []:
        if fact.get("kind") != "long_lead":
            continue
        item = (fact.get("item") or "").lower()
        for rows in by_chain.values():
            if any(item and item in (r.get("item") or "").lower() for r in rows):
                rel = next((r for r in rows if r.get("cls") == "release"), None)
                if rel:
                    fact["release_date"] = rel.get("es") or ""
