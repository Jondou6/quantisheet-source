"""Owner report gaps G01-G30 (HELD gaps patch on top of the owner report
pack): as-of logs, weather rows / notices / allowance / granted time,
dashboard and drafted summary, proposed owner actions, schedule, budget,
PCO log, photos, progress by trade, site activity, permits, RFI sent date,
long-lead, risks, S-curve, contingency, meetings, offline forecast, page
references, before/after, logistics, distribution, data notes and the
weekly / monthly preset control. Offline, rule-based, fictional data."""
import os
from datetime import date

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                      # noqa: E402
from app.pm import owner_report as orp                        # noqa: E402
from app.pm import owner_report_logs as orl                   # noqa: E402
from app.pm import schema                                     # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402

WE = date(2026, 11, 20)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    monkeypatch.setenv("QUANTISHEET_NO_OPEN", "1")
    s = ProjectStore(str(tmp_path / "Job"))
    s.data["name"] = "Harbor Point Clubhouse (example)"
    for k, v in {"number": "26-101", "project_start": "2026-11-02",
                 "data_date": "2026-11-19", "holidays": ["2026-11-26"],
                 "contract_finish": "2027-03-31",
                 "contract_final_completion": "2027-04-30",
                 "ld_per_day": 1000, "owner_pays_days": 30,
                 "weather_allowance": {"2026-11": 2, "2026-12": 3},
                 "crew_plan": {"Sitework - operators": 3},
                 "owner_contingency_pct": 5,
                 "sample_settings": ["crew_plan"]}.items():
        s.set_setting(k, v)
    job(s)
    return s


def rec(s, coll, **kw):
    return s.save_record(coll, kw)


