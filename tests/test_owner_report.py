"""Weekly Owner Report (owner_report.py): the default form page for page,
carry-over, the company template snapshot, drafting from Daily Logs (plain
and local-AI), and each optional section off -> absent, on -> present.
Made-up data only."""
import json
import math
import os
import re
from datetime import date, timedelta

import fitz
import pytest
from PIL import Image

from app import annotate, settings
from app.pm import activity_lookahead, lookahead, owner_report as orp
from app.pm import recovery, schedule, weather
from app.pm.store import ProjectStore

WE = date(2026, 10, 20)                  # a Tuesday: the week closes
GREY = (0.851, 0.851, 0.851)
FRAME = (0.329, 0.51, 0.208)
RED_INT = 0xCC0000


# ------------------------------------------------------------ fixtures
@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    s = ProjectStore(str(tmp_path / "Job"))
    s.data["name"] = "Harbor Point Clubhouse (example)"
    s.set_setting("number", "26-101")
    s.set_setting("project_start", "2026-09-01")
    return s


def make_photo(tmp_path, name, size=(400, 300), when="2026:10:14 14:40:00",
               seed=0):
    """A made-up photo: noise so every file differs, optional EXIF date."""
    im = Image.effect_noise(size, 40 + seed % 50).convert("RGB")
    im = Image.merge("RGB", [im.split()[0],
                             im.split()[1].point(lambda v: (v + seed) % 256),
                             im.split()[2]])
    p = str(tmp_path / name)
    ex = Image.Exif()
    if when:
        ex[0x0132] = when
        ex.get_ifd(0x8769)[0x9003] = when
    im.save(p, "JPEG", exif=ex)
    if not when:
        t = (date(2026, 10, 15) - date(1970, 1, 1)).days * 86400 + 36000
        os.utime(p, (t, t))
    return p


def report(store, **opts):
    rep = orp.new_report(store, WE, online=False)
    rep["options"].update(opts)
    return rep


def add_photos(store, rep, tmp_path, n, **kw):
    paths = [make_photo(tmp_path, f"ph{i:02d}.jpg", seed=i, **kw)
             for i in range(n)]
    return orp.add_photos(store, rep, paths)


def build(store, rep, tmp_path, name="r.pdf", **kw):
    path = str(tmp_path / name)
    res = orp.build_pdf(store, rep, path, **kw)
    return res, fitz.open(path)


def names(res):
    return [m[0] for m in res["page_map"]]


def pages_of(res, name):
    m = next(m for m in res["page_map"] if m[0] == name)
    return list(range(m[1] - 1, (m[2] if len(m) > 2 else m[1])))


def text_of(doc, pnos=None):
    return "\n".join(doc[i].get_text() for i in
                     (pnos if pnos is not None else range(doc.page_count)))


def close(a, b, tol=1.0):
    return abs(a - b) <= tol


def color_close(c, want, tol=0.02):
    return c is not None and len(c) == 3 and \
        all(abs(x - y) <= tol for x, y in zip(c, want))


def spans(page):
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                yield sp


def daily(store, day, **kw):
    rec = {"date": day, "status": "Submitted"}
    rec.update(kw)
    return store.save_record("daily", rec)


# ------------------------------------------------------------ core
def test_at01_default_package_order(store, tmp_path):
    rep = report(store)
    add_photos(store, rep, tmp_path, 32)
    res, doc = build(store, rep, tmp_path)
    assert names(res) == ["page1", "photos", "rfi_log", "submittal_log",
                          "weather_log", "forecast"]
    assert pages_of(res, "photos") == list(range(1, 9))     # 8 pages
    assert res["pages"] == doc.page_count
    assert res["bytes"] == os.path.getsize(tmp_path / "r.pdf")
    assert res["photo_bytes"] > 0
    assert res["data"][:4] == b"%PDF"


def test_at02_page1_is_landscape_with_sections(store, tmp_path):
    res, doc = build(store, report(store), tmp_path)
    p = doc[0]
    assert (p.rect.width, p.rect.height, p.rotation) == (792, 612, 0)
    t = p.get_text()
    for s in ("Project Progress Report", "WORK IN PROGRESS", "LOGS",
              "INCLEMENT WEATHER DAYS", "CURRENT PROGRESS",
              "UPCOMING WEATHER FORECAST - 10 DAY", "REPORT #", "001",
              "26-101", "10/20/2026", "See Attached Inclement Weather Log"):
        assert s in t, s


def test_at03_geometry(store, tmp_path):
    rep = report(store, captions=False)     # the form's photo grid
    add_photos(store, rep, tmp_path, 4)
    res, doc = build(store, rep, tmp_path)
    dr = doc[0].get_drawings()
    bars = sorted(round(d["rect"].y0, 1) for d in dr
                  if color_close(d.get("fill"), GREY) and
                  d["rect"].height < 13)
    for y in (orp.WIP_Y, orp.LOGS_Y, orp.WEATHER_Y, orp.PROGRESS_Y,
              orp.FORECAST_Y[0]):
        assert any(close(b, y) for b in bars), y
    wip = next(d["rect"] for d in dr if color_close(d.get("fill"), GREY)
               and close(d["rect"].y0, orp.WIP_Y))
    assert close(wip.x0, 39.8) and close(wip.x1, 751.7) and \
        close(wip.height, 11.7)
    boxes = [d["rect"] for d in dr if close(d["rect"].width, 8.9, 0.3) and
             close(d["rect"].height, 8.7, 0.3)]
    assert len(boxes) == 23
    assert {round(b.x0, 1) for b in boxes} == set(orp.BOX_X)
    # photos: frames on the cells (400x300 is 4:3 -> fills the cell)
    frames = [d for d in doc[1].get_drawings()
              if color_close(d.get("color"), FRAME) and
              close(d.get("width") or 0, 1.65, 0.05)]
    assert len(frames) == 4
    for d, cell in zip(sorted(frames, key=lambda d: (d["rect"].y0,
                                                    d["rect"].x0)),
                       orp.CELLS4):
        assert all(close(a, b, 1.0) for a, b in zip(d["rect"], cell))


def test_at04_checkboxes_match_trades(store, tmp_path):
    rep = report(store)
    rep["trades"] = ["Site Work", "Masonry", "Electrical", "Painting"]
    res, doc = build(store, rep, tmp_path)
    dr = doc[0].get_drawings()
    boxes = [d["rect"] for d in dr if close(d["rect"].width, 8.9, 0.3) and
             close(d["rect"].height, 8.7, 0.3)]
    assert len(boxes) == 23
    trades = orp.trade_list(orp.load_template())
    ticked = set()
    for d in dr:
        r = d["rect"]
        if close(r.width, 8.9, 0.3):                   # a box itself
            continue
        for b in boxes:
            if b.x0 - 0.5 <= r.x0 and r.x1 <= b.x1 + 0.5 and \
                    b.y0 - 0.5 <= r.y0 and r.y1 <= b.y1 + 0.5:
                c = min(range(4), key=lambda i: abs(orp.BOX_X[i] - b.x0))
                row = min(range(6), key=lambda i: abs(orp.BOX_Y[i] - b.y0))
                ticked.add(trades[c][row])
    assert ticked == set(rep["trades"])


