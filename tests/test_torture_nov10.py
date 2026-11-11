"""Problems the torture test found (tools/torture.py, Nov 10). Made-up
data only."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                    # noqa: E402
import pytest                                                  # noqa: E402


@pytest.mark.parametrize("v", [1e300, -1e300, "1e400", 10 ** 40])
def test_money_too_large_to_round_is_a_value_error(v):
    from app import dmoney
    with pytest.raises(ValueError):
        dmoney.c2(v)
    if not isinstance(v, float):        # a huge float is left as it is
        with pytest.raises(ValueError):
            dmoney.half_up(v, 2)
    with pytest.raises(ValueError):
        dmoney.cents(v)


def test_rounding_still_works_up_to_huge_amounts():
    from app import dmoney
    assert dmoney.c2(1e20) == 1e20
    assert dmoney.c2(1234567.885) == 1234567.89
    assert dmoney.half_up(2.25, 1) == 2.3


@pytest.mark.parametrize("payload", [5, "text", [1, 2], 1.5, True])
def test_op_with_a_payload_that_is_not_an_object_is_refused(payload, caplog):
    from app import annotate
    d = fitz.open()
    d.new_page()
    op = annotate.new_op("set_jobdata", 0)
    op["payload"] = payload
    assert annotate.apply_op(d, op) is False
    assert "Traceback" not in caplog.text
    assert "payload is not an object" in caplog.text


@pytest.mark.parametrize("op", [None, 5, "add_rect", [1, 2]])
def test_op_that_is_not_an_object_is_refused(op):
    from app import annotate
    d = fitz.open()
    d.new_page()
    assert annotate.apply_op(d, op) is False


def test_billing_data_is_saved_compact():
    from app import money, embfiles
    d = fitz.open()
    d.new_page()
    money.set_info(d, 10, 10, project="Example", owner="Example",
                   contractor="Example")
    money.set_sov(d, [{"desc": f"Line {i}", "scheduled": 100.0}
                      for i in range(5)])
    raw = embfiles.get(d, money.FILE)
    assert b"\n " not in raw                 # not the slow indented form
    assert money.sov(d)[4]["scheduled"] == 100.0


def test_no_job_data_writer_indents_its_json():
    """Indented json.dumps runs in pure Python: 20x slower on the big
    records saved into the PDF on every edit (torture test, Nov 10)."""
    import re
    root = os.path.join(os.path.dirname(__file__), "..", "app")
    bad = []
    for dirpath, _d, files in os.walk(root):
        for n in files:
            if not n.endswith(".py"):
                continue
            p = os.path.join(dirpath, n)
            src = open(p, encoding="utf-8").read()
            if "embfiles.put" not in src:
                continue
            for i, line in enumerate(src.split("\n"), 1):
                if re.search(r"json\.dumps\([^)]*indent", line) and \
                        ("embfiles.put" in line or "raw = " in line or
                         "data = json" in line):
                    bad.append(f"{n}:{i}")
    assert not bad, bad


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "nan", "-inf"])
def test_bid_rate_that_is_not_a_number_counts_as_zero(bad):
    import math
    from app import bidbuild
    lines = [{"key": "a", "trade": "Example", "direct": 100.0,
              "material": 40.0}]
    b = bidbuild.build(lines, {"overhead": bad, "profit": 10})
    assert math.isfinite(b["total"])
    assert b["total"] == 110.0
    b = bidbuild.build([dict(lines[0], direct=bad)], {"profit": 10})
    assert math.isfinite(b["total"])


def _step(h, doc, x):
    from app import annotate
    before = h.begin_pages(doc, {0})
    annotate.apply_op(doc, annotate.new_op("add_rect", 0,
                                           rect=[x, 10, x + 10, 20]),
                      fresh=True)
    h.commit_pages(doc, before)
    annotate.bump_edits(doc)            # what the window's mark_dirty does
    h.stamp(doc)


def _history(doc):
    from app.history import History
    return History(lambda: doc.tobytes(), max_bytes=10 ** 9)


def test_next_edit_reuses_the_last_after_state(monkeypatch):
    from app import history
    d = fitz.open()
    d.new_page()
    h = _history(d)
    _step(h, d, 10)
    calls = []
    real = history.page_state
    monkeypatch.setattr(history, "page_state",
                        lambda doc, p: calls.append(p) or real(doc, p))
    _step(h, d, 30)
    assert calls == [0]                 # only the "after", not the "before"


def test_a_change_in_between_is_read_again(monkeypatch):
    from app import annotate, history
    d = fitz.open()
    d.new_page()
    h = _history(d)
    _step(h, d, 10)
    annotate.bump_edits(d)              # something else changed the file
    calls = []
    real = history.page_state
    monkeypatch.setattr(history, "page_state",
                        lambda doc, p: calls.append(p) or real(doc, p))
    _step(h, d, 30)
    assert calls == [0, 0]


def test_a_markup_added_behind_the_counter_is_read_again():
    d = fitz.open()
    d.new_page()
    h = _history(d)
    _step(h, d, 10)
    d[0].add_rect_annot(fitz.Rect(200, 200, 220, 220))   # no counter
    _step(h, d, 30)
    h.undo(d)
    assert len(list(d[0].annots())) == 2    # the direct one survives undo


def test_undo_and_redo_after_reused_states_are_exact():
    d = fitz.open()
    d.new_page()
    h = _history(d)
    for i in range(30):
        _step(h, d, 10 + i * 12)
    assert len(list(d[0].annots())) == 30
    for n in range(29, -1, -1):
        h.undo(d)
        assert len(list(d[0].annots())) == n
    for n in range(1, 31):
        h.redo(d)
        assert len(list(d[0].annots())) == n


def test_without_a_stamp_nothing_is_reused(monkeypatch):
    from app import annotate, history
    d = fitz.open()
    d.new_page()
    h = _history(d)
    before = h.begin_pages(d, {0})
    annotate.apply_op(d, annotate.new_op("add_rect", 0, rect=[1, 1, 9, 9]),
                      fresh=True)
    h.commit_pages(d, before)           # count_triage-style: no stamp
    calls = []
    real = history.page_state
    monkeypatch.setattr(history, "page_state",
                        lambda doc, p: calls.append(p) or real(doc, p))
    h.begin_pages(d, {0})
    assert calls == [0]


def test_is_applied_finds_ops_by_their_tag():
    from app import annotate
    d = fitz.open()
    d.new_page()
    ids = []
    for i in range(40):
        op = annotate.new_op("add_rect", 0, rect=[i, i, i + 5, i + 5])
        annotate.apply_op(d, op, fresh=True)
        ids.append(op["id"])
    d[0].add_rect_annot(fitz.Rect(300, 300, 310, 310))   # untagged
    page = d[0]
    for oid in ids:
        assert annotate.is_applied(page, oid)
        assert annotate.is_applied(page, oid) == any(
            annotate.tag_of(a) == oid for a in page.annots())
    assert not annotate.is_applied(page, "not-an-op")
    assert not annotate.is_applied(page, ids[0][:-1])
    # a replayed op is still applied only once
    op = annotate.new_op("add_rect", 0, rect=[1, 1, 2, 2])
    assert annotate.apply_op(d, op)
    assert not annotate.apply_op(d, op)


def test_viewer_edit_leaves_a_valid_stamp(qapp, tmp_path):
    """The redraw after an edit bumps the edit counter; the stamp must
    come after it or the next edit never reuses the state."""
    from app import annotate
    from app.viewer import PdfView
    p = str(tmp_path / "s.pdf")
    d = fitz.open()
    d.new_page()
    d.save(p)
    v = PdfView(fitz.open(p), p)
    v.apply_marks([(0, "add_rect", {"rect": [10, 10, 30, 30]})])
    hit = v.history._after
    assert hit is not None and hit["count"] == annotate.edit_count(v.doc)


def test_big_job_data_is_stored_fast_and_reads_back_exactly(tmp_path):
    import json
    import random
    from app import embfiles, money
    rnd = random.Random(1)
    d = fitz.open()
    d.new_page()
    data = {"rows": [{"desc": f"Line {i} Ü", "v": rnd.random() * 1e6}
                     for i in range(20000)]}
    raw = json.dumps(data).encode("utf-8")
    assert len(raw) > embfiles.FAST_ABOVE
    embfiles.put(d, "quantisheet_test.json", b"{}")
    embfiles.put(d, "quantisheet_test.json", raw)         # the update path
    assert bytes(embfiles.get(d, "quantisheet_test.json")) == raw
    p = str(tmp_path / "x.pdf")
    d.save(p)
    r = fitz.open(p)
    assert bytes(embfiles.get(r, "quantisheet_test.json")) == raw
    _loc, entries = embfiles._find(r, "quantisheet_test.json")
    i = embfiles._index(r, entries, "quantisheet_test.json")
    x = embfiles._stream_xref(r, entries[i][1])
    assert r.xref_get_key(x, "Filter")[1] == "/FlateDecode"
    # and a pay app record that grows past the line still saves and reads
    money.set_info(r, 10, 10, project="Example", owner="Example",
                   contractor="Example")
    money.set_sov(r, [{"desc": f"Line {i} " + "x" * 300, "scheduled": 100.0}
                      for i in range(600)])
    assert len(money.sov(r)) == 600
    no = money.new_pay_app(r, "2026-01-31")
    money.set_progress(r, no, money.sov(r)[0]["item"], work=12.5)
    assert money.compute(r, no)["rows"][0]["this"] == 12.5