def job(s):
    for n, co, role, trade in (
            ("Pat Example", "Owner Co (example)", "Owner", None),
            ("Alex Sample", "Design Co (example)", "Architect", None),
            ("Jordan Test", "Builder Co (example)", "General Contractor",
             None),
            ("Sam Grader", "Red Dirt Sitework (example)", "Subcontractor",
             "Sitework"),
            ("Ira Beam", "Tall Oak Steel (example)", "Subcontractor",
             "Structural steel")):
        rec(s, "member", name=n, company=co, role=role, trade=trade)
    rec(s, "commitment", vendor="Sam Grader", title="Sitework",
        lines=[{"description": "Sitework", "amount": 200000}],
        insurance_expires="2027-12-31")
    rec(s, "commitment", vendor="Ira Beam", title="Steel",
        lines=[{"description": "Structural steel", "amount": 300000}],
        insurance_expires="2027-01-15")
    for i, (d, v) in enumerate((("General conditions", 100000),
                                ("Sitework", 200000),
                                ("Structural steel", 300000),
                                ("Fee", 50000)), 1):
        rec(s, "contract", item=str(i), description=d, scheduled=v)
    A = lambda **kw: rec(s, "activity", **kw)                   # noqa
    A(name="Notice to proceed", duration=0, start="2026-11-02",
      status="Complete", percent=100, baseline_start="2026-11-02",
      baseline_finish="2026-11-02", responsible="Jordan Test")
    A(name="Clear and grub", duration=10, preds=[{"id": "A0001"}],
      status="In Progress", percent=50, actual_start="2026-11-04",
      baseline_start="2026-11-03", baseline_finish="2026-11-16",
      responsible="Sam Grader", area="Site")
    A(name="Steel shop drawings submit/approve", duration=10,
      preds=[{"id": "A0001"}], area="Procurement", responsible="Ira Beam",
      baseline_start="2026-11-03", baseline_finish="2026-11-16")
    A(name="Fabricate and deliver steel", duration=20,
      preds=[{"id": "A0003"}], area="Procurement", responsible="Ira Beam")
    A(name="Erect structural steel", duration=15,
      preds=[{"id": "A0002"}, {"id": "A0004"}], responsible="Ira Beam",
      area="Building", baseline_start="2027-01-04",
      baseline_finish="2027-01-22")
    A(name="Substantial completion", duration=0, preds=[{"id": "A0005"}],
      responsible="Jordan Test", baseline_finish="2027-01-22")
    A(name="Final completion", duration=0, preds=[{"id": "A0006"}],
      responsible="Jordan Test", baseline_finish="2027-02-05")
    crews = lambda h=8: [                                       # noqa
        {"company": "Red Dirt Sitework (example)",
         "trade": "Sitework - operators", "workers": 3, "hours": h,
         "location": "East area", "notes": "Clear and grub east area."},
        {"company": "Builder Co (example)", "trade": "Supervision",
         "workers": 1, "hours": 9, "location": "Site",
         "notes": "Superintendent"}]
    for d, hi, lo, sky, rain in (("2026-11-16", 56, 38, "Cloudy", 0.05),
                                 ("2026-11-17", 58, 40, "Cloudy", 0.0),
                                 ("2026-11-18", 51, 44, "Rain", 0.6),
                                 ("2026-11-19", 60, 38, "Sunny", 0.0),
                                 ("2026-11-20", 55, 37, "Sunny", 0.0)):
        kw = {"date": d, "status": "Submitted",
              "weather": {"high": str(hi), "low": str(lo), "sky": sky,
                          "precip": str(rain)},
              "manpower": crews(4 if d == "2026-11-18" else 8),
              "work": "Clear and grub continued. Granite Concrete called "
                      "about the schedule (TEST DATA)",
              "safety": "Toolbox talk: mud. No incidents, no near misses."}
        if d == "2026-11-18":
            kw["delays"] = [{"cause": "Weather", "hours": 4,
                             "description": "Rain, too wet to grade"}]
        if d == "2026-11-20":
            kw.update(inspections_note="Proof roll at pad FAILED at grid "
                                       "B-2; testing agency.",
                      equipment=[{"item": "D6 dozer", "hours": 8}],
                      deliveries=[{"item": "Silt fence", "qty": "10 rolls",
                                   "vendor": "Supply Co (example)"}],
                      visitors=[{"name": "Lee Sampleton",
                                 "company": "Test Lab (example)",
                                 "purpose": "Proof roll"}])
        rec(s, "daily", **kw)
    r1 = rec(s, "rfi", subject="Soft soils at pad", question="Undercut?",
             to="Alex Sample", sent="2026-11-20", due="2026-12-01",
             answered="2026-11-24", answer="24 in.", status="Closed",
             cost_impact="Yes", schedule_impact="Yes")
    rec(s, "rfi", subject="Curb size", question="Which curb?",
        to="Alex Sample", sent="2026-11-02", due="2026-11-09",
        status="Open", cost_impact="Undetermined",
        schedule_impact="Undetermined")
    rec(s, "event", title="Undercut at pad (RFI-001)", rfi=r1["_id"],
        lines=[{"description": "Undercut", "cost": 10000, "markup": 10}],
        status="Approved", days=2, submitted="2026-11-26",
        approved="2026-12-10", co_no="CO-001")
    rec(s, "delay", title="Rain delay", cause="Weather",
        event_start="2026-11-18", event_end="2026-11-18",
        notice_date="2026-11-19", days_requested=1, status="Open")
    rec(s, "delay", title="Undercut delay", cause="Owner change or decision",
        event_start="2026-11-20", notice_date="2026-11-25",
        days_requested=2, days_granted=2, status="Granted")
    rec(s, "payapp", period_to="2026-11-30", status="Certified",
        retainage_work=10, lines=[
            {"item": "1", "description": "General conditions",
             "this_period": 10000, "stored": 0},
            {"item": "2", "description": "Sitework", "this_period": 20000,
             "stored": 0}])
    rec(s, "payapp", period_to="2026-12-31", status="Draft",
        retainage_work=10, lines=[
            {"item": "2", "description": "Sitework", "this_period": 50000,
             "stored": 0}])
    rec(s, "issue", title="Owner furniture date", assignee="Pat Example",
        due="2026-11-27", status="Open")
    rec(s, "punch", title="Touch-up paint", due="2027-08-20", status="Open")
    rec(s, "meeting", title="OAC meeting #2", date="2026-11-18",
        time="10:00", location="Site trailer",
        attendees=[{"name": "Pat Example", "company": "Owner Co (example)",
                    "present": "Yes"}],
        topics=[{"no": "2.1", "topic": "Soils", "discussion": "Pending RFI",
                 "owner": "Alex Sample", "status": "Open"}])
    rec(s, "meeting", title="OAC meeting #3", date="2026-12-02",
        time="10:00", location="Site trailer")
    rec(s, "submittal", title="Structural steel shop drawings",
        spec="05 12 00", status="Open", required_on_site="2027-01-04")


def report(store, **opts):
    rep = orp.new_report(store, WE, online=False)
    rep["options"].update(opts)
    return rep


def auto(store, **opts):
    from app.pm import owner_report_auto as ora
    rep = report(store, **opts)
    return ora, rep, ora.facts(store, rep)


def pdf_text(store, rep, tmp_path, name="r.pdf"):
    res = orp.build_pdf(store, rep, str(tmp_path / name))
    doc = fitz.open(str(tmp_path / name))
    return res, doc, "\n".join(p.get_text() for p in doc)


def keys(res):
    return [m[0] for m in res["page_map"]]


# --------------------------------------------------------------- G01
def test_g01_new_reports_print_logs_as_of(store):
    rep = report(store)
    assert orp.options(rep)["as_of_logs"] is True
    c = orl.counts(store, WE, orp.options(rep))
    assert c["rfi"]["open"] == 2                   # RFI-001 answered later