def test_at05_progress_overflows_to_page_1b(store, tmp_path):
    rep = report(store)
    rep["progress"] = [{"text": f"Example progress bullet number {i} for "
                        "the owner report.", "include": True, "src": "typed"}
                       for i in range(25)]
    res, doc = build(store, rep, tmp_path)
    assert names(res)[:2] == ["page1", "page1b"]
    t0, t1 = doc[0].get_text(), doc[1].get_text()
    assert "number 0 " in t0 and "number 20 " in t0
    assert "number 21 " not in t0 and "number 24 " in t1
    assert "CURRENT PROGRESS (CONTINUED)" in t1 and "REPORT #" in t1
    for pno in (0, 1):
        sizes = {round(sp["size"], 1) for sp in spans(doc[pno])
                 if "progress bullet" in sp["text"]}
        assert sizes == {8.2}
    # the forecast block stays on page 1 only
    assert "UPCOMING WEATHER FORECAST" not in t1


def test_at08_flattened(store, tmp_path):
    rep = report(store)
    add_photos(store, rep, tmp_path, 2)
    res, doc = build(store, rep, tmp_path)
    for p in doc:
        assert p.first_annot is None and p.first_widget is None


def test_at12_carry_over(store, tmp_path):
    rep = report(store)
    rep["report_no"] = "022"
    rep["trades"] = ["Masonry", "Framing"]
    rep["progress"] = [{"text": "Framing at Bldg A continued.",
                        "include": True, "src": "typed"}]
    rep["decisions"] = [{"text": "Select tile", "due": "2026-10-30",
                         "done": False},
                        {"text": "Approve paint", "due": "2026-10-10",
                         "done": True}]
    add_photos(store, rep, tmp_path, 2)
    rep["options"]["captions"] = True
    orp.save(store, rep)
    nxt = orp.new_report(store, WE + timedelta(days=7), online=False)
    assert nxt["report_no"] == "023"
    assert nxt["date"] == nxt["week_ending"] == "2026-10-27"
    assert nxt["trades"] == ["Masonry", "Framing"]
    assert [(b["text"], b["src"]) for b in nxt["progress"]] == \
        [("Framing at Bldg A continued.", "carried")]
    assert [d["text"] for d in nxt["decisions"]] == ["Select tile"]
    assert nxt["photos"] == []
    assert nxt["options"]["captions"] is True
    # without a date: the week after the last report
    nxt2 = orp.carry_over(store.get(orp.COLL, nxt["_id"]), store,
                          WE + timedelta(days=14))
    assert nxt2["report_no"] == "024"
    assert orp.week_ending_for(date(2026, 10, 21)) == WE
    assert orp.week_ending_for(WE) == WE


def test_at13_template_snapshot(store, tmp_path):
    a, b = str(tmp_path / "logo_a.png"), str(tmp_path / "logo_b.png")
    Image.new("RGB", (200, 100), (30, 120, 60)).save(a)
    Image.new("RGB", (100, 100), (200, 40, 40)).save(b)
    t = orp.load_template()
    t["logo"] = a
    orp.save_template(t)
    old = report(store)
    orp.export(store, old)
    t = orp.load_template()
    t["logo"] = b
    t["trades"][0][0] = "Sitework & Grading"
    orp.save_template(t)

    def look(rep, name):
        res, doc = build(store, rep, tmp_path, name)
        imgs = doc[0].get_images(full=True)
        return doc[0].get_text(), {(i[2], i[3]) for i in imgs}
    text, imgs = look(store.get(orp.COLL, old["_id"]), "old.pdf")
    assert "Site Work" in text and "Sitework" not in text
    assert imgs == {(200, 100)}
    new = orp.new_report(store, WE + timedelta(days=7), online=False)
    text, imgs = look(new, "new.pdf")
    assert "Sitework & Grading" in text
    assert imgs == {(100, 100)}
    # the export landed in Reports/Owner with the form's file name
    ex = store.get(orp.COLL, old["_id"])["exported"][0]
    # company rule: date first, project name, PPR Report, 3-digit number
    base = os.path.basename(ex["path"])
    assert base.startswith("2026.10.20 ") and \
        base.endswith(" PPR Report 001.pdf"), base
    assert os.path.isfile(ex["path"])


# ------------------------------------------------------------ (a) captions
def test_a1_captions(store, tmp_path):
    rep = report(store, captions=False)     # on by default since G09
    add_photos(store, rep, tmp_path, 2)
    rep["photos"][0]["location"] = "Pool House"
    rep["photos"][1]["caption"] = "Work in progress - example caption."
    res, doc = build(store, rep, tmp_path, "off.pdf")
    t = text_of(doc, pages_of(res, "photos"))
    assert t.split() == "Project Progress Report".split()
    rep["options"]["captions"] = True
    res, doc = build(store, rep, tmp_path, "on.pdf")
    t = text_of(doc, pages_of(res, "photos"))
    assert "#01" in t and "10/14/2026 2:40 PM" in t and "Pool House" in t
    assert "#02" in t and "example caption" in t


def test_a2_no_exif_date_says_file_date(store, tmp_path):
    rep = report(store, captions=True)
    orp.add_photos(store, rep, [make_photo(tmp_path, "noexif.jpg",
                                           when=None)])
    assert rep["photos"][0]["taken_src"] == "file"
    res, doc = build(store, rep, tmp_path)
    assert "(file date)" in text_of(doc, pages_of(res, "photos"))


# ------------------------------------------------------------ (b) decisions
def test_b1_owner_decisions(store, tmp_path):
    rep = report(store)
    rep["decisions"] = [
        {"text": "Approve transformer pad relocation", "due": "2026-10-22",
         "impact": "Permanent power slips", "ref": "RFI-004", "done": False},
        {"text": "Select entry canopy color", "due": "2026-11-15",
         "impact": "", "ref": "", "done": False},
        {"text": "Approve paint colors", "due": "2026-10-01", "done": True}]
    res, doc = build(store, rep, tmp_path, "off.pdf")
    assert "OWNER DECISIONS NEEDED" not in text_of(doc)
    rep["options"]["decisions"] = True
    res, doc = build(store, rep, tmp_path, "on.pdf")
    assert names(res)[:2] == ["page1", "summary"]
    t = text_of(doc, pages_of(res, "summary"))
    assert "OWNER DECISIONS NEEDED" in t
    assert "transformer pad" in t and "canopy" in t
    assert "Approve paint colors" not in t
    assert len(orp.open_decisions(rep)) == 2
    sp = {s["text"].strip(): s for s in spans(doc[pages_of(res,
                                                           "summary")[0]])}
    urgent, later = sp["10/22/2026"], sp["11/15/2026"]
    assert urgent["color"] == RED_INT and "Bold" in urgent["font"]
    assert later["color"] != RED_INT and "Bold" not in later["font"]


