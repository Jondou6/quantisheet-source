"""Owner report pack (HELD patch): the new sections drawn with the report's
own style, logs as of the report date, trades not ticked by firm names,
progress drafted by trade, the forecast page's source and holidays.
Made-up data only."""
from datetime import date

import fitz
import pytest

from app import settings
from app.pm import owner_report as orp
from app.pm import owner_report_logs as orl
from app.pm import owner_report_pack as pack
from app.pm.store import ProjectStore

WE = date(2026, 10, 20)
GREY = (0.851, 0.851, 0.851)


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


def report(store, **opts):
    rep = orp.new_report(store, WE, online=False)
    rep["options"].update(opts)
    return rep


def build(store, rep, tmp_path, name="r.pdf"):
    path = str(tmp_path / name)
    res = orp.build_pdf(store, rep, path)
    return res, fitz.open(path)


def names(res):
    return [m[0] for m in res["page_map"]]


def pages_of(res, name):
    m = next(m for m in res["page_map"] if m[0] == name)
    return list(range(m[1] - 1, (m[2] if len(m) > 2 else m[1])))


def spans(page):
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                yield sp


def daily(store, day, **kw):
    rec = {"date": day, "status": "Submitted"}
    rec.update(kw)
    return store.save_record("daily", rec)


def a_pack(rows=3):
    return {"sections": [
        {"key": "dash", "title": "DASHBOARD - STATUS AT A GLANCE",
         "place": "front", "footer": "Owner Summary", "blocks": [
             {"t": "rag", "items": [["Schedule", "Y", "8 days behind"],
                                    ["Safety", "G", "no injuries"]]},
             {"t": "kpis", "items": [["Percent complete", "1.4%", "earned"]]},
             {"t": "sample", "text": "allowance is a placeholder"}]},
        {"key": "budget", "title": "BUDGET AND BILLING", "place": "detail",
         "blocks": [{"t": "table", "title": "CASH FLOW",
                     "cols": [["Pay app", 60], ["Note", 400],
                              ["Amount", 90, "right"]],
                     "rows": [[f"#{i}", "word " * (40 if i == 0 else 3),
                               "$1,000"] for i in range(rows)]}]},
        {"key": "dist", "title": "DISTRIBUTION LIST", "place": "end",
         "blocks": [{"t": "table", "cols": [["Name", 1], ["Copy", 1]],
                     "rows": [["Pat Example", "Email (PDF)"]]}]}]}


# ------------------------------------------------------------ pack pages
def test_pk01_off_by_default_order_unchanged(store, tmp_path):
    rep = report(store)
    rep["pack"] = a_pack()
    res, doc = build(store, rep, tmp_path)
    assert not any(n.startswith("pack_") for n in names(res))
    assert names(res)[0] == "page1"


def test_pk02_sections_in_their_places(store, tmp_path):
    rep = report(store, owner_pack=True, decisions=True, lookahead=False)
    rep["decisions"] = [{"text": "Approve the fill", "due": "2026-10-24"}]
    rep["pack"] = a_pack()
    res, doc = build(store, rep, tmp_path)
    n = names(res)
    assert n.index("page1") < n.index("pack_dash") < n.index("summary") \
        < n.index("pack_budget") < n.index("rfi_log") \
        < n.index("forecast") < n.index("pack_dist")


def test_pk03_same_page_style_as_the_report(store, tmp_path):
    rep = report(store, owner_pack=True)
    rep["pack"] = a_pack()
    res, doc = build(store, rep, tmp_path)
    for pno in pages_of(res, "pack_budget"):
        page = doc[pno]
        assert (page.rect.width, page.rect.height) == (792, 612)
        fonts = {sp["font"] for sp in spans(page)}
        assert fonts <= {"LiberationSans", "LiberationSans-Bold",
                         "LibSans", "LibSans-Bold"} or \
            all("Liberation" in f or "LibSans" in f for f in fonts)
        t = page.get_text()
        assert "Project Progress Report" in t
        assert "BUDGET AND BILLING" in t
    bars = [d for d in doc[pages_of(res, "pack_budget")[0]].get_drawings()
            if d.get("fill") and all(abs(a - b) < 0.02 for a, b in
                                      zip(d["fill"], GREY))]
    assert bars, "section bar in the report's grey"
    assert not res["unembedded_fonts"]