def test_g01_billing_punch_and_left_out_note(store):
    ora, rep, F = auto(store)
    assert F["billing"]["billed"] == 0             # certified for 11/30
    assert F["punch_open"] == 0                    # dated 2027
    lo = " ".join(F["left_out"])
    assert "CE-001" in lo and "RFI-001 answer" in lo and "D-002" in lo


# --------------------------------------------------------------- G02
def test_g02_fill_weather_ignores_the_computer_clock(store):
    rep = report(store)
    orp.fill_weather(store, rep, online=False, today=date(2026, 10, 29))
    days = {d["date"]: d for d in rep["weather"]["days"]}
    assert "2026-11-18" in days and days["2026-11-18"]["tracked"]
    assert rep["weather"]["as_of"] == "2026-11-20"


def test_g02_claimed_comes_from_delay_notices(store):
    rep = report(store)
    rep["weather"]["days"] = [{"date": "2026-11-05", "rain_in": 0.8}]
    orp.fill_weather(store, rep, online=False, today=WE)
    days = {d["date"]: d for d in rep["weather"]["days"]}
    assert days["2026-11-18"]["claimed"] is True
    assert days["2026-11-05"]["tracked"] and not days["2026-11-05"]["claimed"]
    assert orp.weather_counts(rep) == (2, 1)


def test_g02_full_weather_rows_and_weekend_rain(store):
    from app.pm import owner_report_auto as ora
    rep = report(store)
    rep["weather"]["days"] = [{"date": "2026-11-15", "rain_in": 0.74,
                               "high": 52, "low": 45, "sky": "Rain"}]
    F = ora.facts(store, rep)
    rows = {r["date"]: r for r in F["weather"]["rows"]}
    r = rows[date(2026, 11, 18)]
    assert (r["high"], r["low"], r["sky"], r["rain"], r["lost"]) == \
        ("51", "44", "Rain", 0.6, 4.0)
    assert r["trades"] == "Sitework" and r["adverse"] and r["claimed"]
    assert r["claim_ref"] == "D-001"
    w = rows[date(2026, 11, 15)]
    assert w["rain"] == 0.74 and not w["workday"] and not w["adverse"]
    assert F["weather"]["rain_week"] == pytest.approx(0.65)
    assert F["weather"]["lost_week"] == 4.0


# --------------------------------------------------------------- G03
def test_g03_allowance_setting(store):
    ora, rep, F = auto(store)
    al = F["weather"]["allowance"]
    assert al[0]["month"] == "2026-11" and al[0]["allowed"] == 2
    assert al[0]["adverse"] == 1 and al[0]["excess"] == 0
    assert F["weather"]["claimed"] == 1 and F["weather"]["granted"] == 0


def test_g03_contract_finish_moves_only_by_granted_days(store):
    rep = report(store, schedule=True)
    rep["weather"]["days"] = [{"date": "2026-11-18", "rain_in": 0.6,
                               "tracked": True, "claimed": True}]
    st = orp.schedule_status(store, rep)
    assert st["weather_days"] == 0 and st["weather_src"] == "granted"
    assert st["contract_finish"] == date(2027, 3, 31)
    store.save_record("delay", {"title": "Rain granted", "cause": "Weather",
                                "event_start": "2026-11-10",
                                "notice_date": "2026-11-11",
                                "days_granted": 1, "status": "Granted",
                                "granted_on": "2026-11-13"})
    st = orp.schedule_status(store, rep)
    assert st["weather_days"] == 1
    assert st["contract_finish"] == date(2027, 4, 1)


# --------------------------------------------------------------- G04
def test_g04_dashboard_and_drafted_summary(store, tmp_path):
    ora, rep, F = auto(store)
    assert list(F["rag"]) == ["Schedule", "Cost", "Safety", "Quality",
                              "Weather", "Owner actions"]
    assert F["rag"]["Quality"][0] == "Y"           # failed proof roll
    s = ora.draft_summary(store, rep, F, short=True)
    assert 3 <= len(s) <= 4
    assert "substantial completion" in " ".join(s).lower()
    rep["options"].update(owner_pack=True, auto_pack=True)
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "DASHBOARD - STATUS AT A GLANCE" in t and "EXECUTIVE SUMMARY" in t
    rep["summary_text"] = "Edited by the PM before export."
    res, doc, t = pdf_text(store, rep, tmp_path, "b.pdf")
    assert "Edited by the PM before export." in t


# --------------------------------------------------------------- G05
def test_g05_owner_actions_proposed_with_impact(store):
    ora, rep, F = auto(store)
    props = ora.propose_decisions(store, rep, F)
    refs = " ".join(p["ref"] for p in props)
    assert "RFI-002" in refs                       # overdue RFI
    assert "D-001" in refs                         # open delay notice
    assert "I-001" in refs                         # owner issue
    for p in props:
        assert p["due"] and p["impact"] and p["text"]
    rep["decisions"] = [dict(props[0], text="Typed by the PM")]
    ora.merge_decisions(rep, props)
    assert rep["decisions"][0]["text"] == "Typed by the PM"
    assert len(rep["decisions"]) == len(props)