# ------------------------------------------------------------ (c) schedule
def _schedule(store):
    store.set_setting("data_date", "2026-09-01")
    store.set_setting("contract_days", 300)
    add = lambda **r: store.save_record("activity", r)  # noqa: E731
    add(name="Mobilize", duration=10, start="2026-09-01", percent=100,
        status="Complete")
    add(name="Foundations", duration=20, preds=[{"id": "A0001"}],
        percent=50, status="In Progress")
    add(name="Framing", duration=10, preds=[{"id": "A0002"}],
        responsible="Sample Framing")
    add(name="Dry in", duration=0, preds=[{"id": "A0003"}],
        baseline_finish="2026-10-20")
    add(name="Roofing", duration=8, preds=[{"id": "A0003"}])
    add(name="SUBSTANTIAL COMPLETION", duration=0,
        preds=[{"id": "A0005"}], baseline_finish="2026-10-23")


def test_c1_schedule_status(store, tmp_path):
    _schedule(store)
    recovery.save(store, {"target": "2026-10-23", "cause": "weather",
                          "steps": [{"id": "x", "technique": "crash",
                                     "agreed": True}],
                          "status": "Applied", "applied": "2026-10-12"})
    rep = report(store)
    rep["weather"]["claimed"] = 3
    st = orp.schedule_status(store, rep)
    # duration-weighted: (10*100 + 20*50 + 10*0 + 8*0) / 48
    assert abs(st["percent"] - 2000 / 48) <= 0.1
    assert st["used"] + st["remaining"] == 300 + 3
    assert st["used"] == (WE - date(2026, 9, 1)).days + 1
    cpm = schedule.cached(store)
    for m in st["milestones"]:
        row = next(r for r in cpm["rows"] if r["name"] == m["name"])
        assert m["variance"] == schedule.variance(row, cpm["cal"])
    behind = recovery.standing(store, cpm=cpm)["behind"]
    assert st["recovery"]["behind"] == behind and st["recovery"]["plan"]
    res, doc = build(store, rep, tmp_path, "off.pdf")
    assert "SCHEDULE STATUS" not in text_of(doc)
    rep["options"]["schedule"] = True
    res, doc = build(store, rep, tmp_path, "on.pdf")
    t = " ".join(text_of(doc, pages_of(res, "summary")).split())
    assert "SCHEDULE STATUS" in t and f"{st['percent']:.1f}%" in t
    assert "300 + 3 weather = 303" in t
    assert "Recovery plan in place" in t
    if behind:
        word = "behind" if behind > 0 else "ahead"
        assert f"{abs(behind)} workday" in t and word in t
    assert "Dry in" in t


def test_c2_no_schedule(store, tmp_path):
    rep = report(store, schedule=True)
    assert orp.schedule_status(store, rep) == {"has": False}
    res, doc = build(store, rep, tmp_path)
    assert "No schedule in Project Center" in text_of(doc)


# ------------------------------------------------------------ (d) look-ahead
def test_d1_lookahead(store, tmp_path):
    _schedule(store)
    store.save_record("submittal", {"title": "Tile - grout colors",
                                    "spec": "09 30 00", "type": "Samples",
                                    "status": "Not Submitted",
                                    "submit_by": "2026-10-28",
                                    "responsible": "Sample Tile Co."})
    store.save_record("submittal", {"title": "Elevator shop drawings",
                                    "spec": "14 20 00",
                                    "status": "Not Submitted",
                                    "submit_by": "2026-12-15"})
    rep = report(store)
    s, e, rows = orp.lookahead_rows(store, rep)
    assert (s, e) == (WE + timedelta(days=1), WE + timedelta(days=14))
    want = [r for r in activity_lookahead.rows(store, 3, s)
            if r["late"] or (r["start"] <= e and r["finish"] >= s)]
    assert [r["id"] for r in rows] == [r["id"] for r in want]
    assert rows
    res, doc = build(store, rep, tmp_path, "off.pdf")
    assert "LOOK-AHEAD" not in text_of(doc)
    rep["options"]["lookahead"] = True
    res, doc = build(store, rep, tmp_path, "on.pdf")
    pnos = pages_of(res, "lookahead")
    t = text_of(doc, pnos)
    assert "TWO-WEEK LOOK-AHEAD" in t
    for r in rows:
        assert r["name"] in t
    subs = lookahead.lookahead(store, 2, s)
    assert [x["title"] for x in subs] == ["Tile - grout colors"]
    assert "Tile - grout colors" in t and "Elevator shop" not in t
    crit = [d for d in doc[pnos[0]].get_drawings()
            if color_close(d.get("fill"), orp.CRIT_RED)]
    shown = [r for r in rows if r["critical"] and not r["milestone"] and
             any(r["start"] <= s + timedelta(days=i) <= r["finish"] and
                 (s + timedelta(days=i)).weekday() < 5 for i in range(14))]
    assert bool(crit) == bool(shown)


# ------------------------------------------------------------ (e) weather gap
def test_e1_weather_gap_line(store, tmp_path, monkeypatch):
    store.set_setting("location", "Example, SC")
    store.set_setting("project_start", "2026-10-01")
    rain = {"2026-10-03": 0.9,       # Saturday: non-work day
            "2026-10-06": 0.7,       # Tuesday: claimed
            "2026-10-08": 1.2,       # Thursday: claimed
            "2026-10-11": 0.6}       # Sunday
    monkeypatch.setattr(weather, "history", lambda place, a, b: [
        {"date": d, "rain_in": v, "high": 70, "low": 50}
        for d, v in sorted(rain.items()) if a <= d <= b], raising=False)
    monkeypatch.setattr(weather, "forecast", lambda place, days=10: [],
                        raising=False)
    rep = orp.new_report(store, WE, online=False)
    orp.autofill(store, rep, online=True, today=WE + timedelta(days=1))
    w = rep["weather"]
    assert (w["impacted"], w["claimed"]) == (4, 2)
    res, doc = build(store, rep, tmp_path, "off.pdf")
    assert "impacted vs" not in doc[0].get_text()
    rep["options"]["weather_gap"] = True
    res, doc = build(store, rep, tmp_path, "on.pdf")
    t = " ".join(doc[0].get_text().split())
    line = orp.gap_line(rep)
    assert line and " ".join(line.split()) in t
    nums = [int(n) for n in re.findall(r"(?<![\d.])(\d+)(?![\d.])", line)]
    assert nums[:2] == [4, 2] and sum(nums[2:]) == 4 - 2
    # equal counts: no line. The totals come from the day list (review
    # 0.12.38 #12 / single-source fix #7), so mark the days claimed there;
    # the stored totals are left stale on purpose - they must not win.
    w["impacted"], w["claimed"] = 4, 2
    for d in w["days"]:
        if d.get("tracked"):
            d["claimed"] = True
            d["edited"] = True
    assert orp.weather_counts(rep) == (4, 4)
    assert orp.gap_line(rep) is None
    res, doc = build(store, rep, tmp_path, "eq.pdf")
    assert "impacted vs" not in doc[0].get_text()
    # the review's case: three weather days, all three claimed in the day
    # list -> no gap line, whatever the stored total says
    three = {"impacted": 3, "claimed": 0, "days": [
        {"date": "2026-10-06", "rain_in": 0.7, "tracked": True,
         "claimed": True},
        {"date": "2026-10-07", "rain_in": 0.8, "tracked": True,
         "claimed": True},
        {"date": "2026-10-08", "rain_in": 1.2, "tracked": True,
         "claimed": True}]}
    rep3 = dict(rep, weather=three)
    assert orp.weather_counts(rep3) == (3, 3)
    assert orp.gap_line(rep3) is None
    three["days"][1]["claimed"] = False             # one unclaimed: a line
    assert orp.gap_line(rep3)


