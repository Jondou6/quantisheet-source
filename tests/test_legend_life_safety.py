"""Nov 1 (Aiken): the fire extinguisher in the code-plan legend was left
over at AI Takeoff's 180 s device limit. Code-legend notes (mounting
heights, egress paths, wall types) each took ~17 s to search for nothing,
and the extinguisher was only looked for on the trade sheets, where it is
never drawn. Now notes are not searched, devices go first, and a
life-safety device is looked for on the life safety / floor plans."""
import pytest

fitz = pytest.importorskip("fitz")

from app import tradetakeoff as tt  # noqa: E402


@pytest.mark.parametrize("name", [
    '50" A.F.F', "TOP OF F.E.C", "ANTICIPATED LOAD",
    "CONSTRUCTION FOR NON-RATED PARTITIONS",
    "EXIT CAPACITY (DOOR EGRESS WIDTH / 0.2)",
    "EGRESS TRAVEL PATH - DISTANCE NOTED IS ACTUAL", "OCCUPANT LOAD"])
def test_code_legend_notes_are_not_symbols(name):
    assert not tt.good_name(name)


@pytest.mark.parametrize("name", [
    "CONT FIRE EXTINGUISHER", "DUPLEX CONVENIENCE OUTLET", "EXIT SIGN",
    "FIRE ALARM MANUAL PULL STATION", "LOAD CENTER", "SUPPLY DIFFUSER"])
def test_devices_still_are(name):
    assert tt.good_name(name)


def test_life_safety_devices():
    assert tt.life_safety_device("CONT FIRE EXTINGUISHER")
    assert tt.life_safety_device("FEC - FIRE EXTINGUISHER CABINET")
    assert tt.life_safety_device("AED CABINET")
    assert not tt.life_safety_device("TOP OF F.E.C")       # a note
    assert not tt.life_safety_device("DUPLEX CONVENIENCE OUTLET")


def test_life_safety_pages_prefer_the_life_safety_plan():
    titles = {3: "FIRST FLOOR PLAN", 4: "LIFE SAFETY PLAN", 5: "ROOF PLAN"}
    assert tt._life_safety_pages([3, 4], titles) == [4]
    assert tt._life_safety_pages([3, 5], titles) == [3, 5]


def _run(monkeypatch, rows, plan_pages, disciplines, titles, time_limit=None,
         slow=()):
    """legend_counts with the picture search stubbed: returns (searched
    [(name, pages)], report)."""
    from app import autocount
    doc = fitz.open()
    for _ in range(6):
        doc.new_page()
    monkeypatch.setattr(tt, "legend_rows",
                        lambda page, rejects=None, text_syms=None:
                        rows if page.number == 0 else [])
    monkeypatch.setattr(tt, "_table_boxes", lambda page: [])
    monkeypatch.setattr(tt, "_same_picture", lambda tpl, seen: None)
    monkeypatch.setattr(tt, "fill_ring_signature", lambda d, b: None)
    monkeypatch.setattr(tt, "_symbol_word", lambda page, sym: None)
    n = [0]

    def tpl(page, clip):
        n[0] += 1
        return b"png%d" % n[0]
    monkeypatch.setattr(autocount, "symbol_template", tpl)
    searched = []
    clock = [0.0]
    import time as _t
    monkeypatch.setattr(_t, "perf_counter", lambda: clock[0])

    def find(doc_, t, thr, where, cache=None):
        name = names[t]
        searched.append((name, list(where) if where is not None else None))
        clock[0] += 17.0 if name in slow else 2.0
        return []
    names = {}
    order = []

    def prog(k, total, name):
        order.append(name)
        names[b"png%d" % (n[0] + 1)] = name
        return True
    monkeypatch.setattr(autocount, "find_symbols", find)
    rep = {}
    tt.legend_counts(doc, [1, 2], progress=prog, time_limit=time_limit,
                     report=rep, disciplines=disciplines, titles=titles,
                     plan_pages=plan_pages)
    return searched, order, rep


R = fitz.Rect


def test_extinguisher_on_the_life_safety_plan_first(monkeypatch):
    rows = [("TOILET ACCESSORY MOUNTING", R(10, 10, 30, 30)),
            ("TOP OF F.E.C", R(10, 40, 30, 60)),
            ("CONT FIRE EXTINGUISHER", R(10, 70, 30, 90))]
    disc = {0: "code", 1: "electrical", 2: "plumbing", 3: "architectural",
            4: "architectural", 5: "architectural"}
    titles = {3: "FIRST FLOOR PLAN", 4: "LIFE SAFETY PLAN"}
    searched, order, rep = _run(monkeypatch, rows, [3, 4], disc, titles)
    assert "TOP OF F.E.C" not in order                    # a note
    assert order[0] == "CONT FIRE EXTINGUISHER"           # device first
    assert dict(searched)["CONT FIRE EXTINGUISHER"] == [4]
    assert dict(searched)["TOILET ACCESSORY MOUNTING"] == [1, 2]
    assert any(n == "TOP OF F.E.C" for _p, n, _w in rep["rejected"])


def test_time_limit_falls_on_the_doubtful_lines(monkeypatch):
    rows = [("WEIRD LINE %d" % i, R(10, 10 + 30 * i, 30, 30 + 30 * i))
            for i in range(5)] + [("CONT FIRE EXTINGUISHER", R(60, 10, 80, 30))]
    disc = {0: "code", 1: "electrical", 2: "plumbing", 3: "architectural"}
    searched, order, rep = _run(
        monkeypatch, rows, [3], disc, {3: "FLOOR PLAN"}, time_limit=40,
        slow={"WEIRD LINE %d" % i for i in range(5)})
    assert "CONT FIRE EXTINGUISHER" in dict(searched)
    left = [n for n, why in rep["not_counted"] if "time limit" in why]
    assert left and "CONT FIRE EXTINGUISHER" not in left


def test_no_plan_pages_keeps_the_old_pages(monkeypatch):
    rows = [("CONT FIRE EXTINGUISHER", R(10, 70, 30, 90))]
    disc = {0: "code", 1: "electrical", 2: "plumbing"}
    searched, _o, _r = _run(monkeypatch, rows, None, disc, {})
    assert dict(searched)["CONT FIRE EXTINGUISHER"] == [1, 2]