# --------------------------------------------------------------- G06
def test_g06_schedule_section(store, tmp_path):
    ora, rep, F = auto(store)
    sec = {s["key"]: s for s in ora.pack(store, rep, F)["sections"]}
    assert "schedule" in sec
    rep["options"].update(owner_pack=True, auto_pack=True)
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "SCHEDULE STATUS - MILESTONES, CRITICAL PATH AND RECOVERY" in t
    assert "03/31/2027" in t                       # contract SC
    assert "Critical path" in t and "A0003" in t
    assert "Recovery" in t


# --------------------------------------------------------------- G07
def test_g07_budget_billing_cash_flow(store):
    ora, rep, F = auto(store)
    b = F["billing"]
    assert b["retainage_rate"] == 0.10 and b["retainage_held"] == 0
    assert [c["gross"] for c in b["cash"]] == [30000, 50000]
    assert b["cash"][0]["pay"] == date(2026, 12, 30)
    assert F["contract_sum"] == 650000


# --------------------------------------------------------------- G08
def test_g08_exposure_log_and_pco_from_rfi(store):
    ora, rep, F = auto(store)
    ch = F["changes"]
    assert ch["approved"] == 0 and ch["revised"] == 650000
    assert [p["no"] for p in ch["pcos"]] == ["PCO-001"]
    assert ch["pcos"][0]["amount"] == pytest.approx(11000)
    assert [x["rfi"] for x in ch["tbd"]] == ["RFI-002"]
    rfi2 = next(r for r in store.list("rfi") if r["_no"] == "RFI-002")
    ev = ora.pco_from_rfi(store, rfi2)
    assert ev["rfi"] == rfi2["_id"] and ev["status"] == "Open"
    assert store.get("rfi", rfi2["_id"]).get("change_event") == ev["_id"]
    F = ora.facts(store, rep)
    assert [p["no"] for p in F["changes"]["pcos"]] == ["PCO-001", "PCO-002"]
    assert F["changes"]["tbd"] == []


# --------------------------------------------------------------- G09
def test_g09_captions_on_by_default_and_date_order(store, tmp_path):
    rep = report(store)
    assert orp.options(rep)["captions"] is True
    paths = []
    for i, day in enumerate(("2026-11-19", "2026-11-16")):
        p = str(tmp_path / f"p{i}.png")
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
        pix.clear_with(120 + i)
        pix.save(p)
        paths.append((p, day))
    for p, day in paths:
        orp.add_photos(store, rep, [p])
        rep["photos"][-1]["taken"] = day + "T09:00"
    orp.sort_photos(rep)
    assert [p["taken"][:10] for p in rep["photos"]] == ["2026-11-16",
                                                          "2026-11-19"]
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert any("no caption" in w for w in res["warnings"])


def test_g09_log_photo_caption_defaults(store, tmp_path):
    from app.pm import owner_report_auto as ora
    report(store)
    ph = {"ref": {"name": "x.jpg"}, "src": "DL-0005", "caption": "",
          "location": ""}
    ora.default_caption(store, ph)
    assert ph["caption"].startswith("Clear and grub east area")
    assert ph["location"] == "East area"


# --------------------------------------------------------------- G10
def test_g10_by_trade_ticks_from_crews_only(store):
    rep = report(store, progress_by_trade=True)
    orp.draft_from_daily_logs(store, rep)
    assert rep["trades"] == ["Site Work"]          # not "Concrete" text
    texts = [b["text"] for b in rep["progress"]]
    assert len(texts) == len(set(texts))


def test_g10_next_week_plan(store):
    ora, rep, F = auto(store)
    nos = [r["_no"] for r in F["next_week"]]
    assert "A0002" in nos and "A0003" in nos


# --------------------------------------------------------------- G11
def test_g11_three_week_lookahead(store):
    rep = report(store, lookahead=True, lookahead_weeks=3)
    a, b, rows = orp.lookahead_rows(store, rep)
    assert (b - a).days >= 18


# --------------------------------------------------------------- G12/G13
def test_g12_manpower_vs_plan_and_g13_safety(store):
    ora, rep, F = auto(store)
    m = F["manpower"]
    row = next(r for r in m["rows"] if r["trade"] == "Sitework - operators")
    assert row["worker_days"] == 15 and row["plan"] == 3
    assert m["manhours_week"] == 3 * 8 * 4 + 3 * 4 + 5 * 9
    s = F["safety"]
    assert s["recordables"] == 0 and s["toolbox_week"] == 5
    assert s["trir"] == 0.0