# ------------------------------------------------------------ (h) manpower
def test_h1_manpower_and_safety(store, tmp_path):
    daily(store, "2026-10-14", manpower=[
        {"company": "Sample Concrete", "trade": "Concrete", "workers": 6},
        {"company": "Sample Steel", "trade": "Steel", "workers": 4}],
        safety="Toolbox talk on ladders. Nothing else.")
    daily(store, "2026-10-15", manpower=[
        {"company": "Sample Concrete", "trade": "Concrete", "workers": 5}],
        safety="No incidents today.")
    daily(store, "2026-10-12", manpower=[           # the week before
        {"company": "Sample Concrete", "trade": "Concrete", "workers": 9}])
    rep = report(store)
    mp = orp.manpower_week(store, rep)
    assert mp["totals"]["2026-10-14"] == 10
    assert mp["totals"]["2026-10-15"] == 5
    assert mp["total"] == 15
    assert [d.isoformat() for d in mp["days"]] == [
        "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19",
        "2026-10-20"]
    res, doc = build(store, rep, tmp_path, "off.pdf")
    t = text_of(doc)
    assert "MANPOWER" not in t and "SAFETY:" not in t
    rep["options"]["manpower"] = True
    res, doc = build(store, rep, tmp_path, "on.pdf")
    t = text_of(doc, pages_of(res, "summary"))
    assert "MANPOWER THIS WEEK" in t and "Sample Concrete" in t
    assert "SAFETY:" in t and "Toolbox talk on ladders" in t
    assert "No incidents today" in t
    assert "15" in t


# ------------------------------------------------------------ (i) key plan
def _sheet(tmp_path):
    """A made-up plan sheet whose text font is embedded, so it prints as
    vectors (a base-14 sheet goes in as an image: test_owner_report_fonts)."""
    from app.pm import owner_report_logs as orl
    path = str(tmp_path / "C-101 example.pdf")
    d = fitz.open()
    p = d.new_page(width=792, height=612)
    p.draw_rect(fitz.Rect(60, 60, 300, 200), color=(0, 0, 0), width=1)
    p.insert_font(fontname="SheetF", fontfile=os.path.join(
        orl.font_dir(), "LiberationSans-Regular.ttf"))
    p.insert_text((70, 80), "BLDG A - CLUBHOUSE", fontsize=9,
                  fontname="SheetF")
    d.save(path)
    d.close()
    return path


def _spy(monkeypatch):
    calls = []
    real = annotate.apply_op

    def spy(doc, op, fresh=False):
        calls.append(op)
        return real(doc, op, fresh)
    monkeypatch.setattr(annotate, "apply_op", spy)
    return calls


