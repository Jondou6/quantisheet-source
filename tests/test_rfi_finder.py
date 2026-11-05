"""Review > AI: Find RFIs & Questions."""
import json
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, rfilog                            # noqa: E402
from app.ai import rfi_finder                               # noqa: E402
from test_gui import win, qapp                              # noqa: E402,F401


def _sheet(d, number, title, lines):
    p = d.new_page(width=612, height=792)
    y = 80
    for line in lines:
        p.insert_text((60, y), line, fontsize=10)
        y += 20
    p.insert_text((520, 740), title, fontsize=7)
    p.insert_text((520, 765), number, fontsize=16)
    return p


def make_plans(path=None):
    d = fitz.open()
    _sheet(d, "A-101", "FLOOR PLAN", [
        "SEE DETAIL 5/A-501 FOR DOOR HEAD",
        "DOOR HARDWARE PER SECTION 08 71 00",
        "FRAMES PER SECTION 08 11 13",
        "CEILING HEIGHT TBD",
        "CASEWORK BY OTHERS",
        "AHU-1 ON ROOF",
        "AHU-2 ABOVE CORRIDOR",
        "SEE 3/A-102 FOR WALL TYPES"])
    _sheet(d, "A-102", "WALL TYPES", ["WALL TYPE 1: 3-5/8 IN STUD"])
    _sheet(d, "M-601", "MECHANICAL SCHEDULE", [
        "EQUIPMENT SCHEDULE", "AHU-1  2000 CFM  208V"])
    if path:
        d.save(path)
    return d


def make_specs(path):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), "SECTION 08 11 13 - HOLLOW METAL DOORS AND "
                  "FRAMES", fontsize=10)
    p.insert_text((72, 100), "PART 1 GENERAL", fontsize=10)
    d.save(path)
    return d


def stub(reply_items):
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return json.dumps({"items": reply_items})
    ask.calls = calls
    return ask


def test_rule_checks(tmp_path):
    plans = rfi_finder.gather(make_plans())
    specs = rfi_finder.gather(make_specs(str(tmp_path / "s.pdf")), "specs")
    assert [p[1] for p in plans] == ["A-101", "A-102", "M-601"]
    found = rfi_finder.checks(plans, specs)
    qs = " | ".join(f["question"] for f in found)
    assert "5/A-501" in qs and "sheet A-501 is not in" in qs
    assert "3/A-102" not in qs                     # that sheet exists
    assert "Section 08 71 00" in qs
    assert "08 11 13" not in qs                    # that one is in the book
    assert "AHU-2" in qs and "AHU-1" not in qs
    assert "TBD" in qs and "BY OTHERS" in qs
    assert all(f["source"] == "check" and f["page"] == 0 for f in found)


def test_ai_review_with_stub_model():
    plans = rfi_finder.gather(make_plans())
    ask = stub([{"question": "Confirm ceiling height in corridor?",
                 "reason": "Height is TBD", "reference": "A-101",
                 "page": 1, "quote": "CEILING HEIGHT TBD"},
                {"question": "", "page": 1}])
    out = rfi_finder.ai_review(plans, ask=ask)
    assert len(out) == 1 and out[0]["page"] == 0 and out[0]["source"] == "AI"
    assert "[Page 1] Sheet A-101" in ask.calls[0]


def test_locate_quote():
    d = make_plans()
    pg, r = rfi_finder.locate(d, {"page": 0, "quote": "CASEWORK BY OTHERS"})
    assert pg == 0 and r is not None and r.width > 50
    pg, r = rfi_finder.locate(d, {"page": 2, "quote": "nowhere to be found"})
    assert pg == 2 and r is None