# --------------------------------------------------------------- G14
def test_g14_site_activity_and_failed_inspection_printed(store, tmp_path):
    rep = report(store, owner_pack=True, auto_pack=True)
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "FAILED" in t and "Proof roll at pad" in t
    assert "D6 dozer" in t and "Silt fence" in t and "Lee Sampleton" in t


# --------------------------------------------------------------- G15
def test_g15_permit_log(store, tmp_path):
    assert "permit" in schema.TOOLS
    store.save_record("permit", {"title": "Grading permit",
                                 "agency": "County (example)",
                                 "status": "Issued", "issued": "2026-10-20",
                                 "next_inspection": "Weekly SWPPP"})
    rep = report(store, owner_pack=True, auto_pack=True,
                 report_preset="monthly")
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "Grading permit" in t and "County (example)" in t


# --------------------------------------------------------------- G16
def test_g16_rfi_sent_field_and_aging(store):
    assert schema.field("rfi", "sent")["type"] == "date"
    ora, rep, F = auto(store)
    r2 = next(r for r in F["rfis"] if r["no"] == "RFI-002")
    assert r2["days_open"] == 18 and r2["overdue"]
    assert r2["bic"] == "Alex Sample (Architect)"


# --------------------------------------------------------------- G17
def test_g17_long_lead(store):
    ora, rep, F = auto(store)
    ll = F["long_lead"]
    assert ll[0]["submit"] == "A0003" and ll[0]["fabricate"] == "A0004"
    assert ll[0]["install"] == "A0005"
    assert isinstance(ll[0]["margin"], int)
    sub = F["submittals"][0]
    assert sub["bic"] == "Tall Oak Steel (example)" and sub["activity"] == \
        "A0003"


def test_g17_long_lead_label_field(store):
    """Known-broken fix: the PM names the long-lead item (activity field),
    instead of it always being the install step's name."""
    assert schema.field("activity", "long_lead_label")
    act = next(a for a in store.list("activity") if a["_no"] == "A0003")
    act["long_lead_label"] = "Example steel joists"
    store.save_record("activity", act)
    ora, rep, F = auto(store)
    assert F["long_lead"][0]["item"] == "Example steel joists"


def test_allowances_editor_feeds_the_pack(store):
    from app.pm import allowances as al
    with pytest.raises(al.AllowanceError):
        al.save(store, [{"name": "Example signage", "amount": "abc"}])
    with pytest.raises(al.AllowanceError):
        al.save(store, [{"name": "", "amount": "5"}])
    al.save(store, [{"name": "Example signage", "amount": "$12,000",
                     "spent": "4,500.50"}, {"name": "", "amount": "",
                                            "spent": ""}])
    assert al.read(store) == [{"name": "Example signage",
                               "amount": 12000.0, "spent": 4500.5}]
    ora, rep, F = auto(store)
    assert F["allowances"][0]["amount"] == 12000
    assert F["allowances"][0]["remaining"] == 7500


# --------------------------------------------------------------- G18
def test_g18_risks_include_insurance_and_issues(store):
    ora, rep, F = auto(store)
    txt = " ".join(r["risk"] for r in F["risks"])
    assert "insurance" in txt.lower() and "Owner furniture date" in txt


# --------------------------------------------------------------- G19/G20
def test_g19_s_curve_and_g20_contingency(store):
    ora, rep, F = auto(store)
    e = F["earned"]
    assert 0 < e["pct"] < 100 and len(e["curve"]) >= 3
    assert e["curve"][-1][1] == pytest.approx(100.0, abs=0.5)
    c = F["contingency"]
    assert c["amount"] == 32500 and c["remaining"] == 32500 - 11000


# --------------------------------------------------------------- G21
def test_g21_meetings(store):
    ora, rep, F = auto(store)
    assert F["meetings"]["last"]["title"] == "OAC meeting #2"
    assert F["meetings"]["next"]["title"] == "OAC meeting #3"


# --------------------------------------------------------------- G22
def test_g22_offline_forecast_says_not_available(store, tmp_path):
    rep = report(store)
    rep["forecast"] = {"mode": "table", "rows": [], "attach_ref": None}
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "Not available offline" in doc[0].get_text()


# --------------------------------------------------------------- G23
def test_g23_monthly_contents_with_page_numbers(store, tmp_path):
    rep = report(store, owner_pack=True, auto_pack=True,
                 report_preset="monthly")
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert keys(res)[0] == "pack_contents"
    first = doc[0].get_text()
    assert "CONTENTS" in first and "Budget" in first
    sched = next(m for m in res["page_map"] if m[0] == "pack_schedule")
    assert str(sched[1]) in first


