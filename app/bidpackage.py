"""Bid Package (Nov 17): everything for one bid in one folder and one zip,
from one command (Estimate > Export Bid Package...).

    <folder>/<yyyy.mm.dd Project Bid Package>/
        ... Proposal.pdf             the client proposal (saved details)
        ... Estimate Summary.pdf     totals by CSI division and cost type
        ... Estimate Summary.xlsx
        ... Estimate Detail.csv      every takeoff line, with its pages
        ... Takeoff Sheets.pdf       the sheets that carry takeoff, with
                                     the measurements on them
        ... Estimate Workbook.xlsx   by division, rates blank (only after
                                     AI Takeoff ran in this session)
        ... Contents.txt             what is in the package and what still
                                     needs a look (unpriced lines, AI items
                                     not checked, an unlocked bid)
    <folder>/<same name>.zip         the folder zipped, to send

A part that can't be made is listed in Contents.txt with the reason; the
rest of the package is still made. Nothing is sent anywhere: the folder
and the zip are written where the person picked. File names follow the
company rule (reportname.py). No Qt here.
"""
import logging
import os
import zipfile

from . import reportname

log = logging.getLogger(__name__)

PARTS = ("proposal", "summary_pdf", "summary_xlsx", "detail_csv",
         "sheets_pdf", "workbook", "contents")
LABEL = {"proposal": "Proposal", "summary_pdf": "Estimate Summary",
         "summary_xlsx": "Estimate Summary", "detail_csv": "Estimate Detail",
         "sheets_pdf": "Takeoff Sheets", "workbook": "Estimate Workbook",
         "contents": "Contents"}
EXT = {"proposal": ".pdf", "summary_pdf": ".pdf", "summary_xlsx": ".xlsx",
       "detail_csv": ".csv", "sheets_pdf": ".pdf", "workbook": ".xlsx",
       "contents": ".txt"}


def project_of(doc):
    from . import proposal
    try:
        p = (proposal.read(doc) or {}).get("project") or ""
    except Exception:                                     # noqa: BLE001
        p = ""
    if not p:
        name = getattr(doc, "name", "") or ""
        p = os.path.splitext(os.path.basename(name))[0] if name else ""
    return p or "Project"


def takeoff_pages(doc):
    """0-based pages that carry takeoff (measurements, set quantities or
    AI quantities worked out on that sheet), in order."""
    from . import annotate, ai_quantities, estimate
    pages = set()
    try:
        pages |= {it["page"] for it in annotate.totals_items(doc)}
    except Exception:                                     # noqa: BLE001
        log.info("takeoff pages", exc_info=True)
    pages |= {it["page"] for it in estimate.set_items(doc)}
    pages |= {r["page"] for r in ai_quantities.rows(doc)
              if r["page"] is not None}
    n = getattr(doc, "page_count", 0) or 0
    return sorted(p for p in pages if isinstance(p, int) and 0 <= p < n)


def sheets_pdf(doc, path):
    """The takeoff sheets, measurements and all, as one PDF; returns how
    many sheets (0: nothing written)."""
    import fitz
    pages = takeoff_pages(doc)
    if not pages:
        return 0
    out = fitz.open()
    try:
        for p in pages:
            out.insert_pdf(doc, from_page=p, to_page=p, annots=True)
        out.save(path, garbage=3, deflate=True)
    finally:
        out.close()
    return len(pages)


def checks(doc, ai_result=None):
    """What still needs a look before the bid goes: [text]."""
    from . import annotate, estimate_export, prebid
    out = []
    try:
        lk = prebid.lock_state(doc)
        if not lk:
            out.append("The bid isn't locked (Estimate > Pre-bid "
                       "Checklist): numbers may still change.")
        elif isinstance(lk, dict) and lk.get("stale"):
            out.append("The takeoff changed after the bid was locked - "
                       "check the numbers and lock it again.")
    except Exception:                                     # noqa: BLE001
        log.info("lock state", exc_info=True)
    try:
        un = estimate_export.unpriced(doc)
        if un:
            out.append(f"{len(un)} takeoff line(s) have a quantity but no "
                       "price - listed in the summary, not in any total: " +
                       "; ".join(str(u.get("desc") or "")[:40]
                                 for u in un[:5]))
    except Exception:                                     # noqa: BLE001
        log.info("unpriced", exc_info=True)
    try:
        pend = [it for it in annotate.takeoff_items(doc)
                if it.get("pending")]
        if pend:
            out.append(f"{len(pend)} AI measurement(s) not checked yet - "
                       "they are in no total (Check Takeoff).")
    except Exception:                                     # noqa: BLE001
        log.info("pending", exc_info=True)
    if ai_result:
        from . import review
        try:
            left = review.counts(ai_result)["left"]
            if left:
                out.append(f"{left} AI Takeoff CHECK item(s) still to "
                           "review (AI Takeoff > Review).")
        except Exception:                                 # noqa: BLE001
            log.info("review counts", exc_info=True)
    return out