def test_pk04_footer_counts_each_label(store, tmp_path):
    rep = report(store, owner_pack=True)
    rep["pack"] = a_pack()
    res, doc = build(store, rep, tmp_path)
    t = doc[pages_of(res, "pack_dash")[0]].get_text()
    assert "Owner Summary" in t and "Page 1 of 1" in t
    assert "October 20, 2026" in t


def test_pk05_long_table_wraps_and_continues(store, tmp_path):
    rep = report(store, owner_pack=True)
    rep["pack"] = a_pack(rows=60)
    res, doc = build(store, rep, tmp_path)
    pn = pages_of(res, "pack_budget")
    assert len(pn) >= 2
    assert "CASH FLOW (continued)" in doc[pn[1]].get_text()
    assert "Note" in doc[pn[1]].get_text()           # heading repeated
    words = doc[pn[0]].get_text().count("word")
    assert words >= 40                                # nothing cut off
    assert "..." not in doc[pn[0]].get_text()


def test_pk06_sample_tag_red(store, tmp_path):
    rep = report(store, owner_pack=True)
    rep["pack"] = a_pack()
    res, doc = build(store, rep, tmp_path)
    sp = [s for s in spans(doc[pages_of(res, "pack_dash")[0]])
          if "[SAMPLE DATA]" in s["text"]]
    assert sp and sp[0]["color"] == 0xCC0000


def test_pk07_no_signature_block(store, tmp_path):
    rep = report(store, owner_pack=True)
    p = a_pack()
    p["sections"][2]["blocks"].append({"t": "signature"})   # not a type
    rep["pack"] = p
    res, doc = build(store, rep, tmp_path)
    t = " ".join(doc[i].get_text() for i in range(doc.page_count)).lower()
    assert "signature" not in t and "sign-off" not in t


def test_pk08_company_name_fits_logo_box(store, tmp_path):
    store.set_setting("contractor", "Ridgeview Constructors (fictional)")
    rep = report(store, owner_pack=True)
    rep["pack"] = a_pack()
    t = orp.load_template()
    t["company"] = {"name": "Ridgeview Constructors (fictional)",
                    "lines": []}
    path = str(tmp_path / "r.pdf")
    orp.build_pdf(store, rep, path, template=t)
    doc = fitz.open(path)
    txt = doc[1].get_text()
    assert "Ridgeview" in txt and "(fictional)" in txt
    assert "Constr..." not in txt


def test_pk09_percent_complete_from_pack(store, tmp_path):
    store.save_record("activity", {"name": "Clear site", "duration": 10,
                                   "start": "2026-09-01", "percent": 50})
    rep = report(store, owner_pack=True, schedule=True)
    rep["pack"] = dict(a_pack(), percent_complete=1.4)
    res, doc = build(store, rep, tmp_path)
    t = doc[pages_of(res, "summary")[0]].get_text()
    assert "1.4% (earned)" in t


# ------------------------------------------------------------ as of
def test_ao01_rfi_answered_later_is_open(store):
    r = store.save_record("rfi", {"subject": "Soils", "status": "Closed",
                                  "sent": "2026-10-19",
                                  "answered": "2026-10-24",
                                  "due": "2026-11-01"})
    store.save_record("rfi", {"subject": "Later", "status": "Open",
                              "sent": "2026-10-28"})
    v = orl.as_of_view("rfi", store.list("rfi"), date(2026, 10, 20))
    assert len(v) == 1
    assert v[0]["status"] == "Open" and not v[0].get("answered")
    assert store.get("rfi", r["_id"])["status"] == "Closed"   # untouched


