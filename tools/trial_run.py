"""Timed trial of QuantiSheet's features on a real document.

    python tools/trial_run.py <file.pdf> [report.txt]

Works on a copy in trial_output/, never the original.
"""
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz                                        # noqa: E402
from app import (acrobat, acrobat2, annotate, rules, history,   # noqa: E402
                 page_ops)

SRC = sys.argv[1].strip('"')
REPORT = sys.argv[2].strip('"') if len(sys.argv) > 2 else "trial-report.txt"
OUT = os.path.join(os.path.dirname(os.path.abspath(REPORT)), "trial_output")
os.makedirs(OUT, exist_ok=True)
lines = []


def log(msg):
    print(msg, flush=True)
    lines.append(msg)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def step(name, fn):
    t = time.perf_counter()
    try:
        result = fn()
        log(f"[{time.perf_counter() - t:7.2f}s] OK    {name}: {result}")
        return result
    except Exception as e:
        log(f"[{time.perf_counter() - t:7.2f}s] FAIL  {name}: {e}")
        log("        " + traceback.format_exc().replace("\n", "\n        "))
        return None


log(f"Trial on {os.path.basename(SRC)} ({os.path.getsize(SRC) / 1e6:.1f} MB)")
doc = step("open", lambda: fitz.open(SRC))
step("pages", lambda: doc.page_count)
step("bookmarks", lambda: len(doc.get_toc()))
step("pages with no text (need OCR)",
     lambda: len(acrobat.pages_needing_ocr(doc)))
step("page sizes", lambda: sorted({(round(p.rect.width), round(p.rect.height))
                                    for p in doc})[:6])

# viewing
step("render page 1 at 150% (view)",
     lambda: doc[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).width)
step("render all thumbnails (120px)",
     lambda: sum(1 for p in doc for _ in [p.get_pixmap(
         matrix=fitz.Matrix(120 / p.rect.width, 120 / p.rect.width))]))

# search
for term in ("shall", "fire rating", "submittal", "warranty"):
    step(f"search '{term}'",
         lambda term=term: sum(len(p.search_for(term)) for p in doc))

# spec section headings
import re                                           # noqa: E402
sec = re.compile(r"^\s*SECTION\s+(\d{2}\s?\d{2}\s?\d{2}(?:\.\d+)?)\s*[-–—]?\s*(.*)$",
                 re.I | re.M)


def sections():
    found = []
    for i, p in enumerate(doc):
        m = sec.search(p.get_text()[:600])
        if m:
            found.append((i + 1, m.group(1), m.group(2).strip()[:50]))
    return f"{len(found)} e.g. {found[:5]}"


step("spec sections found (SECTION xx xx xx)", sections)

# undo snapshot cost
step("doc.tobytes() (undo snapshot)", lambda: f"{len(doc.tobytes()) / 1e6:.1f} MB")
h = step("History() init", lambda: history.History(lambda: doc.tobytes()))

# auto-markup on the whole book
marks = step("auto-markup: find marks (default rules)",
             lambda: rules.find_marks(doc))
if marks:
    log(f"        marks by kind: " + str({k: sum(1 for m in marks if m[1] == k)
                                           for k in {m[1] for m in marks}}))
    step("auto-markup: apply all marks", lambda: sum(
        annotate.apply_op(doc, annotate.new_op(k, p, **pl))
        for p, k, pl in marks))
step("Markups List refresh (markup_items)",
     lambda: len(annotate.markup_items(doc)))
step("Quantities refresh (takeoff_items)",
     lambda: len(annotate.takeoff_items(doc)))
step("undo snapshot after markup", lambda: (h.snapshot(), len(h.stack))[1])

# page-level undo, as used for markups in the app
with open(SRC, "rb") as _fh:
    _initial = _fh.read()
h2 = history.History(lambda: doc.tobytes(), initial=_initial)


def markup_step():
    before = h2.begin_pages(doc, [5])
    annotate.apply_op(doc, annotate.new_op("add_cloud", 5,
                                           rect=[100, 100, 300, 200]))
    h2.commit_pages(doc, before)
    return h2.stack[-1][0]


step("markup + record undo (page-level)", markup_step)
step("undo markup (in place)", lambda: h2.undo(doc))
step("redo markup (in place)", lambda: h2.redo(doc))
step("page op + full snapshot", lambda: (doc[3].set_rotation(90),
                                         h2.snapshot(), len(h2.stack))[2])
step("undo page op (rebuild)", lambda: f"{len(h2.undo(doc)) / 1e6:.1f} MB")
doc[3].set_rotation(0)

# redaction search
for name in ("Phone numbers", "Email addresses"):
    step(f"redaction search: {name}", lambda name=name: len(
        acrobat.find_for_redaction(doc, pattern=acrobat.PATTERNS[name])))

# exports and page tools on a fresh copy
fresh = fitz.open(SRC)
step("split every 100 pages", lambda: len(acrobat2.split(
    fresh, os.path.join(OUT, "split"), every=100, base="spec")))
step("export text", lambda: os.path.getsize(
    acrobat.export_text(fresh, os.path.join(OUT, "spec.txt"))))
step("export Word (.docx)", lambda: os.path.getsize(
    acrobat.export_word(fresh, os.path.join(OUT, "spec.docx"))))
step("export Excel (.xlsx)", lambda: acrobat.export_excel(
    fresh, os.path.join(OUT, "spec.xlsx")))
step("page numbers + Bates", lambda: (
    acrobat.header_footer(fresh, {"bottom_right": "Page {page} of {pages}"}),
    page_ops.bates_number(fresh, "AIKEN-", 1))[1])
step("reduce file size", lambda: f"{acrobat.reduce_size(fitz.open(SRC), os.path.join(OUT, 'spec_small.pdf')) / 1e6:.1f} MB")
for g in (1, 2):
    step(f"save marked-up copy (garbage={g})", lambda g=g: (doc.save(
        os.path.join(OUT, f"spec_marked{g}.pdf"), garbage=g, deflate=True),
        "saved")[1])
step("xref objects", lambda: doc.xref_length())
log("DONE")