def file_name(part, project, when=None):
    return reportname.report_file_name(LABEL[part], project, when=when,
                                       ext=EXT[part])


def make(doc, folder, when=None, parts=PARTS, comp=None, ai_rows=None,
         ai_result=None):
    """Write the package into a new folder under `folder` and zip it.
    Returns {"folder", "zip", "files": [(part, path)], "skipped":
    [(part, why)], "checks": [text]}."""
    project = project_of(doc)
    base = reportname.report_file_name("Bid Package", project, when=when,
                                       ext="")
    root = os.path.join(folder, base)
    k = 2
    while os.path.exists(root) or os.path.exists(root + ".zip"):
        root = os.path.join(folder, f"{base} ({k})")
        k += 1
    os.makedirs(root)
    files, skipped = [], []

    def where(part):
        return os.path.join(root, file_name(part, project, when))

    def do(part, fn):
        if part not in parts:
            return
        path = where(part)
        try:
            r = fn(path)
        except Exception as e:                            # noqa: BLE001
            log.warning("bid package: %s", part, exc_info=True)
            skipped.append((part, f"couldn't be made ({e})"))
            return
        if r is False or r == 0 or not os.path.isfile(path):
            skipped.append((part, r if isinstance(r, str) else
                            "nothing to put in it"))
            return
        files.append((part, path))

    def proposal_pdf(path):
        from . import proposal
        out = proposal.make_pdf(doc, proposal.read(doc), comp)
        try:
            out.save(path, garbage=3, deflate=True)
        finally:
            out.close()
        return True

    def summary_pdf(path):
        from . import estimate_export
        estimate_export.save_pdf(doc, path)
        return True

    def summary_xlsx(path):
        from . import estimate_export
        estimate_export.save_xlsx(doc, path)
        return True

    def detail_csv(path):
        from . import estimate
        estimate.export_csv(doc, path)
        return True

    def workbook(path):
        if not ai_result:
            return 0
        from . import estimate_book
        lines = estimate_book.collect(ai_rows or [], ai_result)
        if not lines:
            return 0
        gsf = next((q["qty"] for q in ai_result.get("quantities") or ()
                    if q.get("name") == "Gross floor area"), None)
        estimate_book.write(path, lines, project=project, gsf=gsf)
        return True

    do("proposal", proposal_pdf)
    do("summary_pdf", summary_pdf)
    do("summary_xlsx", summary_xlsx)
    do("detail_csv", detail_csv)
    do("sheets_pdf", lambda p: sheets_pdf(doc, p))
    if "workbook" in parts and not ai_result:
        skipped.append(("workbook", "run AI Takeoff first (made from its "
                                    "result)"))
    else:
        do("workbook", workbook)
    notes = checks(doc, ai_result)
    if "contents" in parts:
        path = where("contents")
        with open(path, "w", encoding="utf-8") as f:
            f.write(contents_text(project, files, skipped, notes, when))
        files.append(("contents", path))
    zpath = root + ".zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for _part, p in files:
            z.write(p, os.path.join(os.path.basename(root),
                                    os.path.basename(p)))
    return {"folder": root, "zip": zpath, "files": files,
            "skipped": skipped, "checks": notes}


def contents_text(project, files, skipped, notes, when=None):
    lines = [f"Bid package - {project}",
             f"Made {reportname.stamp(when)}", "", "In this package:"]
    lines += [f"  {os.path.basename(p)}" for _part, p in files]
    lines.append(f"  {file_name('contents', project, when)}")
    if skipped:
        lines += ["", "Not included:"]
        lines += [f"  {LABEL[part]}: {why}" for part, why in skipped]
    lines += ["", "Before you send it:"]
    lines += [f"  - {n}" for n in notes] or ["  - Nothing flagged."]
    return "\n".join(lines) + "\n"


BOARD_MATCH = 0.8      # how alike the project names must be


def board_match(project, items=None):
    """The Bid Board opportunity this package is for (Nov 17): one still
    open or accepted whose project name is alike, or None. Two that fit
    equally well: None (the person marks it by hand)."""
    from . import bidboard
    try:
        items = bidboard.load() if items is None else items
    except Exception:                                     # noqa: BLE001
        log.info("bid board", exc_info=True)
        return None
    fits = []
    for o in items:
        if o.get("status") not in bidboard.OPEN:
            continue
        a = bidboard._alike(project, o.get("project"))
        if a >= BOARD_MATCH:
            fits.append((a, o))
    fits.sort(key=lambda t: -t[0])
    if not fits or (len(fits) > 1 and fits[1][0] == fits[0][0]):
        return None
    return fits[0][1]


def mark_submitted(o, package):
    """Mark the opportunity Submitted, noting the package's folder name."""
    from . import bidboard
    note = (o.get("notes") or "").rstrip()
    line = f"Bid package: {os.path.basename(package['folder'])}"
    o = dict(o, notes=(note + "\n" if note else "") + line)
    bidboard.save(o)
    return bidboard.set_status(o["id"], "Submitted")