def test_i1_i2_key_plan(store, tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    rep = report(store)
    add_photos(store, rep, tmp_path, 6)
    for i, ph in enumerate(rep["photos"][:3]):
        ph["pin"] = {"sheet": sheet, "page": 0, "x": 100 + 60 * i, "y": 150}
        ph["location"] = f"Example area {i + 1}"
    calls = _spy(monkeypatch)
    res, doc = build(store, rep, tmp_path, "off.pdf")
    assert "key_plan" not in names(res) and not calls
    rep["options"]["key_plan"] = True
    rep["key_plan"] = {"sheet": sheet, "page": 0, "clip": [0, 0, 600, 400]}
    res, doc = build(store, rep, tmp_path, "on.pdf")
    assert names(res).index("key_plan") == names(res).index("photos") + 1
    assert [c["kind"] for c in calls] == ["add_count"] * 3
    assert all(c["payload"]["look"] == "takeoff" for c in calls)
    assert [c["payload"]["n"] for c in calls] == ["1", "2", "3"]
    for p in doc:
        assert p.first_annot is None and p.first_widget is None
    t = text_of(doc, pages_of(res, "key_plan"))
    assert "Location / caption" in t
    for i in range(3):
        assert f"Example area {i + 1}" in t
    # the photos are on report page 2 (index 1): the table says so
    assert orp.printed_photos(rep)[0]["pin"]
    pin_dots = [d for d in doc[pages_of(res, "key_plan")[0]].get_drawings()
                if color_close(d.get("fill"), orp.PIN_COLOR, 0.05)]
    assert len(pin_dots) >= 3
    # the sheet's font is embedded: it stays vector (its text is text) and
    # the pin numbers are drawn in the report's own embedded font
    assert "BLDG A - CLUBHOUSE" in t
    assert not doc[pages_of(res, "key_plan")[0]].get_images()
    assert res["unembedded_fonts"] == []


def test_j1_work_areas(store, tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    rep = report(store)
    rep["work_areas"] = [
        {"sheet": sheet, "page": 0, "pts": [[60, 60], [300, 60], [300, 200],
                                            [60, 200]],
         "color": [0.96, 0.69, 0.25], "label": "Bldg A",
         "note": "Slab east half; framing layout."},
        {"sheet": sheet, "page": 0, "pts": [[400, 300], [600, 300],
                                            [500, 450]],
         "label": "Area C", "note": "Retention grading."}]
    calls = _spy(monkeypatch)
    res, doc = build(store, rep, tmp_path, "off.pdf")
    assert "work_areas" not in names(res)
    rep["options"]["work_areas"] = True
    res, doc = build(store, rep, tmp_path, "on.pdf")
    assert [c["kind"] for c in calls] == ["add_polygon"] * 2
    assert all(c["payload"]["look"] == "takeoff" for c in calls)
    t = text_of(doc, pages_of(res, "work_areas"))
    assert "This week's work areas" in t
    assert "Bldg A" in t and "Area C" in t and "Retention grading" in t
    for p in doc:
        assert p.first_annot is None


# ------------------------------------------------------------ (k) pairs
def test_k1_before_after(store, tmp_path):
    sheet = _sheet(tmp_path)
    rep = report(store)
    add_photos(store, rep, tmp_path, 3)
    before = orp.add_photos(store, {"photos": []}, [
        make_photo(tmp_path, f"old{i}.jpg", seed=50 + i,
                   when="2026:10:07 09:00:00") for i in range(3)])
    before[0]["pin"] = {"sheet": sheet, "page": 0, "x": 100, "y": 100}
    before[1]["pin"] = {"sheet": sheet, "page": 0, "x": 300, "y": 100}
    before[2]["location"] = "Maintenance Yard"
    rep["before_candidates"] = before
    a, b, c = rep["photos"]
    a["pin"] = {"sheet": sheet, "page": 0, "x": 110, "y": 110}   # 14 pt
    b["pin"] = {"sheet": sheet, "page": 0, "x": 340, "y": 100}   # 40 pt
    c["location"] = "maintenance yard"
    pairs = orp.suggest_pairs(rep)
    got = {orp._photo_key(p["ref"]): orp._photo_key(q["ref"])
           for p, q in pairs}
    assert got == {orp._photo_key(a["ref"]): orp._photo_key(before[0]["ref"]),
                   orp._photo_key(c["ref"]): orp._photo_key(before[2]["ref"])}
    orp.accept_pairs(rep, pairs)
    res, doc = build(store, rep, tmp_path, "off.pdf")
    assert "before_after" not in names(res)
    rep["options"]["before_after"] = True
    res, doc = build(store, rep, tmp_path, "on.pdf")
    t = text_of(doc, pages_of(res, "before_after"))
    assert t.count("BEFORE") == 2 and t.count("AFTER") == 2
    assert "10/07/2026" in t and "10/14/2026" in t


# ------------------------------------------------------------ (l) drafting
def _logs(store):
    daily(store, "2026-10-14",
          work="Poured slab on grade at Bldg A east half. Set forms.\n"
               "- Masons laid CMU at the pool house walls.",
          manpower=[{"company": "Sample Concrete", "trade": "Concrete",
                     "workers": 6,
                     "notes": "Poured slab on grade at Bldg A east half."},
                    {"company": "Sample Steel", "trade": "Steel",
                     "workers": 4}])
    daily(store, "2026-10-20", status="Draft",
          work="Roofers installed flashing at the north parapet.")
    daily(store, "2026-10-13", work="Last week's work is not in this one.",
          manpower=[{"company": "Sample Paint", "trade": "Painting",
                     "workers": 2}])


def test_l1_draft_from_daily_logs(store, tmp_path):
    _logs(store)
    rep = report(store)
    assert rep["progress"]            # NW-05: drafting from logs is now on
    rep["progress"] = []
    orp.draft_from_daily_logs(store, rep)
    assert [(b["text"], b["src"]) for b in rep["progress"]] == [
        ("Poured slab on grade at Bldg A east half.", "DL-0001"),
        ("Set forms.", "DL-0001"),                  # 2-word notes kept
        ("Masons laid CMU at the pool house walls.", "DL-0001"),
        ("Roofers installed flashing at the north parapet.", "DL-0002"),
        ("Crews on site: Sample Concrete, Sample Steel.", "DL-0001")]
    # with the option off, a new report waits for the PM
    store.delete(orp.COLL, rep["_id"])
    rep2 = orp.new_report(store, WE, online=False)
    assert len(rep2["progress"]) == 5                # drafted by itself
    rep2["progress"] = []
    rep2["options"]["draft_from_logs"] = False
    orp.autofill(store, rep2, online=False)
    assert not rep2["progress"]
    rep2["options"]["draft_from_logs"] = True
    orp.autofill(store, rep2, online=False)
    assert len(rep2["progress"]) == 5
    rep2["progress"][2]["include"] = False
    res, doc = build(store, rep2, tmp_path)
    t = doc[0].get_text()
    assert "Poured slab" in t and "Roofers installed" in t
    assert "Masons laid" not in t and "Last week" not in t


def test_l2_trades_from_manpower(store, tmp_path):
    _logs(store)
    rep = report(store)
    orp.draft_from_daily_logs(store, rep)
    assert {"Footings/Concrete", "Metal Work", "Masonry",
            "Roofing/Flashing"} <= set(rep["trades"])
    assert "Painting" not in rep["trades"]            # last week's log
    assert rep["trades_src"]["Metal Work"] == "DL-0001"
    orp.set_trade(rep, "Masonry", False)
    orp.draft_from_daily_logs(store, rep)              # a re-draft
    assert "Masonry" not in rep["trades"]
    orp.save(store, rep)
    nxt = orp.new_report(store, WE + timedelta(days=7), online=False)
    assert "Masonry" not in nxt["trades"] and "Masonry" in nxt["trades_off"]
    daily(store, "2026-10-22", work="Masons grouted the CMU walls.")
    orp.draft_from_daily_logs(store, nxt)
    assert "Masonry" not in nxt["trades"]


# ------------------------------------------------------------ local AI
def test_ai_draft_progress_scripted(store):
    _logs(store)
    rep = report(store)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return json.dumps({"bullets": [
            {"text": "Placed the Bldg A slab-on-grade (east half).",
             "facts": [1]},
            {"text": "Installed 300 feet of flashing at the north parapet.",
             "facts": [4]},                     # 300 isn't logged
            {"text": "Painted the lobby.", "facts": []}]})  # no source
    orp.ai_draft_progress(store, rep, ask=ask)
    p = prompts[0]
    assert "[1] (DL-0001, 10/14/2026) Poured slab on grade" in p
    assert "Use ONLY the facts" in p and "Last week" not in p
    got = [(b["text"], b["src"], b["include"]) for b in rep["progress"]]
    assert got[:2] == [
        ("Placed the Bldg A slab-on-grade (east half).", "DL-0001", True),
        ("Roofers installed flashing at the north parapet.", "DL-0002",
         True)]
    rest = got[2:]                      # the unused facts, left unticked
    assert ("Masons laid CMU at the pool house walls.", "DL-0001",
            False) in rest
    assert all(inc is False for _t, _s, inc in rest)
    assert not any("lobby" in b["text"] or "300" in b["text"]
                   for b in rep["progress"])
    assert rep["ai"]["fallback"] is None
    assert "Footings/Concrete" in rep["trades"]


def test_ai_draft_progress_falls_back(store):
    _logs(store)
    rep = report(store)

    def broken(prompt):
        raise RuntimeError("Can't reach Ollama.")
    orp.ai_draft_progress(store, rep, ask=broken)
    assert [b["src"] for b in rep["progress"]] == [
        "DL-0001", "DL-0001", "DL-0001", "DL-0002", "DL-0001"]
    assert "Ollama" in rep["ai"]["fallback"]
    rep2 = report(store)
    orp.ai_draft_progress(store, rep2, ask=lambda p: "not json at all")
    assert len(rep2["progress"]) == 5 and rep2["ai"]["fallback"]


# ------------------------------------------------------------ photos from DLs
def test_photos_pulled_from_the_weeks_daily_logs(store, tmp_path):
    refs = [store.attach(make_photo(tmp_path, f"dl{i}.jpg", seed=i,
                                    when=None)) for i in range(3)]
    daily(store, "2026-10-14", photos=refs[:2])
    daily(store, "2026-10-12", photos=refs[2:])             # last week
    rep = report(store)
    assert [p["src"] for p in rep["photos"]] == ["DL-0001", "DL-0001"]
    # no EXIF: the log's date, said so
    assert rep["photos"][0]["taken"].startswith("2026-10-14")
    assert rep["photos"][0]["taken_src"] == "log"
    orp.autofill(store, rep, online=False)                  # no duplicates
    assert len(rep["photos"]) == 2


# ------------------------------------------------------------ all on
def test_all_options_on(store, tmp_path, monkeypatch):
    _schedule(store)
    _logs(store)
    sheet = _sheet(tmp_path)
    rep = report(store)
    add_photos(store, rep, tmp_path, 7)
    rep["photos"][0]["pin"] = {"sheet": sheet, "page": 0, "x": 120,
                               "y": 120}
    rep["work_areas"] = [{"sheet": sheet, "page": 0,
                          "pts": [[60, 60], [300, 60], [300, 200]],
                          "label": "Bldg A", "note": "Example."}]
    rep["before_candidates"] = orp.add_photos(store, {"photos": []}, [
        make_photo(tmp_path, "old.jpg", seed=99)])
    rep["before_candidates"][0]["pin"] = {"sheet": sheet, "page": 0,
                                          "x": 125, "y": 118}
    orp.accept_pairs(rep)
    rep["decisions"] = [{"text": "Select tile", "due": "2026-10-21",
                         "done": False}]
    rep["progress"] = [{"text": "Example bullet " * 30, "include": True,
                        "src": "typed"} for _ in range(12)]
    for k, v in orp.DEFAULT_OPTIONS.items():
        if isinstance(v, bool):
            rep["options"][k] = True
    rep["options"]["photos_per_page"] = 6
    res, doc = build(store, rep, tmp_path)
    for n in ("page1", "page1b", "summary", "lookahead", "photos",
              "key_plan", "work_areas", "before_after", "rfi_log",
              "submittal_log", "co_log", "weather_log", "forecast"):
        assert n in names(res), n
    assert pages_of(res, "photos") == [names(res).index("photos") + 1,
                                       names(res).index("photos") + 2] or \
        len(pages_of(res, "photos")) == 2
    for p in doc:
        assert (round(p.rect.width), round(p.rect.height)) in \
            ((792, 612), (612, 792))
        assert p.rotation == 0
        assert p.first_annot is None and p.first_widget is None
        box = p.rect + (-1, -1, 1, 1)
        for b in p.get_text("dict")["blocks"]:
            if b.get("type") == 0:
                assert fitz.Rect(b["bbox"]) in box, (p.number, b["bbox"])
    assert "Change Orders" in doc[0].get_text()


# ------------------------------------------------------------ size
def test_estimate_size_follows_the_preset(store, tmp_path):
    rep = report(store)
    add_photos(store, rep, tmp_path, 8, size=(1600, 1200))
    sizes = {p: orp.estimate_size(store, rep, p)
             for p in ("original", "print", "email", "small")}
    assert sizes["print"] > sizes["email"] > sizes["small"] > 0
    res, doc = build(store, rep, tmp_path)
    assert res["photo_bytes"] < res["bytes"]
    assert math.isfinite(sizes["email"])


def test_original_preset_prints_a_turned_phone_photo_upright(store,
                                                              tmp_path):
    p = str(tmp_path / "phone.jpg")
    ex = Image.Exif()
    ex[0x0112] = 6                       # stored sideways, shown upright
    ex[0x0132] = "2026:10:14 14:40:00"
    Image.effect_noise((400, 300), 60).convert("RGB").save(p, "JPEG",
                                                           exif=ex)
    rep = report(store, size_preset="original")
    orp.add_photos(store, rep, [p])
    res, doc = build(store, rep, tmp_path)
    page = doc[pages_of(res, "photos")[0]]
    imgs = [(i[2], i[3]) for i in page.get_images(full=True)]
    assert (300, 400) in imgs and (400, 300) not in imgs
    # no EXIF (GPS) carried into the PDF
    xref = page.get_images(full=True)[0][0]
    assert b"Exif" not in doc.xref_stream_raw(xref)[:4096]


def test_captions_still_fill_4_by_3_photos(store, tmp_path):
    rep = report(store, captions=True)
    add_photos(store, rep, tmp_path, 1)
    res, doc = build(store, rep, tmp_path)
    frames = [d["rect"] for d in doc[1].get_drawings()
              if color_close(d.get("color"), FRAME)]
    cell = orp.photo_cells(4, True)[0]
    assert len(frames) == 1
    assert all(close(a, b, 1.0) for a, b in zip(frames[0], cell))


# ------------------------------------------------- review 0.12.35 #6-#9
def _word_after(page, *label):
    """The word right of the label words on the same line."""
    words = page.get_text("words")
    n = len(label)
    for i in range(len(words) - n + 1):
        if tuple(w[4] for w in words[i:i + n]) == label:
            last = words[i + n - 1]
            right = [w for w in words if abs(w[3] - last[3]) < 2.0 and
                     w[0] > last[2] - 0.5]
            return min(right, key=lambda w: w[0])[4] if right else None
    return None


def _row(page, label):
    """The words right of a label cell on the same line, left to right."""
    words = page.get_text("words")
    lab = next(w for w in words if w[4] == label)
    return [w[4] for w in sorted(words, key=lambda w: w[0])
            if abs(w[3] - lab[3]) < 2.0 and w[0] > lab[2]]


def test_typed_rain_survives_a_weather_repull(store, tmp_path, monkeypatch):
    store.set_setting("location", "Example, SC")
    store.set_setting("project_start", "2026-10-01")
    pulls = {"2026-10-06": 0.10, "2026-10-07": 0.0}
    monkeypatch.setattr(weather, "history", lambda place, a, b: [
        {"date": d, "rain_in": v, "high": 70, "low": 50}
        for d, v in sorted(pulls.items()) if a <= d <= b], raising=False)
    monkeypatch.setattr(weather, "forecast", lambda place, days=10: [],
                        raising=False)
    rep = orp.new_report(store, WE, online=False)
    orp.autofill(store, rep, online=True, today=WE + timedelta(days=1))
    day = next(d for d in rep["weather"]["days"] if d["date"] == "2026-10-06")
    day.update(rain_in=1.25, tracked=True, claimed=True, edited=True,
               source="typed")                  # typed from the rain gauge
    orp.autofill(store, rep, online=True, today=WE + timedelta(days=1))
    day = next(d for d in rep["weather"]["days"] if d["date"] == "2026-10-06")
    assert day["rain_in"] == 1.25 and day["source"] == "typed"
    assert day["download_in"] == 0.10
    res, doc = build(store, rep, tmp_path)
    log_text = " ".join(text_of(doc, pages_of(res, "weather_log")).split())
    assert "typed 1.25 in (download 0.10 in)" in log_text


def test_weather_totals_one_source(store, tmp_path):
    """3 tracked / 1 claimed in the day list, a stale typed claimed total
    of 3: page 1, the weather log and the gap line all say 3 and 1."""
    rep = report(store, weather_gap=True)
    days = [{"date": "2026-10-12", "rain_in": 0.9},     # Monday
            {"date": "2026-10-13", "rain_in": 0.8},
            {"date": "2026-10-14", "rain_in": 0.7}]
    for i, d in enumerate(days):
        d.update(tracked=True, claimed=i == 0, edited=True, note="")
    rep["weather"].update(days=days, threshold_in=0.5, impacted=3,
                          claimed=3)
    assert orp.weather_counts(rep) == (3, 1)
    res, doc = build(store, rep, tmp_path)
    p1 = doc[0]
    t1 = " ".join(p1.get_text().split())
    assert "IMPACTED WEATHER DAYS: 3" in t1
    assert _word_after(p1, "CLAIMED", "WEATHER", "DAYS:") == "1"
    assert "3 impacted vs 1 claimed" in t1
    assert orp.gap_line(rep).startswith("3 impacted vs 1 claimed")
    wl = doc[pages_of(res, "weather_log")[0]]
    # Tracked (not claimed) | Claimed | Actual
    assert _row(wl, "Total")[:3] == ["2.00", "1.00", "3.00"]


def test_pdf_fonts_embedded_and_subset(store, tmp_path):
    """Every font in the default report is the embedded Liberation Sans
    subset - no base-14 (non-embedded) font."""
    from app.pm import owner_report_logs as orl
    rep = report(store, captions=True, weather_gap=True, counts=True)
    add_photos(store, rep, tmp_path, 2)
    rep["progress"] = [{"text": "Set trusses at Bldg A.", "include": True,
                        "src": "typed"}]
    rep["forecast"] = {"mode": "table", "rows": [
        {"date": "2026-10-21", "sky": "Rain", "high": 70, "low": 55,
         "rain_chance": 60, "rain_in": 0.4, "wind": 8}],
        "as_of": "2026-10-20"}
    res, doc = build(store, rep, tmp_path)
    full = os.path.getsize(os.path.join(orl.font_dir(),
                                        "LiberationSans-Bold.ttf"))
    seen = set()
    for p in doc:
        fonts = doc.get_page_fonts(p.number)
        if p.get_text().strip():
            assert fonts, p.number
        for xref, ext, _typ, base, *_ in fonts:
            assert ext != "n/a", (p.number, base)         # embedded
            assert "LiberationSans" in base.replace(" ", ""), (p.number, base)
            if xref not in seen:
                seen.add(xref)
                assert len(doc.extract_font(xref)[3]) < full / 2, base
    bold = {sp["font"] for sp in spans(doc[0])
            if sp["text"].startswith("IMPACTED")}
    assert bold and all("Bold" in f for f in bold)


def _site_photos(tmp_path, n, w=4032, h=3024):
    """Made-up 12 MP photos that JPEG like real ones: smooth colour fields
    under noisy texture at three detail levels (a plain wall, a site, a
    gravel close-up), each file different."""
    import numpy as np
    from PIL import ImageChops

    def field(seed):
        r = np.random.default_rng(seed)
        return Image.fromarray(r.integers(0, 256, (6, 8, 3),
                                          dtype=np.uint8)).resize(
            (w, h), Image.BICUBIC)
    tex = []
    for k, amp in enumerate((12.0, 28.0, 50.0)):
        a = np.random.default_rng(100 + k).normal(128, amp, (h // 2, w // 2))
        tex.append(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
                   .resize((w, h), Image.BILINEAR).convert("RGB"))
    cols = [field(s) for s in range(4)]
    paths = []
    for i in range(n):
        t = tex[i % 3]
        if (i // 3) % 2:
            t = t.transpose(Image.FLIP_LEFT_RIGHT)
        img = ImageChops.add(Image.blend(cols[i % 4], cols[(i + 1) % 4],
                                         0.3), t, offset=-128)
        p = str(tmp_path / f"site{i:02d}.jpg")
        img.save(p, "JPEG", quality=92)
        paths.append(p)
    return paths


def test_estimate_size_within_25_percent_of_the_real_pdf(store, tmp_path):
    """Review 0.12.35 #9: the estimate vs the built PDF for all four
    presets, 12 MP phone-size photos at three detail levels. 16 photos,
    not 32: the estimate really encodes 3 of them whatever the count, so
    16 already has 13 photos guessed from that trial (4 photo pages, every
    cell position, every detail level), and the four real builds of 32
    twelve-megapixel photos would take about a minute."""
    rep = report(store)
    orp.add_photos(store, rep, _site_photos(tmp_path, 16))
    for preset in ("email", "print", "small", "original"):
        orp._trials.clear()
        est = orp.estimate_size(store, rep, preset)
        rep["options"]["size_preset"] = preset
        real = orp.build_pdf(store, rep)["bytes"]
        assert 0.75 * real <= est <= 1.25 * real, (preset, est, real)


# ------------------------------------------- review: weather precedence
def test_recorded_rain_day_survives_later_weeks(store, monkeypatch):
    """Review #1 (t3.py): a Daily Log's morning weather (0.00 in) on 9/29
    overwrote the 1.2 in Open-Meteo recorded once that day was more than a
    week back, so the claimed day dropped out of the third report."""
    import copy as _copy
    store.set_setting("location", "Example, SC")
    store.set_setting("project_start", "2026-09-28")
    store.save_record("daily", {"date": "2026-09-29",
                                "weather": {"precip": "0.00", "high": "70"}})

    def hist(place, a, b):
        a, b = date.fromisoformat(a), date.fromisoformat(b)
        out = []
        while a <= b:
            out.append({"date": a.isoformat(), "high": 70, "low": 50,
                        "rain_in": 1.2 if a == date(2026, 9, 29) else 0.0})
            a += timedelta(days=1)
        return out
    monkeypatch.setattr(weather, "history", hist, raising=False)
    rep = orp.blank(store, date(2026, 10, 6))
    for n in range(4):
        we = date(2026, 10, 6) + timedelta(days=7 * n)
        if n:
            rep = orp.carry_over(_copy.deepcopy(rep), store, we)
        orp.fill_weather(store, rep, today=we + timedelta(days=1))
        day = {d["date"]: d for d in rep["weather"]["days"]}["2026-09-29"]
        assert day["rain_in"] == 1.2 and day["claimed"], (n, day)
        assert (rep["weather"]["impacted"], rep["weather"]["claimed"]) == \
            (1, 1)
    # offline, the stored day stays too (the log 0 doesn't win)
    orp.fill_weather(store, rep, online=False, today=date(2026, 10, 28))
    day = {d["date"]: d for d in rep["weather"]["days"]}["2026-09-29"]
    assert day["rain_in"] == 1.2 and day["claimed"]


def test_daily_log_rain_still_fills_days_not_stored(store):
    store.set_setting("project_start", "2026-10-12")
    store.save_record("daily", {"date": "2026-10-13",
                                "weather": {"precip": "0.80"}})
    rep = orp.blank(store, WE)
    orp.fill_weather(store, rep, online=False, today=WE)
    day = {d["date"]: d for d in rep["weather"]["days"]}["2026-10-13"]
    assert day["rain_in"] == 0.8 and day["claimed"]


# ------------------------------------- review: background job results
def _fake_job(store, rep, kind, work):
    """What the window does: copy at start, the job changes its copy, the
    result is folded back. Returns (copy, before) for the fold."""
    import copy as _copy
    before = _copy.deepcopy(rep.get("weather") or {})
    job = _copy.deepcopy(rep)
    work(job)
    return job, before


def test_weather_job_result_keeps_edits_made_meanwhile(store, monkeypatch):
    """Review #2: the job's copy used to replace the live report - bullets,
    decisions and day ticks typed while it ran were lost."""
    store.set_setting("location", "Example, SC")
    store.set_setting("project_start", "2026-10-12")
    monkeypatch.setattr(weather, "history", lambda place, a, b: [
        {"date": d, "rain_in": r} for d, r in
        (("2026-10-13", 0.9), ("2026-10-14", 0.7), ("2026-10-15", 0.0))
        if a <= d <= b], raising=False)
    monkeypatch.setattr(weather, "forecast", lambda place, days=10: [
        {"date": "2026-10-21", "rain_in": 0.1}], raising=False)
    rep = orp.blank(store, WE)
    rep["forecast"]["mode"] = "table"
    rep["weather"]["days"] = [{"date": "2026-10-13", "rain_in": 0.2,
                               "tracked": False, "claimed": False,
                               "note": ""}]
    job, before = _fake_job(store, rep, "weather", lambda r: (
        orp.fill_weather(store, r, today=WE),
        orp.fill_forecast(store, r, today=WE)))
    # meanwhile the PM types a bullet, a decision and unticks a day
    rep["progress"].append({"text": "Typed while it ran.", "include": True,
                            "src": "typed"})
    rep["decisions"] = [{"text": "Pick the tile", "done": False}]
    rep["weather"]["days"].append({"date": "2026-10-14", "rain_in": 0.7,
                                   "tracked": True, "claimed": False,
                                   "note": "Worked inside", "edited": True})
    orp.merge_job_result(store, rep, "weather", job, before)
    assert rep["progress"][-1]["text"] == "Typed while it ran."
    assert rep["decisions"] == [{"text": "Pick the tile", "done": False}]
    days = {d["date"]: d for d in rep["weather"]["days"]}
    assert days["2026-10-13"]["rain_in"] == 0.9 and \
        days["2026-10-13"]["claimed"]                       # the job's rain
    assert days["2026-10-14"]["claimed"] is False and \
        days["2026-10-14"]["note"] == "Worked inside"       # the PM's untick
    assert (rep["weather"]["impacted"], rep["weather"]["claimed"]) == (2, 1)
    assert rep["forecast"]["rows"] == [{"date": "2026-10-21",
                                        "rain_in": 0.1}]
    # nothing touched meanwhile: the job's weather is taken whole
    rep2 = orp.blank(store, WE)
    job2, before2 = _fake_job(store, rep2, "weather",
                              lambda r: orp.fill_weather(store, r, today=WE))
    orp.merge_job_result(store, rep2, "weather", job2, before2)
    assert rep2["weather"] == job2["weather"]


def test_two_jobs_each_fold_only_their_own_fields(store, monkeypatch):
    """Review #2: Update Weather + AI Draft at once - each result reaches
    its own fold and neither undoes the other."""
    store.set_setting("location", "Example, SC")
    store.set_setting("project_start", "2026-10-12")
    store.save_record("daily", {"date": "2026-10-14", "status": "Submitted",
                                "work": "Poured slab on grade at Bldg A."})
    monkeypatch.setattr(weather, "history", lambda place, a, b: [
        {"date": "2026-10-13", "rain_in": 1.0}], raising=False)
    rep = orp.blank(store, WE)
    rep["progress"] = [{"text": "Carried line.", "include": True,
                        "src": "carried"}]
    wjob, before = _fake_job(store, rep, "weather",
                             lambda r: orp.fill_weather(store, r, today=WE))
    ajob, _ = _fake_job(store, rep, "ai", lambda r: orp.ai_draft_progress(
        store, r, ask=lambda p: json.dumps({"bullets": [
            {"text": "Placed the slab at Bldg A.", "facts": [1]}]})))
    rep["progress"].append({"text": "Typed meanwhile.", "include": True,
                            "src": "typed"})
    orp.merge_job_result(store, rep, "weather", wjob, before)  # lands first
    orp.merge_job_result(store, rep, "ai", ajob)
    texts = [b["text"] for b in rep["progress"]]
    assert texts[:2] == ["Carried line.", "Typed meanwhile."]
    assert "Placed the slab at Bldg A." in texts
    assert rep["ai"]["fallback"] is None
    assert {d["date"]: d["rain_in"] for d in rep["weather"]["days"]} \
        ["2026-10-13"] == 1.0                     # not undone by the AI job


def test_new_report_can_skip_saving_for_the_gui_thread(store):
    """Review #3: the window builds the report off the GUI thread; saving
    there ran the store's listeners (Project Center widgets) off it."""
    calls = []
    store.listeners.append(lambda coll: calls.append(coll))
    rep = orp.new_report(store, WE, online=False, save_it=False)
    assert not rep.get("_id") and orp.COLL not in calls
    orp.save(store, rep)
    assert rep["_id"] and orp.COLL in calls