def test_g23_report_number_on_every_page(store, tmp_path):
    """G23 (rest): the cover, photo and log pages show the report number
    too, not only the pack pages - and a classic report is unchanged."""
    p = str(tmp_path / "a.png")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
    pix.clear_with(90)
    pix.save(p)
    for preset in ("", "weekly", "monthly"):
        rep = report(store, owner_pack=True, auto_pack=True,
                     report_preset=preset)
        rep["report_no"] = "007"
        orp.add_photos(store, rep, [p])
        res, doc, t = pdf_text(store, rep, tmp_path, f"g23{preset}.pdf")
        for i, page in enumerate(doc):
            assert "Report #007" in page.get_text(), (preset, i)
    rep = report(store)
    rep["report_no"] = "007"
    res, doc, t = pdf_text(store, rep, tmp_path, "classic.pdf")
    assert "Report #007" not in t
    from app.pm import owner_report_logs as orl
    assert orl.FOOTER_SUFFIX == ""


# --------------------------------------------------------------- G24
def test_g24_key_plan_note_names_the_right_report(store, tmp_path):
    sheet = str(tmp_path / "plan.pdf")
    d = fitz.open()
    d.new_page(width=400, height=300)
    d.save(sheet)
    rep = report(store, owner_pack=True, key_plan=True,
                 report_preset="monthly")
    p = str(tmp_path / "a.png")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
    pix.clear_with(90)
    pix.save(p)
    orp.add_photos(store, rep, [p])
    rep["photos"][0].update(pin={"sheet": sheet, "page": 0, "x": 50,
                                 "y": 50}, caption="c", location="l")
    rep["pack"] = {"sections": [], "monthly": {"photo_pages": {
        rep["photos"][0]["ref"]["name"]: "W5"}, "photo_report": "weekly"}}
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "page of this report" not in t
    assert "weekly report" in t and "W5" in t


def test_g24_auto_pin_from_work_area_label(store):
    from app.pm import owner_report_auto as ora
    rep = report(store)
    rep["work_areas"] = [{"sheet": "s.pdf", "page": 0, "label": "East area",
                          "pts": [[0, 0], [10, 0], [10, 10], [0, 10]]}]
    rep["photos"] = [{"ref": {"name": "a.jpg"}, "location": "East area"}]
    ora.auto_pins(rep)
    assert rep["photos"][0]["pin"] == {"sheet": "s.pdf", "page": 0,
                                       "x": 5.0, "y": 5.0, "auto": True}


# --------------------------------------------------------------- G25
def test_g25_before_candidates_from_earlier_logs(store, tmp_path):
    from app.pm import owner_report_auto as ora
    p = str(tmp_path / "old.png")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
    pix.clear_with(60)
    pix.save(p)
    ref = store.attach(p)
    store.save_record("daily", {"date": "2026-11-03", "status": "Submitted",
                                "photos": [ref], "work": "Mobilized.",
                                "manpower": [{"trade": "Sitework - operators",
                                              "location": "East area",
                                              "notes": "Mobilized."}]})
    rep = report(store)
    rep["photos"] = [{"ref": {"name": "new.jpg"}, "location": "East area",
                      "taken": "2026-11-19T09:00"}]
    n = ora.before_from_logs(store, rep)
    assert n == 1 and rep["before_candidates"][0]["location"] == "East area"
    assert rep["photos"][0]["pair_with"] == rep["before_candidates"][0]["ref"]


# --------------------------------------------------------------- G26/G27/G28
def test_g26_logistics_carried_week_to_week(store):
    rep = report(store)
    rep["logistics"] = "Entrance on the east side."
    orp.save(store, rep)
    nxt = orp.new_report(store, date(2026, 11, 27), online=False)
    assert nxt["logistics"] == "Entrance on the east side."


def test_g27_distribution_and_g28_data_notes(store, tmp_path):
    rep = report(store, owner_pack=True, auto_pack=True,
                 report_preset="monthly")
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "DISTRIBUTION LIST" in t and "Pat Example" in t
    assert "DATA SOURCES AND NOTES" in t
    assert "[SAMPLE DATA]" in t and "crew_plan" in t


# --------------------------------------------------------------- G29
def test_g29_fonts_embedded_in_auto_reports(store, tmp_path):
    rep = report(store, owner_pack=True, auto_pack=True,
                 report_preset="weekly")
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert not res["unembedded_fonts"]


# --------------------------------------------------------------- G30
def test_g30_preset_control_summary_and_proposals_in_dialog(store):
    from test_pm import qapp_pm                      # noqa: F401
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.pm.owner_report_ui import OwnerReportWindow
    w = OwnerReportWindow(store, None, online=False)
    w.new_report(wait=True)
    assert w.report_preset.findData("weekly") >= 0
    assert w.report_preset.findData("monthly") >= 0
    w.report_preset.setCurrentIndex(w.report_preset.findData("weekly"))
    w._read()
    o = w.rep["options"]
    assert o["report_preset"] == "weekly" and o["owner_pack"] and \
        o["auto_pack"]
    w.draft_summary()
    assert "substantial completion" in w.summary.toPlainText().lower()
    w.summary.setPlainText("PM wording.")
    w._read()
    assert w.rep["summary_text"] == "PM wording."
    n = w.dec.rowCount()
    w.propose_actions()
    assert w.dec.rowCount() > n
    w.close()


