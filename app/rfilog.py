"""RFI and submittal log, kept inside the PDF (quantisheet_log.json), so it
travels with the drawings and with QuantiSheet's other job data.

Each item: number (RFI-001 / SUB-001), kind, title, question, answer, spec
section, sheet, page and linked markup, assigned to, ball in court,
status, dates sent / due / returned, cost and schedule impact, notes.
"""
import datetime
import json
import logging
import uuid

import fitz
from . import safecell
from . import embfiles

log = logging.getLogger(__name__)

FILE = "quantisheet_log.json"
KINDS = {"RFI": "RFI", "Submittal": "SUB"}
STATUSES = {
    "RFI": ["Draft", "Open", "Answered", "Closed"],
    "Submittal": ["Open", "Approved", "Approved as Noted",
                  "Revise & Resubmit", "Rejected", "Closed"],
}
CLOSED = {"Answered", "Closed", "Approved", "Approved as Noted", "Rejected"}
FIELDS = ("number", "kind", "title", "question", "answer", "spec", "sheet",
          "page", "markup", "assigned", "ball_in_court", "status", "sent",
          "due", "returned", "cost_impact", "schedule_impact", "notes",
          "created", "source")
COLUMNS = [("number", "No."), ("kind", "Type"), ("title", "Title"),
           ("sheet", "Sheet"), ("spec", "Spec"), ("assigned", "Assigned To"),
           ("ball_in_court", "Ball in Court"), ("status", "Status"),
           ("sent", "Sent"), ("due", "Due"), ("returned", "Returned"),
           ("cost_impact", "Cost Impact"),
           ("schedule_impact", "Schedule Impact")]


def read(doc):
    try:
        if FILE in doc.embfile_names():
            d = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(d, dict):
                d.setdefault("items", [])
                d.setdefault("next", {})
                return d
    except Exception:
        log.warning("could not read the RFI log", exc_info=True)
    return {"items": [], "next": {}}


def write(doc, data):
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    embfiles.put(doc, FILE, raw, "QuantiSheet RFI and submittal log")


def items(doc):
    return read(doc)["items"]


def _today():
    return datetime.date.today().isoformat()


def _clean(fields):
    out = {}
    for k in FIELDS:
        if k in fields:
            v = fields[k]
            if k == "page":
                try:
                    v = int(v) if v not in (None, "") else None
                except (TypeError, ValueError):
                    v = None
            elif k == "markup":
                v = v if isinstance(v, dict) else None
            else:
                # long questions/answers were cut at 4000 characters
                # without a word (nit); keep up to 50,000, log any cut
                cap = 50000 if k in ("question", "answer") else 4000
                v = "" if v is None else str(v)
                if len(v) > cap:
                    log.warning("RFI %s cut to %d characters", k, cap)
                    v = v[:cap]
            out[k] = v
    return out


