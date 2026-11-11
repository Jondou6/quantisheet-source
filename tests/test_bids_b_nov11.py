"""Nov 11, bidding phase B1: every value read from a sub's proposal says
where it is in the file, and the windows can show it. Made-up quotes
only."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import proposal_level as pl, settings                   # noqa: E402

LINES = [
    "EXAMPLE PIPE INC", "PROPOSAL", "Project: Sample Plant - Yard Piping",
    "1   8\" PVC SDR-35 sewer   1,200 LF   $45.00   $54,000.00",
    "2   48\" precast manhole   6 EA   $4,200.00   $25,200.00",
    "3   Bypass pumping   Lump Sum   $12,000.00",
    "Total Base Bid: $91,200.00",
    "Alternate 1: Add rock excavation $8,500.00",
    "Extra work at $95.00 per hour",
    "Exclusions:", "- Permits and fees", "- Testing",
    "Excludes: winter protection, bonds",
    "Inclusions:", "- Traffic control"]


def _pdf(path, lines, pages=1, rotate=0):
    d = fitz.open()
    for k in range(pages):
        pg = d.new_page(width=612, height=792)
        y = 60
        for ln in (lines if k == pages - 1 else ["Page 1 of 2"]):
            pg.insert_text((50, y), ln, fontsize=10)
            y += 16
        if rotate:
            pg.set_rotation(rotate)
    d.save(str(path))
    return str(path)


@pytest.fixture
def quote(tmp_path):
    return _pdf(tmp_path / "Example quote.pdf", LINES, pages=2)


def _words(src):
    from app import source_view
    return source_view.words_at(src)


def test_every_value_has_a_page_and_a_rectangle(quote):
    p = pl.parse(quote)
    assert p["path"] == os.path.abspath(quote)
    assert len(p["lines"]) == 3
    for r in p["lines"]:
        for k in ("src", "src_amount"):
            assert r[k]["page"] == 1 and len(r[k]["rect"]) == 4, r
    S = p["sources"]
    assert len(S["exclusions"]) == len(p["exclusions"]) == 4
    assert len(S["inclusions"]) == len(p["inclusions"]) == 1
    assert len(S["alternates"]) == len(p["alternates"]) == 1
    assert len(S["unread"]) == len(p["unread"]) == 1
    every = [S["bidder"], S["total"]] + S["exclusions"] + S["inclusions"] \
        + S["alternates"] + S["unread"]
    assert all(s and s["page"] == 1 and s["rect"][2] > s["rect"][0]
               for s in every)


def test_the_rectangle_is_on_the_right_words(quote):
    p = pl.parse(quote)
    assert _words(pl.source_of(p, "amount", 0)) == "$54,000.00"
    assert _words(pl.source_of(p, "amount", '48" precast manhole')) == \
        "$25,200.00"
    assert _words(pl.source_of(p, "line", 2)).startswith("3 Bypass pumping")
    assert _words(pl.source_of(p, "total", None)) == "$91,200.00"
    assert _words(pl.source_of(p, "bidder", None)) == "EXAMPLE PIPE INC"
    assert _words(pl.source_of(p, "exclusion", "Permits and fees")) == \
        "- Permits and fees"
    # two exclusions on one line: each its own words
    assert _words(pl.source_of(p, "exclusion", "winter protection")) == \
        "winter protection,"
    assert _words(pl.source_of(p, "exclusion", "bonds")) == "bonds"
    assert _words(pl.source_of(p, "inclusion", "traffic control")) == \
        "- Traffic control"
    assert pl.source_of(p, "exclusion", "not in the quote") is None


def test_typed_lines_have_no_place_and_say_so(tmp_path):
    p = pl.parse(str(tmp_path / "typed.pdf"), lines=[
        "Example Co", "Paint LS $900.00", "Total $900.00"])
    assert p["lines"][0]["src"] is None
    assert pl.source_of(p, "amount", 0) is None
    from app import source_view
    assert "no place" in source_view.problem(None)
    assert "isn't where it was" in source_view.problem(
        {"file": str(tmp_path / "gone.pdf"), "page": 0, "rect": [0, 0, 1, 1]})


def test_a_scan_gets_places_from_the_ocr_words(tmp_path, monkeypatch):
    from app import ocr
    d = fitz.open()
    d.new_page()
    path = str(tmp_path / "scan.pdf")
    d.save(path)

    def lines(page):
        def row(y, *ws):
            x, out = 50.0, []
            for w in ws:
                out.append((w, (x, y, x + 6.0 * len(w), y + 10)))
                x += 6.0 * len(w) + 5
            return {"text": " ".join(ws), "words": out}
        return [row(60, "Sample", "Drywall"),
                row(80, "Gypsum", "board", "walls", "1,000", "SF", "$2.20",
                    "$2,200.00"),
                row(100, "Total", "$2,200.00"),
                row(120, "Excludes:", "permits")]
    monkeypatch.setattr(ocr, "ocr_page_lines", lines)
    p = pl.parse(path)
    assert p["ocr"] == "used" and p["bidder"] == "Sample Drywall"
    r = p["lines"][0]
    assert r["amount"] == 2200.0
    assert r["src_amount"]["rect"][1] == 80 and r["src_amount"]["rect"][0] > \
        r["src"]["rect"][0]
    assert p["sources"]["exclusions"][0]["rect"][1] == 120


def test_ocr_text_without_boxes_still_reads(tmp_path, monkeypatch):
    from app import ocr
    d = fitz.open()
    d.new_page()
    path = str(tmp_path / "scan.pdf")
    d.save(path)
    monkeypatch.setattr(ocr, "ocr_page_lines", lambda page: [])
    monkeypatch.setattr(ocr, "ocr_page", lambda page: (
        "Sample Drywall\nGypsum board walls 1,000 SF $2.20 $2,200.00\n"))
    p = pl.parse(path)
    assert p["lines"][0]["amount"] == 2200.0 and p["lines"][0]["src"] is None


def test_scope_sheet_rows_carry_their_source(quote):
    from app.pm import scope_sheet as ss
    p = pl.parse(quote)
    rows = ss.rows_from_proposal(p)
    assert [r["text"] for r in rows][:2] == ["Permits and fees", "Testing"]
    assert all(r["src"]["file"] == p["path"] and r["src"]["page"] == 1
               for r in rows)
    sh = ss.new_sheet("33", "Utilities", bidders=1)
    sh["bidders"][0]["clar"] = rows
    back = ss.from_dict(ss.to_dict(sh))
    assert back["bidders"][0]["clar"][0]["src"] == rows[0]["src"]
    assert "src" not in ss.content(sh)["bidders"][0]["clar"][0]
    # an old row (no source) opens as before
    old = ss.from_dict({"bidders": [{"clar": [{"text": "x", "src": "bad"}]}]})
    assert "src" not in old["bidders"][0]["clar"][0]


@pytest.fixture
def app_(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    said = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(
        lambda *a, **k: said.append(a[2]) or 0))
    QApplication.instance() or QApplication([])
    return said


def test_source_window_boxes_the_words(quote, app_):
    from app import source_view
    p = pl.parse(quote)
    src = pl.source_of(p, "amount", 0)
    img, box = source_view.render(src)
    assert img.width() == 1224 and img.height() == 1584
    # the box is where the amount is drawn: dark ink inside it
    x, y = int(box.center().x()), int(box.center().y())
    dark = sum(1 for dx in range(-40, 41, 2) for dy in range(-6, 7, 2)
               if img.pixelColor(x + dx, y + dy).lightness() < 128)
    assert dark > 5
    dlg = source_view.show(None, src, "amount", modal=False)
    assert dlg is not None and "page 2" in dlg.findChildren(
        type(dlg.label))[0].text()
    dlg.close()
    assert source_view.show(None, None) is None and "no place" in app_[-1]


def test_source_on_a_rotated_page(tmp_path, app_):
    from app import source_view
    path = _pdf(tmp_path / "rot.pdf", LINES, rotate=90)
    p = pl.parse(path)
    src = pl.source_of(p, "amount", 0)
    assert _words(src) == "$54,000.00"
    img, box = source_view.render(src)
    assert img.width() == 1584                    # shown turned
    assert 0 <= box.left() and box.right() <= img.width() and \
        0 <= box.top() and box.bottom() <= img.height()
    assert box.height() > box.width()             # the words run upward


def test_leveling_window_shows_the_source(tmp_path, app_):
    from app import leveling_ui
    a = _pdf(tmp_path / "a.pdf", LINES)
    b = _pdf(tmp_path / "b.pdf", [
        "SAMPLE UTILITIES LLC", "Quotation",
        "8 inch PVC SDR-35 sewer 1200 LF $41.50 $49,800.00",
        "48 inch precast manhole 6 EA $3,900.00 $23,400.00",
        "TOTAL $73,200.00", "Excludes: bypass pumping, permits"])
    w = leveling_ui.LevelingDialog()
    assert w.use_proposals([a, b])
    s = w.source_of("SAMPLE UTILITIES LLC", "amount", '8" PVC SDR-35 sewer')
    assert s["file"] == os.path.abspath(b) and _words(s) == "$49,800.00"
    s = w.source_of("SAMPLE UTILITIES LLC", "exclusion", "permits")
    assert _words(s) == "permits"
    assert w.source_of("Nobody", "amount", "x") is None
    dlg = w.show_source("EXAMPLE PIPE INC", "exclusion", "Testing",
                        modal=False)
    assert dlg is not None
    dlg.close()


def test_leveling_board_keeps_and_shows_the_source(tmp_path, app_,
                                                   monkeypatch):
    from app import estimate
    from app.estimating import bidday, levelboard as LB, levelboard_ui
    monkeypatch.setattr(estimate, "lines", lambda d, page=None: [
        {"name": "8 in PVC SDR-35 sewer", "unit": "lf", "type": "length",
         "quantity": 1200, "code": "33 31 00", "unit_cost": 40.0}])
    doc = fitz.open()
    doc.new_page()
    w = levelboard_ui.LevelBoard(doc)
    w.new_from_trade("33", ask=False)
    q = _pdf(tmp_path / "q.pdf", LINES)
    assert w.add_quote(q)
    pkg = w.package()
    s = LB.source_of(doc, pkg, "EXAMPLE PIPE INC", row_id="1")
    assert s["file"] == os.path.abspath(q) and _words(s) == "$54,000.00"
    s = LB.source_of(doc, pkg, "EXAMPLE PIPE INC", exclusion="testing")
    assert _words(s) == "- Testing"
    LB.set_status(doc, pkg, "EXAMPLE PIPE INC", "1", LB.YELLOW)  # rebuilt
    assert LB.source_of(doc, pkg, "EXAMPLE PIPE INC", row_id="1")
    assert LB.source_of(doc, pkg, "Nobody", row_id="1") is None
    os.rename(q, q + ".moved")
    assert w.show_source("EXAMPLE PIPE INC", row_id="1") is None
    assert "isn't where it was" in app_[-1]
    assert bidday.load(doc, pkg)["bidders"][0]["file"]


# ---- B2: Read with AI --------------------------------------------------------

MESSY = [
    "SAMPLE MECHANICAL CO", "Proposal",
    "Furnish and install rooftop units per plans .......... $48,250.00",
    "Ductwork complete, 3,400 LB at $6.50/LB ............ $22,100.00",
    "Controls by our sub (lump) - 9,800.00",
    "We exclude: roof curbs; temporary heat",
    "This price includes start-up and one year of service",
    "Our price for the above: $80,150.00"]


def _answer(extra_lines=(), **kw):
    import json
    a = {"lines": [
        {"row": 2, "desc": "Furnish and install rooftop units per plans",
         "amount": 48250.00},
        {"row": 3, "desc": "Ductwork complete", "qty": 3400, "unit": "LB",
         "unit_price": 6.50, "amount": 22100.00},
        {"row": 4, "desc": "Controls by our sub", "amount": 9800}] +
        list(extra_lines),
        "total": {"row": 7, "amount": 80150.00},
        "exclusions": [{"row": 5, "text": "roof curbs"},
                       {"row": 5, "text": "temporary heat"}],
        "inclusions": [{"row": 6, "text": "start-up"}]}
    a.update(kw)
    return json.dumps(a)


@pytest.fixture
def messy(tmp_path):
    return _pdf(tmp_path / "messy.pdf", MESSY)


def test_patterns_leave_it_unread_and_ai_is_offered(messy):
    from app import proposal_ai as ai
    p = pl.parse(messy)
    assert not p["lines"] and p["unread"] and ai.needs_ai(p)
    assert not ai.needs_ai(pl.parse(messy, lines=[
        "Example Co", "Paint LS $900.00", "Total $900.00"]))
    pr = ai.prompt_for(pl.located_lines(messy))
    assert "[2] Furnish and install rooftop units" in pr


def test_ai_values_must_be_in_the_quote_word_for_word(messy):
    from app import proposal_ai as ai
    p = pl.parse(messy)
    got = ai.read(p, ask=lambda prompt: _answer(
        extra_lines=[{"row": 4, "desc": "Test and balance",
                      "amount": 3500.00},                  # made up
                     {"row": 9, "desc": "Ductwork complete",
                      "amount": 22100.00}],                # wrong row: found
        exclusions=[{"row": 5, "text": "roof curbs"},
                    {"row": 5, "text": "permits and fees"},  # made up
                    {"row": 1, "text": "temporary heat"}]))
    kinds = [o["kind"] for o in got["offers"]]
    assert kinds.count("line") == 3 and kinds.count("total") == 1
    assert kinds.count("exclusion") == 2 and kinds.count("inclusion") == 1
    why = {what: w for _k, what, w in got["rejected"]}
    assert any("3,500.00" in k for k in why) and \
        "permits and fees" in why
    assert "thrown out" in got["note"]
    # every offer has its place, on the right words
    for o in got["offers"]:
        src = dict(o.get("src_amount") or o["src"], file=p["path"])
        words = _words(src)
        if o["kind"] in ("line", "total"):
            assert f"{o['amount']:,.2f}" in words, (o, words)
        elif o["kind"] != "alternate":
            assert pl._alnum(o["text"]) in pl._alnum(words)
    duct = next(o for o in got["offers"] if o.get("desc", "").startswith(
        "Ductwork"))
    assert (duct["qty"], duct["unit"], duct["price"]) == (3400.0, "LB", 6.5)
    roof = next(o for o in got["offers"] if o.get("desc", "").startswith(
        "Furnish"))
    assert (roof["qty"], roof["unit"]) == (1.0, "LS")
    assert p["lines"] == []                       # nothing added by itself


def test_accept_adds_marks_and_checks_the_math(messy):
    from app import proposal_ai as ai
    p = pl.parse(messy)
    got = ai.read(p, ask=lambda prompt: _answer())
    lines = [o for o in got["offers"] if o["kind"] == "line"]
    # accept two of the three lines and the total: flagged, not forced
    q = ai.accept(p, lines[:2] + [o for o in got["offers"]
                                  if o["kind"] == "total"], "Pat Morgan")
    assert p["lines"] == [] and len(q["lines"]) == 2
    assert all(r["ai"] and r["accepted_by"] == "Pat Morgan"
               for r in q["lines"])
    assert q["total"] == 80150.0 and "they differ" in q["check"]
    assert "read by AI and accepted by Pat Morgan" in q["check"]
    assert sum(r["amount"] for r in q["lines"]) == 70350.0   # not changed
    # all three: adds up
    q = ai.accept(p, got["offers"], "Pat Morgan")
    assert "they differ" not in q["check"]
    assert q["exclusions"] == ["roof curbs", "temporary heat"]
    assert _words(pl.source_of(q, "exclusion", "temporary heat")) == \
        "temporary heat"
    assert _words(pl.source_of(q, "amount", 2)) == "9,800.00"
    assert len(q["unread"]) < len(p["unread"])
    bids = pl.to_bids([q])
    assert all(r["note"] == "read by AI - check"
               for r in bids["SAMPLE MECHANICAL CO"])


def test_a_bad_answer_is_an_error_not_a_guess(messy):
    from app import proposal_ai as ai
    p = pl.parse(messy)
    with pytest.raises(ValueError):
        ai.read(p, ask=lambda prompt: "I could not read this document.")
    got = ai.read(p, ask=lambda prompt: '{"lines": "none"}')
    assert got["offers"] == [] and got["rejected"] == []


def test_ai_only_talks_to_this_pc(monkeypatch):
    from app.ai import review
    with pytest.raises(review.AIError):
        review._allowed_host("http://example.com:11434")


def _pump(cond, secs=10):
    import time
    from PySide6.QtWidgets import QApplication
    end = time.time() + secs
    while not cond() and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    return cond()


def test_read_with_ai_window(messy, app_):
    from PySide6.QtCore import Qt
    from app import proposal_ai_ui as ui
    p = pl.parse(messy)
    dlg = ui.ProposalAIDialog(p, None, ask=lambda prompt: _answer(),
                              start=False)
    assert not dlg.ok.isEnabled()                # nothing asked yet
    dlg.start()
    assert _pump(lambda: not dlg._running)
    n = dlg.table.rowCount()
    assert n == 7 and dlg.table.item(0, 2).text().startswith("AI, check: ")
    assert all(dlg.table.item(r, 0).checkState() == Qt.Unchecked
               for r in range(n))                # nothing pre-accepted
    assert dlg.accept_ticked() is None and dlg.result is None
    s = dlg.show_source(0, modal=False)
    assert s is not None
    s.close()
    dlg.tick()
    q = dlg.accept_ticked()
    assert len(q["lines"]) == 3 and dlg.result is q


def test_read_with_ai_can_be_stopped_and_times_out(messy, app_,
                                                   monkeypatch):
    import threading
    from app import proposal_ai_ui as ui
    gate = threading.Event()

    def slow(prompt):
        gate.wait(20)
        return _answer()
    p = pl.parse(messy)
    dlg = ui.ProposalAIDialog(p, None, ask=slow)
    assert dlg._running and dlg.stop_btn.isEnabled()
    dlg.stop()
    assert not dlg._running and "Nothing was added" in dlg.status.text()
    gate.set()
    _pump(lambda: False, 0.3)                    # the late answer: ignored
    assert dlg.offers == [] and dlg.result is None
    gate.clear()
    monkeypatch.setattr(ui, "_limit", lambda: 0.0)
    dlg.start()
    dlg._started -= 1
    dlg._tick()
    assert not dlg._running and "No answer in" in dlg.status.text()
    gate.set()
    dlg.close()


def test_leveling_window_reads_an_unread_proposal_with_ai(tmp_path, app_):
    from app import leveling_ui, proposal_ai as ai
    a = _pdf(tmp_path / "a.pdf", [
        "EXAMPLE AIR INC", "Rooftop units LS $50,000.00",
        "Ductwork complete 3,400 LB $7.00 $23,800.00",
        "Controls by our sub LS $9,000.00", "Total $82,800.00"])
    b = _pdf(tmp_path / "messy.pdf", MESSY)
    w = leveling_ui.LevelingDialog()
    assert w.use_proposals([a, b]) is None       # only one was readable
    assert [p["bidder"] for p in w.ai_candidates()] == [
        "SAMPLE MECHANICAL CO"]

    def review(parent, p, ask):
        return ai.accept(p, ai.read(p, ask=ask)["offers"], "Pat Morgan")
    got = w.read_with_ai(ask=lambda prompt: _answer(), review=review)
    assert len(got["lines"]) == 3 and w.res is not None
    assert set(w.res["bidders"]) == {"EXAMPLE AIR INC",
                                     "SAMPLE MECHANICAL CO"}
    assert w.ai_candidates() == []
    # cancelled review: nothing changes
    w2 = leveling_ui.LevelingDialog()
    w2.use_proposals([a, b])
    assert w2.read_with_ai(review=lambda *a_: None) is None
    assert len(w2.proposals) == 1


def test_leveling_board_ai_lines_stay_yellow(tmp_path, app_, monkeypatch):
    from app import estimate, proposal_ai as ai
    from app.estimating import levelboard as LB, levelboard_ui
    monkeypatch.setattr(estimate, "lines", lambda d, page=None: [
        {"name": "Ductwork complete", "unit": "lb", "type": "count",
         "quantity": 3400, "code": "23 31 00", "unit_cost": 6.0},
        {"name": "Rooftop units", "unit": "ea", "type": "count",
         "quantity": 4, "code": "23 74 00", "unit_cost": 11000.0}])
    doc = fitz.open()
    doc.new_page()
    w = levelboard_ui.LevelBoard(doc)
    w.new_from_trade("23", ask=False)
    q = _pdf(tmp_path / "messy.pdf", MESSY)
    w.add_quote(q)
    d = LB.board(doc, w.package())
    assert all(r["cells"]["SAMPLE MECHANICAL CO"]["status"] == LB.RED
               for r in d["rows"])               # nothing was read

    def review(parent, p, ask):
        return ai.accept(p, ai.read(p, ask=ask)["offers"], "Pat Morgan")
    assert w.read_with_ai(ask=lambda prompt: _answer(), review=review)
    d = LB.board(doc, w.package())
    row = next(r for r in d["rows"] if r["desc"] == "Ductwork complete")
    cell = row["cells"]["SAMPLE MECHANICAL CO"]
    assert cell["status"] == LB.YELLOW and float(cell["amount"]) == 22100.0
    assert _words(LB.source_of(doc, w.package(), "SAMPLE MECHANICAL CO",
                               row_id=row["id"])) == "$22,100.00"


def test_scope_sheet_import_with_ai(tmp_path, app_):
    from app import proposal_ai as ai
    from app.pm import scope_sheet as ss, scope_sheet_ui as ui
    ed = ui.ScopeSheetEditor(None)
    sh = ss.new_sheet("23 00 00", "HVAC", bidders=1)
    sh["bidders"][0]["company"] = "Sample Mechanical Co"
    ed.set_sheet(sh)
    q = _pdf(tmp_path / "messy.pdf", MESSY)
    assert ed.clar.import_from_proposal(q) == 0   # the patterns found none

    def review(parent, p, ask):
        return ai.accept(p, ai.read(p, ask=ask)["offers"], "Pat Morgan")
    n = ed.clar.import_from_proposal(
        q, ai=True, ask=lambda prompt: _answer(), review=review)
    rows = ss.clarifications(sh, sh["bidders"][0])
    assert n == 2 and [r["text"] for r in rows] == ["roof curbs",
                                                   "temporary heat"]
    assert all(r["ai"] and r["status"] == "pending" and r["src"]["file"]
               for r in rows)
    back = ss.from_dict(ss.to_dict(sh))
    assert back["bidders"][0]["clar"][0]["ai"] is True