def test_ao02_rfi_closed_date_is_answer_not_last_edit(store):
    store.save_record("rfi", {"subject": "Soils", "status": "Closed",
                              "sent": "2026-10-10",
                              "answered": "2026-10-15"})
    v = orl.as_of_view("rfi", store.list("rfi"), date(2026, 10, 20))
    assert v[0]["closed_on"] == "2026-10-15"
    assert orl._rfi_closed_on(v[0]) == "2026-10-15"


def test_ao03_events_as_they_stood(store):
    rfi = store.save_record("rfi", {"subject": "Soils", "status": "Open",
                                    "sent": "2026-10-20"})
    store.save_record("event", {"title": "Undercut", "status": "Approved",
                                "rfi": rfi["_id"], "submitted": "2026-10-26",
                                "approved": "2026-11-10", "co_no": "CO-001"})
    store.save_record("event", {"title": "Storage room", "status":
                                "Approved", "submitted": "2027-01-08",
                                "approved": "2027-01-20"})
    v = orl.as_of_view("event", store.list("event"), date(2026, 10, 20),
                       store.list("rfi"))
    assert [e["title"] for e in v] == ["Undercut"]
    assert v[0]["status"] == "Open" and not v[0].get("co_no")
    assert orl._co_totals(store, v)["approved"] == 0


def test_ao04_submittal_closed_without_return_is_open(store):
    store.save_record("submittal", {"title": "Steel shop drawings",
                                    "status": "Closed"})
    v = orl.as_of_view("submittal", store.list("submittal"),
                       date(2026, 10, 20))
    assert v[0]["status"] == "Open"


def test_ao05_logs_and_counts_use_the_view(store, tmp_path):
    store.save_record("rfi", {"subject": "Soils", "status": "Closed",
                              "sent": "2026-10-19",
                              "answered": "2026-10-24"})
    rep = report(store, as_of_logs=True, counts=True)
    res, doc = build(store, rep, tmp_path)
    t = doc[pages_of(res, "rfi_log")[0]].get_text()
    assert "Open" in t and "10/24/2026" not in t
    c = orl.counts(store, date(2026, 10, 20), {"as_of_logs": True})
    assert c["rfi"]["open"] == 1
    assert orl.counts(store, date(2026, 10, 20))["rfi"]["open"] == 0


# ------------------------------------------------------------ page 1
def test_tr01_firm_name_does_not_tick_a_trade(store):
    daily(store, "2026-10-19", work="Schedule updates sent to Granite Line "
          "Concrete and Red Clay Sitework.", manpower=[
              {"company": "Granite Line Concrete Inc", "trade": "Survey",
               "workers": 0}])
    rep = report(store)
    orp._tick_trades(store, rep)
    assert "Footings/Concrete" not in rep["trades"]


def test_tr02_clear_and_grub_ticks_site_work(store):
    daily(store, "2026-10-19", work="Clear and grub east half; topsoil "
          "stripping started.")
    rep = report(store)
    orp._tick_trades(store, rep)
    assert rep["trades"] == ["Site Work"]