def add(doc, kind="RFI", **fields):
    """A new numbered item. Returns it."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}")
    d = read(doc)
    n = int(d["next"].get(kind) or 0) + 1
    used = {it.get("number") for it in d["items"]}
    while f"{KINDS[kind]}-{n:03d}" in used:
        n += 1
    d["next"][kind] = n
    it = {k: "" for k in FIELDS}
    it.update({"id": uuid.uuid4().hex, "kind": kind, "page": None,
               "markup": None, "number": f"{KINDS[kind]}-{n:03d}",
               "status": STATUSES[kind][0] if kind == "Submittal"
               else "Open", "created": _today()})
    it.update(_clean(fields))
    it["kind"] = kind
    d["items"].append(it)
    write(doc, d)
    return it


def update(doc, item_id, **fields):
    d = read(doc)
    for it in d["items"]:
        if it.get("id") == item_id:
            it.update(_clean(fields))
            write(doc, d)
            return it
    return None


def delete(doc, item_id):
    d = read(doc)
    keep = [it for it in d["items"] if it.get("id") != item_id]
    if len(keep) == len(d["items"]):
        return False
    d["items"] = keep
    write(doc, d)
    return True


def is_open(it):
    return it.get("status") not in CLOSED


def days_open(it, today=None):
    try:
        start = datetime.date.fromisoformat(it.get("sent") or
                                            it.get("created"))
    except (TypeError, ValueError):
        return None
    end = today or datetime.date.today()
    if not is_open(it) and it.get("returned"):
        try:
            end = datetime.date.fromisoformat(it["returned"])
        except ValueError:
            pass
    return (end - start).days


def is_overdue(it, today=None):
    if not is_open(it) or not it.get("due"):
        return False
    try:
        due = datetime.date.fromisoformat(it["due"])
    except ValueError:
        return False
    return due < (today or datetime.date.today())


def from_markup(doc, pno, annot):
    """Fields for an RFI raised from a markup on page `pno`."""
    from . import annotate, sheets
    info = annot.info or {}
    text = (info.get("content") or "").strip()
    subj = info.get("subject") or ""
    if subj.startswith(annotate.TAKEOFF + ":"):
        subj = (subj.split(":", 5) + [""] * 6)[4]
    try:
        sheet = sheets.label_for(doc[pno])
    except Exception:
        sheet = ""
    title = (text.splitlines()[0] if text else subj or "Question")[:120]
    return {"title": title, "question": text, "sheet": sheet or
            f"Page {pno + 1}", "page": pno, "markup": annotate.ref(annot)}


# ---- exports -----------------------------------------------------------------

def _row(it, today=None):
    out = [it.get(k, "") or "" for k, _ in COLUMNS]
    d = days_open(it, today)
    out.append("" if d is None else str(d))
    out.append("Overdue" if is_overdue(it, today) else "")
    return out


def headers():
    return [h for _, h in COLUMNS] + ["Days Open", "Overdue"]


def export_csv(doc, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = safecell.writer(f)
        w.writerow(headers() + ["Question", "Answer", "Notes"])
        for it in items(doc):
            w.writerow(_row(it) + [it.get("question", ""),
                                   it.get("answer", ""), it.get("notes", "")])
    return path


def export_xlsx(doc, path):
    from . import acrobat
    rows = [headers() + ["Question", "Answer", "Notes"]]
    for it in items(doc):
        rows.append(_row(it) + [it.get("question", ""), it.get("answer", ""),
                                it.get("notes", "")])
    acrobat.write_xlsx(path, [("RFI & Submittal Log", rows)])
    return path


def export_pdf(doc, path, title="RFI & Submittal Log", project=""):
    from .forms import flow_text, write_box
    """A printable log: landscape tabloid table, then each item's
    question and answer."""
    out = fitz.open()
    W, H = 1224, 792                           # 17 x 11 in
    cols = [("No.", 70), ("Type", 60), ("Title", 260), ("Sheet", 150),
            ("Assigned", 110), ("Status", 100), ("Sent", 70), ("Due", 70),
            ("Returned", 70), ("Days", 40), ("Cost/Sched.", 120)]
    rows = []
    for it in items(doc):
        d = days_open(it)
        impact = " / ".join(x for x in (it.get("cost_impact"),
                                         it.get("schedule_impact")) if x)
        rows.append(([it.get("number", ""), it.get("kind", ""),
                      it.get("title", ""), it.get("sheet", ""),
                      it.get("assigned", ""), it.get("status", ""),
                      it.get("sent", ""), it.get("due", ""),
                      it.get("returned", ""), "" if d is None else str(d),
                      impact], is_overdue(it)))
    y, page = 0, None

    def new_page():
        p = out.new_page(width=W, height=H)
        p.insert_text((36, 44), title, fontsize=16, fontname="hebo")
        sub = f"{project}   " if project else ""
        p.insert_text((36, 62), f"{sub}Printed {_today()}   "
                      f"{len(rows)} item(s)", fontsize=9)
        x = 36
        for name, w in cols:
            p.draw_rect(fitz.Rect(x, 74, x + w, 90), color=(0, 0, 0),
                        fill=(0.85, 0.88, 0.95), width=0.5)
            write_box(p, (x + 3, 77, x + w - 2, 90), name, 8, True)
            x += w
        return p, 90
    page, y = new_page()
    for vals, overdue in rows:
        if y + 16 > H - 36:
            page, y = new_page()
        x = 36
        for (name, w), v in zip(cols, vals):
            page.draw_rect(fitz.Rect(x, y, x + w, y + 16), color=(0.6,) * 3,
                           fill=(1, 0.9, 0.9) if overdue else None, width=0.3)
            write_box(page, (x + 3, y + 3, x + w - 2, y + 16), str(v)[:60],
                      7.5)
            x += w
        y += 16
    # details
    for it in items(doc):
        if not (it.get("question") or it.get("answer")):
            continue
        if y + 120 > H - 36:
            page, y = out.new_page(width=W, height=H), 36
        y += 18
        page.insert_text((36, y), f"{it.get('number')}  {it.get('title')}",
                         fontsize=10, fontname="hebo")
        for label, key in (("Question", "question"), ("Answer", "answer")):
            text = it.get(key) or ""
            if not text:
                continue
            y += 6
            # the whole text, over as many pages as it needs (3b C11)
            page, y = flow_text(page, 36, W - 36, y, f"{label}: {text}",
                                8.5, lambda: (out.new_page(width=W,
                                                           height=H), 36),
                                H - 36)
    out.save(path)
    out.close()
    return path