# ------------------------------------------- second round (same gaps)
def test_g06_recovery_plan_steps_printed(store, tmp_path):
    from app.pm import recovery
    a5 = next(a for a in store.list("activity") if a["_no"] == "A0005")
    recovery.save(store, {"target": "2027-01-22", "cause": "other",
                          "steps": [{"id": a5["_id"], "technique": "crash",
                                     "duration": 12, "how": "Second crew",
                                     "agreed": True}],
                          "status": "Draft"})
    rep = report(store, owner_pack=True, auto_pack=True)
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "RECOVERY STEPS" in t and "Second crew" in t


def test_g11_lookahead_weeks_and_g26_logistics_in_dialog(store):
    from test_pm import qapp_pm                      # noqa: F401
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.pm.owner_report_ui import OwnerReportWindow
    w = OwnerReportWindow(store, None, online=False)
    w.new_report(wait=True)
    w.la_weeks.setCurrentIndex(w.la_weeks.findData(3))
    w.logistics.setPlainText("Gate on the east side.")
    w._read()
    assert w.rep["options"]["lookahead_weeks"] == 3
    assert w.rep["logistics"] == "Gate on the east side."
    w.close()


def test_g13_lost_time_and_open_observations(store):
    store.save_record("observation", {"title": "Open trench at storm line",
                                       "type": "Safety", "status": "Initiated",
                                       "due": "2026-11-19"})
    store.save_record("observation", {"title": "Later item", "type": "Safety",
                                       "status": "Initiated",
                                       "due": "2026-12-19"})
    ora, rep, F = auto(store)
    assert F["safety"]["lost_time"] == 0
    assert F["safety"]["observations_open"] == 1


def test_g14_inspection_records_in_the_week(store):
    store.save_record("inspection", {"title": "Footing inspection",
                                      "date": "2026-11-19",
                                      "status": "Failed",
                                      "inspector": "Jordan Test"})
    ora, rep, F = auto(store)
    x = next(i for i in F["site"]["inspections"]
             if "Footing inspection" in i["note"])
    assert x["failed"] and x["by"] == "Jordan Test"


def test_g21_attendees_present(store):
    ora, rep, F = auto(store)
    assert F["meetings"]["present"] == ["Pat Example (Owner Co (example))"]


def test_g22_forecast_page_says_not_available_offline(store, tmp_path):
    rep = report(store)
    rep["forecast"] = {"mode": "table", "rows": [], "attach_ref": None}
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "Not available offline - type the forecast rows" in t
    assert "No forecast available" not in t


def test_g11_holidays_marked_on_three_week_lookahead(store, tmp_path):
    store.set_setting("holidays", ["2026-11-26", "2026-12-25"])
    rep = report(store, lookahead=True, lookahead_weeks=3)
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "THREE-WEEK LOOK-AHEAD" in t and "TWO-WEEK LOOK-AHEAD" not in t
    assert "Holidays in this look-ahead: Thu 11/26/2026" in t
    assert "12/25/2026" not in t.split("Holidays in this look-ahead:")[1][:40]


def test_g20_allowance_lines_spent_and_remaining(store, tmp_path):
    store.set_setting("allowances", [
        {"name": "Example hardware allowance", "amount": 40000, "spent": 12500},
        {"name": "Example signage allowance", "amount": "15,000"}])
    ora, rep, F = auto(store, owner_pack=True, auto_pack=True,
                       report_preset="monthly")
    a = F["allowances"]
    assert [(r["name"], r["amount"], r["spent"], r["remaining"]) for r in a] \
        == [("Example hardware allowance", 40000, 12500, 27500),
            ("Example signage allowance", 15000, 0, 15000)]
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "ALLOWANCES" in t and "Example hardware allowance" in t
    assert "$27,500" in t


def test_g23_monthly_cover_block_with_project_facts(store, tmp_path):
    rep = report(store, owner_pack=True, auto_pack=True,
                 report_preset="monthly")
    res, doc, t = pdf_text(store, rep, tmp_path)
    first = doc[0].get_text()
    for word in ("PROJECT", "Owner", "Architect", "General contractor",
                 "Contract sum", "Notice to proceed", "Substantial completion",
                 "Report no.", "Week"):
        assert word in first, word
    assert first.index("PROJECT") < first.index("CONTENTS")


def test_g23_report_number_in_every_pack_footer(store, tmp_path):
    for preset in ("weekly", "monthly"):
        rep = report(store, owner_pack=True, auto_pack=True,
                     report_preset=preset)
        rep["report_no"] = "007"
        res, doc, t = pdf_text(store, rep, tmp_path, name=preset + ".pdf")
        pack = [i for m in res["page_map"] if m[0].startswith("pack_")
                for i in range(m[1], m[-1] + 1)]
        assert pack and all("Report #007" in doc[i - 1].get_text()
                            for i in pack), preset