def test_find_rfis_in_the_app(win, tmp_path):
    plans_path = str(tmp_path / "plans.pdf")
    make_plans(plans_path)
    specs_path = str(tmp_path / "specs.pdf")
    make_specs(specs_path)
    assert win.open_path(plans_path)
    shown = {}

    class Fake:
        def __init__(self, items, note):
            shown["items"], shown["note"] = items, note

        def exec(self):
            return 1

        def selected(self):
            return [dict(f, question=f["question"]) for f in shown["items"]]

    ask = stub([{"question": "Is the AHU-2 location coordinated with the "
                 "corridor ceiling?", "reason": "Clearance",
                 "reference": "A-101", "page": 1,
                 "quote": "AHU-2 ABOVE CORRIDOR"}])
    rfis = win.ai_find_rfis(spec_path=specs_path, ask=ask, wait=True,
                            dialog=Fake)
    # TBD + BY OTHERS notes are one open-scope item now (NW-19)
    assert len(rfis) == len(shown["items"]) >= 4
    log = rfilog.items(win._view.doc)
    assert [x["number"] for x in log][:2] == ["RFI-001", "RFI-002"]
    assert all(x["status"] == "Draft" for x in log)
    # v36: drawing findings come from rules; the model is never asked
    assert all(x["source"] == "Check" for x in log) and not ask.calls
    assert "Cost impact: TBD" in log[0]["question"]
    linked = [x for x in log if x["markup"]]
    assert linked                                  # clouds at the quotes
    v = win._view
    clouds = [a for a in v.doc[0].annots()
              if (a.info or {}).get("subject") == "RFI"]
    assert len(clouds) == len(linked)
    assert win.rfis.table.rowCount() == len(log)


def test_finding_needs_no_model(win, tmp_path):
    path = str(tmp_path / "plans.pdf")
    make_plans(path)
    assert win.open_path(path)
    seen = {}

    class Fake:
        def __init__(self, items, note):
            seen["n"], seen["note"] = len(items), note

        def exec(self):
            return 0

    def broken(prompt):
        raise RuntimeError("Can't reach Ollama")
    win.ai_find_rfis(spec_path="", ask=broken, wait=True, dialog=Fake)
    assert seen["n"] >= 3 and seen["note"] == ""      # NW-19 grouping


def make_spec_book(path):
    d = fitz.open()
    pages = [
        ["SECTION 01 21 00 - ALLOWANCES", "PART 1 - GENERAL",
         "Include a contingency allowance of $TBD for unforeseen work.",
         "Testing allowance: see Section 01 45 00."],
        ["SECTION 08 11 13 - HOLLOW METAL DOORS AND FRAMES",
         "PART 1 - GENERAL", "Hardware per Section 08 71 00.",
         "Basis of design: Manufacturer to be determined."],
        ["SECTION 09 29 00 - GYPSUM BOARD", "PART 1 - GENERAL",
         "Coordinate with Section 08 11 13.", "Patching by others."],
    ]
    for lines in pages:
        p = d.new_page()
        y = 72
        for ln in lines:
            p.insert_text((72, y), ln, fontsize=10)
            y += 18
    d.save(path)
    return d


def test_spec_book_detected_and_checked(tmp_path):
    book = rfi_finder.gather(make_spec_book(str(tmp_path / "s.pdf")))
    assert rfi_finder.is_spec_book(book)
    assert not rfi_finder.is_spec_book(rfi_finder.gather(make_plans()))
    found = rfi_finder.spec_checks(book)
    refs = {f["reference"] for f in found}
    assert refs == {"Section 01 45 00", "Section 08 71 00"}   # 08 11 13 is in
    assert all(f["doc"] == "specs" for f in found)


def test_find_rfis_with_a_spec_book_open(win, tmp_path):
    path = str(tmp_path / "Project Manual.pdf")
    make_spec_book(path)
    assert win.open_path(path)
    shown = {}

    class Fake:
        def __init__(self, items, note):
            shown["items"], shown["note"] = items, note

        def exec(self):
            return 1

        def selected(self):
            return list(shown["items"])

    ask = stub([{"question": "Who is the hardware manufacturer?",
                 "reason": "Can't price hardware", "reference": "08 11 13",
                 "page": 2, "quote": "Manufacturer to be determined"}])
    rfis = win.ai_find_rfis(ask=ask, wait=True, dialog=Fake)
    assert ask.calls and "SPECIFICATIONS:" in ask.calls[0]
    assert "Project manual" in rfi_finder.SPEC_PROMPT or \
        "project manual" in rfi_finder.SPEC_PROMPT
    assert "all 3 pages" in shown["note"] and "every page" in shown["note"]
    qs = " ".join(f["question"] for f in shown["items"])
    assert "08 71 00" in qs and "01 45 00" in qs        # missing sections
    assert "TBD" in qs or "to be determined" in qs.lower()
    assert "hardware manufacturer" in qs                # the AI's finding
    assert len(rfis) == len(shown["items"])
    clouds = [a for p in win._view.doc for a in p.annots()
              if (a.info or {}).get("subject") == "RFI"]
    assert clouds                                       # marked in the spec