def test_pr01_progress_by_trade_no_repeats(store):
    daily(store, "2026-10-19",
          work="Crew resumed clear and grub in the east half, removing "
               "stumps. Owner representative site walk at 10:00. (TEST DATA)",
          manpower=[{"company": "Red Clay Sitework LLC",
                     "trade": "Sitework - operators", "workers": 3,
                     "notes": "Clear and grub east half: stump removal."},
                    {"company": "Red Clay Sitework LLC", "trade": "Trucking",
                     "workers": 2, "notes": "Hauled 8 loads of debris off "
                                            "site."},
                    {"company": "Ridgeview Constructors", "trade":
                     "Supervision", "workers": 2,
                     "notes": "Superintendent and assistant superintendent"}])
    daily(store, "2026-10-20",
          work="Clear and grub continued in the east half.",
          manpower=[{"company": "Red Clay Sitework LLC",
                     "trade": "Sitework - operators", "workers": 3,
                     "notes": "8 truckloads of debris hauled off site."}])
    rep = report(store, progress_by_trade=True)
    orp.draft_from_daily_logs(store, rep)
    texts = [b["text"] for b in rep["progress"]]
    assert texts[0].startswith("Site Work - crews this week: Red Clay "
                               "Sitework")
    mon = next(t for t in texts if t.startswith("Site Work - Mon 10/19"))
    assert "stump removal" not in mon            # same as the work text
    assert "Hauled 8 loads" in mon
    tue = next(t for t in texts if t.startswith("Site Work - Tue 10/20"))
    assert "continued in the east half" in tue   # a new day's work stays
    assert "truckloads" in tue                   # not a repeat: other day
    assert texts[-1].startswith("General / site conditions - Mon 10/19")
    assert not any("Superintendent and assistant" in t for t in texts)
    assert not any("TEST DATA" in t for t in texts)
    assert rep["trades"] == ["Site Work"]


def test_pr02_typed_bullets_stay_first(store):
    daily(store, "2026-10-19", work="Clear and grub in the east half.")
    rep = report(store, progress_by_trade=True)
    rep["progress"] = [{"text": "Typed by the PM.", "include": True,
                        "src": "typed"}]
    orp.draft_from_daily_logs(store, rep)
    assert rep["progress"][0]["text"] == "Typed by the PM."
    assert len(rep["progress"]) == 2          # no crews logged: no crew line


def test_sim01_similar():
    assert orp.similar("8 truckloads of clearing debris hauled off site.",
                       "Hauled 8 loads of clearing debris off site.")
    assert not orp.similar("Topsoil stockpile covered during the rain.",
                           "Repaired silt fence at the north line.")


# ------------------------------------------------------------ forecast
def test_fc01_source_and_holidays(tmp_path):
    doc = fitz.open()
    orl.add_forecast_page(doc, {"date": "2026-11-20"}, {
        "mode": "table", "source": "SAMPLE DATA typed (offline)",
        "holidays": ["2026-11-26"],
        "rows": [{"date": "2026-11-26", "sky": "Sunny", "rain_in": 0},
                 {"date": "2026-11-24", "sky": "Rain", "rain_in": 0.8}]})
    t = doc[0].get_text()
    assert "source: SAMPLE DATA typed (offline)" in t
    assert "Open-Meteo" not in t
    assert "Holiday" in t and "At risk" in t


def test_fc02_default_source_unchanged(tmp_path):
    doc = fitz.open()
    orl.add_forecast_page(doc, {"date": "2026-11-20"}, {"mode": "table",
                                                        "rows": []})
    assert "source: Open-Meteo" in doc[0].get_text()


# ------------------------------------------------- weekly / monthly presets
def preset_pack():
    pk = a_pack()
    for s in pk["sections"]:
        s["presets"] = ["full", "monthly"]
    pk["sections"].append(
        {"key": "wk_done", "title": "WORK COMPLETED THIS WEEK BY TRADE",
         "place": "weekly", "footer": "Weekly Detail", "presets": ["weekly"],
         "blocks": [{"t": "table", "cols": [["Trade", 1], ["Work", 4]],
                     "rows": [["Site Work", "Clear and grub"]]}]})
    pk["weekly"] = {
        "status": [["Schedule", "Y", "8 wd behind baseline"],
                   ["Cost", "Y", "1 PCO"], ["Safety", "G", "no injuries"]],
        "summary": ["Week 3 on site.", "Forecast holds the contract date."],
        "actions": [[str(i), f"Decision number {i}", "11/24/2026", f"R-{i}"]
                    for i in range(1, 5)],
        "allowance": {"label": "Nov allowance", "days": 3, "sample": True},
        "weather_note": "2 adverse days of 3."}
    pk["monthly"] = {"title": "Project Progress Report - Monthly Appendix"}
    return pk