def _inside_no_overlap(cells):
    x0, y0, x1, y1 = orp.GRID
    for c in cells:
        assert x0 <= c[0] < c[2] <= x1 and y0 <= c[1] < c[3] <= y1
    for i, a in enumerate(cells):
        for b in cells[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_g09_two_and_three_photos_per_page(store, tmp_path):
    for n in (2, 3):
        cells = orp.photo_cells(n, True)
        assert len(cells) == n
        _inside_no_overlap(cells)
        c4 = orp.photo_cells(4, True)[0]
        area4 = (c4[2] - c4[0]) * (c4[3] - c4[1])
        assert max((c[2] - c[0]) * (c[3] - c[1]) for c in cells) > area4
    rep = report(store)
    for i in range(5):
        p = str(tmp_path / f"q{i}.png")
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
        pix.clear_with(100 + i)
        pix.save(p)
        orp.add_photos(store, rep, [p])
        rep["photos"][-1]["caption"] = f"Example caption {i}."
    rep["options"]["photos_per_page"] = 3
    res, doc, t = pdf_text(store, rep, tmp_path)
    ph = next(m for m in res["page_map"] if m[0] == "photos")
    assert ph[-1] - ph[1] + 1 == 2           # 5 photos at 3 a page


def test_g09_per_page_choices_in_dialog(store):
    from test_pm import qapp_pm                      # noqa: F401
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.pm.owner_report_ui import OwnerReportWindow
    d = OwnerReportWindow(store, None, online=False)
    d.new_report(wait=True)
    vals = [d.per_page.itemData(i) for i in range(d.per_page.count())]
    assert {2, 3, 4, 6} <= set(vals)


def test_g24_view_direction_arrow_and_text(store, tmp_path):
    op = orp.view_arrow_op({"x": 100, "y": 100, "view": "E"})
    assert op["kind"] == "add_line" and op["payload"]["arrow"] is True
    (x0, y0), (x1, y1) = op["payload"]["pts"]
    assert (x0, y0) == (100.0, 100.0) and x1 > x0 and abs(y1 - y0) < 1e-6
    op = orp.view_arrow_op({"x": 100, "y": 100, "view": "N"})
    assert op["payload"]["pts"][1][1] < 100      # up the sheet
    assert orp.view_arrow_op({"x": 1, "y": 1}) is None
    assert orp.view_arrow_op({"x": 1, "y": 1, "view": "sideways"}) is None
    sheet = str(tmp_path / "plan.pdf")
    d = fitz.open()
    d.new_page(width=400, height=300)
    d.save(sheet)
    rep = report(store, key_plan=True)
    p = str(tmp_path / "a.png")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
    pix.clear_with(90)
    pix.save(p)
    orp.add_photos(store, rep, [p])
    rep["photos"][0].update(pin={"sheet": sheet, "page": 0, "x": 50, "y": 50,
                                 "view": "NE"}, caption="c", location="l")
    res, doc, t = pdf_text(store, rep, tmp_path)
    assert "looking NE" in t and not res["warnings"]


def test_g24_view_direction_set_in_dialog(store, tmp_path):
    from test_pm import qapp_pm                      # noqa: F401
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.pm.owner_report_ui import OwnerReportWindow
    w = OwnerReportWindow(store, None, online=False)
    w.new_report(wait=True)
    p = str(tmp_path / "v.png")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
    pix.clear_with(70)
    pix.save(p)
    orp.add_photos(store, w.rep, [p])
    w.rep["photos"][-1]["pin"] = {"sheet": "s.pdf", "page": 0, "x": 1, "y": 1}
    w.load(w.rep)
    w.photos.setCurrentRow(len(w.rep["photos"]) - 1)
    assert w.view_dir.findData("SW") >= 0
    w.view_dir.setCurrentIndex(w.view_dir.findData("SW"))
    assert w.rep["photos"][-1]["pin"]["view"] == "SW"
    w.view_dir.setCurrentIndex(w.view_dir.findData(""))
    assert "view" not in w.rep["photos"][-1]["pin"]


def test_allowances_dialog(store):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.pm.allowances_ui import AllowancesDialog
    d = AllowancesDialog(store)
    r = d.add_row("Example hardware", "8,000", "1,000")
    assert d.table.item(r, 3).text() == "7,000.00"
    d.table.item(r, 2).setText("2,500")
    assert d.table.item(r, 3).text() == "5,500.00"
    bad = d.add_row("Example bad", "lots", "")
    assert d.save() is False and "row" in d.msg.text()
    d.table.removeRow(bad)
    assert d.save() is True
    from app.pm import allowances as al
    assert al.read(store)[-1] == {"name": "Example hardware",
                                  "amount": 8000.0, "spent": 2500.0}