def photo(store, tmp_path, name="p1.png"):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
    pix.clear_with(200)
    path = str(tmp_path / name)
    pix.save(path)
    return path


def test_pp01_weekly_preset_order(store, tmp_path):
    rep = report(store, owner_pack=True, report_preset="weekly",
                 captions=True, key_plan=True, co_log=True, lookahead=True)
    rep["pack"] = preset_pack()
    orp.add_photos(store, rep, [photo(store, tmp_path)])
    rep["photos"][0]["caption"] = "Example caption."   # G09 warns if none
    res, doc = build(store, rep, tmp_path)
    assert names(res) == ["page1", "pack_wk_done", "photos"]
    assert res["pages"] == 3 and not res["warnings"]


def test_pp02_weekly_page1_content(store, tmp_path):
    rep = report(store, owner_pack=True, report_preset="weekly")
    rep["pack"] = preset_pack()
    res, doc = build(store, rep, tmp_path)
    t = doc[0].get_text()
    for s in ("REPORT #", "JOB NUMBER", "STATUS", "SCHEDULE: YELLOW",
              "SAFETY: GREEN", "WORK IN PROGRESS", "INCLEMENT WEATHER DAYS",
              "IMPACTED WEATHER DAYS: 0", "CLAIMED WEATHER DAYS: 0",
              "NOV ALLOWANCE: 3", "[SAMPLE DATA]", "EXECUTIVE SUMMARY",
              "Week 3 on site. Forecast holds", "OWNER ACTION REQUIRED",
              "Decision number 3"):
        assert s in t, s
    assert "Decision number 4" not in t            # top 3 only
    assert "CURRENT PROGRESS" not in t
    assert doc[0].rect.width == 792


def test_pp03_monthly_preset_order(store, tmp_path):
    rep = report(store, owner_pack=True, report_preset="monthly",
                 co_log=True, captions=True)
    rep["pack"] = preset_pack()
    orp.add_photos(store, rep, [photo(store, tmp_path)])
    res, doc = build(store, rep, tmp_path)
    n = names(res)
    assert "page1" not in n and "photos" not in n and "pack_wk_done" not in n
    assert n.index("pack_dash") < n.index("pack_budget") < \
        n.index("rfi_log") < n.index("forecast") < n.index("pack_dist")
    assert "Monthly Appendix" in doc[0].get_text()


def test_pp04_full_report_ignores_preset_only_sections(store, tmp_path):
    rep = report(store, owner_pack=True)
    rep["pack"] = preset_pack()
    res, doc = build(store, rep, tmp_path)
    n = names(res)
    assert n[0] == "page1" and "pack_dash" in n and "pack_wk_done" not in n
    assert pack.sections(rep, "weekly", "weekly")[0]["key"] == "wk_done"
    assert pack.sections(rep, None, "")[0]["key"] == "dash"


def test_pp05_unknown_preset_builds_full(store, tmp_path):
    rep = report(store, owner_pack=True, report_preset="quarterly")
    rep["pack"] = preset_pack()
    res, doc = build(store, rep, tmp_path)
    assert names(res)[0] == "page1"
    assert sum("Unknown report preset" in w for w in res["warnings"]) == 1


def test_pp06_preset_footers_use_document_pages(store, tmp_path):
    rep = report(store, owner_pack=True, report_preset="weekly")
    rep["pack"] = preset_pack()
    res, doc = build(store, rep, tmp_path)
    t = doc[pages_of(res, "pack_wk_done")[0]].get_text()
    assert "Weekly Detail" in t and f"Page 2 of {res['pages']}" in t


def test_pp07_preset_off_without_owner_pack(store, tmp_path):
    rep = report(store, report_preset="weekly")
    rep["pack"] = preset_pack()
    res, doc = build(store, rep, tmp_path)
    assert names(res)[0] == "page1" and "pack_wk_done" not in names(res)
