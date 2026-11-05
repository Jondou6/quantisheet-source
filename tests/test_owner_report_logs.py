"""Weekly Owner Report log pages (0.12.31): RFI log, Submittal Detail
Report, Change Order log, weather log and forecast page - layout order,
totals recounted from the store, per-log page numbers, open-only, blank
1900 dates, the weather maths and the weather gap line.
Made-up data only."""
import os
import re
from datetime import date, timedelta

import fitz
import pytest

from app import settings
from app.pm import owner_report_logs as L
from app.pm.store import ProjectStore

TODAY = date(2026, 10, 20)
HEAD = {"company": {"name": "Example Builders, Inc.",
                    "lines": ["100 Sample Parkway, Suite 2",
                              "Anytown, FL 30000",
                              "Phone: (555) 010-0100"]},
        "project": {"name": "Harbor Point Clubhouse (example)",
                    "number": "26.E.101", "number_arch": "A-2601",
                    "number_owner": "", "location": "1 Example Way, Anytown"},
        "logo": None, "long_date": "October 20, 2026", "date": TODAY}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Example"})
    return ProjectStore(str(tmp_path / "Job"))


def text_of(doc, pages=None):
    pages = range(doc.page_count) if pages is None else pages
    return "\n".join(doc[i].get_text() for i in pages)


def num_after(label, text):
    m = re.search(re.escape(label) + r"\s*(\d+)", text)
    assert m, f"{label!r} not in the page text"
    return int(m.group(1))


def assert_inside(doc):
    """No text drawn outside the page (spec AT-all)."""
    for page in doc:
        r = page.rect
        for w in page.get_text("words"):
            assert w[0] >= r.x0 - 0.5 and w[2] <= r.x1 + 0.5, w
            assert w[1] >= r.y0 - 0.5 and w[3] <= r.y1 + 0.5, w


def flattened_reopens(doc):
    data = doc.tobytes(garbage=4, deflate=True)
    with fitz.open("pdf", data) as d2:
        assert d2.page_count == doc.page_count
        for p in d2:
            assert len(list(p.widgets())) == 0
            assert len(list(p.annots())) == 0


# ------------------------------------------------------------- fixtures
def add_rfis(store):
    """5 made-up RFIs: 2 closed, 2 open, 1 draft; one 01/01/1900 due date;
    one open RFI past due and unanswered (the only overdue one)."""
    rows = [
        dict(subject="Footing depth at grid C", status="Closed",
             sent="2026-09-01", due="2026-09-08", answered="2026-09-05",
             closed_on="2026-09-06"),
        dict(subject="Grease interceptor size", status="Closed",
             sent="2026-09-10", due="1900-01-01", closed_on="2026-09-20"),
        dict(subject="Transformer pad location", status="Open",
             sent="2026-10-01", due="2026-10-08"),
        dict(subject="Canopy color selection", status="Open",
             sent="2026-10-06", due="2026-10-27", answered="2026-10-10"),
        dict(subject="Irrigation zone addition", status="Draft"),
    ]
    out = []
    for r in rows:
        r.update({"question": "Please confirm.", "to": "Example Architects",
                  "from": "J. Doe"})
        out.append(store.save_record("rfi", r))
    return out


def add_submittals(store):
    p1 = store.save_record("subpkg", {"title": "Concrete Mix Design",
                                      "spec": "03 30 00 Cast-in-Place"})
    p2 = store.save_record("subpkg", {"title": "Structural Steel",
                                      "spec": "05 12 00 Structural Steel"})

    def add(title, spec, pkg, **kw):
        rec = {"title": title, "spec": spec, "type": "Product Data",
               "responsible": "Sample Subcontractor Co."}
        if pkg:
            rec["package"] = pkg["_id"]
        rec.update(kw)
        return store.save_record("submittal", rec)

    # A: back from review 4 days late -> received overdue, 18 days in review
    add("Mix designs", "03 30 00", p1, status="Approved as Noted",
        revision=0, received="2026-09-01",
        workflow=[{"reviewer": "Example Architects", "sent": "2026-09-02",
                   "due": "2026-09-16", "returned": "2026-09-20",
                   "result": "Approved as Noted"}])
    # B: in review, due 10/15, not back -> open overdue, 19 days in review
    add("Mix designs", "03 30 00", p1, status="In Review", revision=1,
        received="2026-09-30",
        workflow=[{"reviewer": "Example Architects", "sent": "2026-10-01",
                   "due": "2026-10-15"}])
    # C: in review, due 10/24 -> open, not overdue, 10 days in review
    add("Steel shop drawings", "05 12 00", p2, status="In Review",
        received="2026-10-09",
        workflow=[{"reviewer": "Example Engineers", "sent": "2026-10-10",
                   "due": "2026-10-24"}])
    # D: not submitted, submit-by passed -> yet to submit, overdue
    add("Anchor bolts", "05 12 00", p2, status="Not Submitted",
        submit_by="2026-10-01")
    # E: no package, not submitted, not due yet -> yet to submit
    add("Gypsum board", "09 29 00", None, status="Not Submitted",
        submit_by="2026-11-30")
    return p1, p2


def add_change_events(store):
    for item, desc, amt in (("1", "Base contract", 2400000),
                            ("2", "General conditions", 50000)):
        store.save_record("contract", {"item": item, "description": desc,
                                       "scheduled": amt})
    evs = [("Remove buried debris at Area C", "Unforeseen Condition",
            "Approved", 18450, 3, "CO-01", "2026-05-28", "2026-06-08"),
           ("Relocate water meter", "Design Change", "Approved", 2310, 0,
            "CO-01", "2026-06-07", "2026-06-22"),
           ("Relocate transformer pad", "Unforeseen Condition", "Pending",
            12600, 4, "", "2026-10-10", ""),
           ("Canopy color upgrade", "Owner Request", "Pending", 3150, 1, "",
            "2026-10-15", ""),
           ("Add irrigation zone 10", "Owner Request", "Open", 9800, 0, "",
            "", ""),
           ("Delete irrigation zone 9", "Owner Request", "Rejected", -1200,
            0, "", "2026-08-26", "")]
    for title, reason, st, price, days, co, sent, appr in evs:
        store.save_record("event", {
            "title": title, "reason": reason, "status": st, "days": days,
            "co_no": co, "submitted": sent, "approved": appr,
            "lines": [{"description": title, "cost": price,
                       "markup": 0, "price": price}]})


# ------------------------------------------------------------------ RFIs
def test_rfi_log_columns_totals_and_footer(store):
    add_rfis(store)
    doc = fitz.open()
    res = L.add_rfi_log(doc, store, HEAD, {})
    assert res["pages"] == doc.page_count == 1
    page = doc[0]
    assert (page.rect.width, page.rect.height) == (612, 792)
    assert page.rotation == 0
    text = page.get_text()
    assert "Request for Information Log" in text
    assert "This Report Was Created Using The Following Filters:" in text
    assert "Example Builders, Inc." in text and "26.E.101" in text
    # column headings in the order of the form (spec 1.3)
    order = ["Number", "Originator", "BIC", "Submitted", "Due", "Responded",
             "Closed", "Status"]
    xs = {}
    for w in page.get_text("words"):
        if 238 < w[1] < 263 and w[4] in order and w[4] not in xs:
            xs[w[4]] = w[0]
    assert list(xs) and sorted(xs, key=xs.get) == order
    # rows in number order, subject after the number
    assert text.index("001 Footing depth") < \
        text.index("003 Transformer pad") < text.index("005 Irrigation")
    # totals recounted from the store
    recs = store.list("rfi")
    closed = sum(1 for r in recs if r["status"] == "Closed")
    assert num_after("Total RFIs", text) == len(recs) == 5
    assert num_after("Total Closed RFIs", text) == closed == 2
    assert num_after("Total Open RFIs", text) == len(recs) - closed == 3
    assert num_after("Qty. Responded", text) == \
        sum(1 for r in recs if r.get("answered")) == 2
    assert res["totals"]["total"] == 5 and res["totals"]["overdue"] == 1
    # dates MM/DD/YYYY, footer with the long date and its own page number
    assert "09/05/2026" in text
    assert "October 20, 2026" in text and "Page 1 of 1" in text
    assert_inside(doc)
    flattened_reopens(doc)


def test_rfi_log_paginates_and_page_numbers_restart_per_log(store):
    for i in range(60):
        store.save_record("rfi", {
            "subject": f"Made-up question {i + 1}" +
                       (" with a much longer subject that has to wrap onto "
                        "more lines" if i % 9 == 0 else ""),
            "question": "?", "status": "Closed" if i < 50 else "Open",
            "due": "2026-06-01", "to": "Example Architects"})
    add_submittals(store)
    doc = fitz.open()
    rfi = L.add_rfi_log(doc, store, HEAD, {})
    n = rfi["pages"]
    assert n >= 2 and doc.page_count == n
    for i in range(n):
        t = doc[i].get_text()
        assert f"Page {i + 1} of {n}" in t
        assert "Number" in t and "Originator" in t      # header repeated
    assert "RFI LOG TOTALS:" in doc[n - 1].get_text()
    assert "RFI LOG TOTALS:" not in doc[0].get_text()
    # like the GC's form: company and filter blocks on the first page only
    assert "Example Builders, Inc." in doc[0].get_text()
    assert "Example Builders, Inc." not in doc[1].get_text()
    assert "Following Filters" not in doc[1].get_text()
    allt = text_of(doc)
    for i in (1, 30, 60):
        assert f"{i:03d} Made-up question {i}" in allt
    sub = L.add_submittal_log(doc, store, HEAD, {})
    first = doc[n].get_text()
    assert "Submittal Detail Report" in first
    assert f"Page 1 of {sub['pages']}" in first          # restarts
    assert doc.page_count == n + sub["pages"]
    assert_inside(doc)


def test_rfi_open_only_counts_and_overdue(store):
    add_rfis(store)
    doc = fitz.open()
    res = L.add_rfi_log(doc, store, HEAD, {"open_only": True})
    text = text_of(doc)
    assert "Open only" in text
    assert "Footing depth" not in text and "Grease interceptor" not in text
    assert "Transformer pad" in text and "Irrigation zone" in text
    assert res["totals"]["listed"] == 3
    assert num_after("Total RFIs", text) == 5          # totals stay whole-log
    c = L.counts(store, TODAY)
    recs = store.list("rfi")
    open_ = [r for r in recs if r["status"] != "Closed"]
    overdue = [r for r in open_ if r.get("due") and
               "1901-01-01" <= r["due"] < TODAY.isoformat() and
               not r.get("answered")]
    assert c["rfi"] == {"open": len(open_), "overdue": len(overdue),
                        "total": len(recs)}
    assert c["rfi"]["overdue"] == 1
    # off: no "Open only" and closed ones listed
    doc2 = fitz.open()
    L.add_rfi_log(doc2, store, HEAD, {})
    assert "Open only" not in text_of(doc2)
    assert "Footing depth" in text_of(doc2)


def test_blank_dates_option(store):
    add_rfis(store)
    store.save_record("submittal", {"title": "Placeholder dates",
                                    "spec": "07 21 00",
                                    "received": "1900-01-01",
                                    "status": "Not Submitted"})
    on = fitz.open()
    L.add_rfi_log(on, store, HEAD, {"blank_dates": True})
    L.add_submittal_log(on, store, HEAD, {"blank_dates": True})
    assert "01/01/1900" not in text_of(on)
    off = fitz.open()
    L.add_rfi_log(off, store, HEAD, {})
    L.add_submittal_log(off, store, HEAD, {})
    assert text_of(off).count("01/01/1900") >= 2      # stored value as is


def test_empty_logs_still_print_a_page(store):
    doc = fitz.open()
    r = L.add_rfi_log(doc, store, HEAD, {})
    s = L.add_submittal_log(doc, store, HEAD, {})
    c = L.add_co_log(doc, store, HEAD, {})
    assert (r["pages"], s["pages"], c["pages"]) == (1, 1, 1)
    assert "No RFIs" in doc[0].get_text()
    assert "Number" in doc[0].get_text()               # headings still there
    assert "No submittals" in doc[1].get_text()
    assert "No change events" in doc[2].get_text()
    assert r["totals"]["total"] == 0
    assert num_after("Total RFIs", doc[0].get_text()) == 0
    for i in range(3):
        assert "Page 1 of 1" in doc[i].get_text()


# ------------------------------------------------------------ submittals
def test_submittal_log_grouped_by_package_with_totals(store):
    add_submittals(store)
    doc = fitz.open()
    res = L.add_submittal_log(doc, store, HEAD, {})
    page = doc[0]
    assert (page.rect.width, page.rect.height) == (792, 612)
    assert page.rotation == 0
    text = text_of(doc)
    assert "Submittal Detail Report" in text
    assert "This report is detailed by:" in text
    # packages in spec order, the loose item last
    i1 = text.index("033000-Concrete Mix Design")
    i2 = text.index("051200-Structural Steel")
    i3 = text.index("(no package)")
    assert i1 < i2 < i3
    assert i1 < text.index("03 30 00-001") < i2
    assert i2 < text.index("05 12 00-001") < i3 < text.index("09 29 00-001")
    # package rows are bold
    bold, plain = [], []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                is_bold = "Bold" in sp["font"] or sp["flags"] & 16
                (bold if is_bold else plain).append(sp["text"])
    bold, plain = " | ".join(bold), " | ".join(plain)
    assert "Package:" in bold
    assert "033000-Concrete Mix Design" in bold
    assert "Mix designs" in plain and "Mix designs" not in bold
    # review dates and day counts for item A (back 4 days late)
    assert "09/02/2026" in text and "09/16/2026" in text
    assert text.count("09/20/2026") >= 2       # received from review + to sub
    # totals: recount from the store
    recs = store.list("submittal")
    yet = [r for r in recs if not any(s.get("sent") for s in
                                      r.get("workflow") or [])]
    assert len(yet) == 2
    t = res["totals"]
    assert num_after("Total Submittal Items Yet to Submit:", text) == \
        t["yet_to_submit"] == len(yet)
    assert num_after("# Submittal Items Open Overdue:", text) == \
        t["open_overdue"] == 2                       # B (review) + D (submit)
    assert num_after("# Submittal Items Received Overdue:", text) == \
        t["received_overdue"] == 1                   # A
    assert num_after("Avg Days in Review (Days)", text) == \
        t["avg_days_in_review"] == round((18 + 19 + 10) / 3)
    c = L.counts(store, TODAY)["submittal"]
    assert c == {"open": 4, "overdue": 2, "total": 5}
    assert_inside(doc)
    flattened_reopens(doc)


def test_submittal_open_only(store):
    add_submittals(store)
    doc = fitz.open()
    res = L.add_submittal_log(doc, store, HEAD, {"open_only": True})
    text = text_of(doc)
    assert "Open only" in text
    assert res["totals"]["listed"] == 4
    assert "Steel shop drawings" in text and "Gypsum board" in text
    assert "09/20/2026" not in text            # A was returned: not listed


def test_submittal_log_paginates_with_package_continued(store):
    pkg = store.save_record("subpkg", {"title": "Doors and frames",
                                       "spec": "08 11 13 Hollow Metal"})
    for i in range(45):
        store.save_record("submittal", {
            "title": f"Door item {i + 1}", "spec": "08 11 13",
            "package": pkg["_id"], "status": "In Review",
            "workflow": [{"reviewer": "Example Architects",
                          "sent": "2026-09-01", "due": "2026-09-15"}]})
    doc = fitz.open()
    res = L.add_submittal_log(doc, store, HEAD, {})
    n = res["pages"]
    assert n >= 2
    for i in range(n):
        assert f"Page {i + 1} of {n}" in doc[i].get_text()
    assert "(continued)" in doc[1].get_text()
    assert "Avg Days in Review" in doc[n - 1].get_text()
    assert num_after("# Submittal Items Open Overdue:",
                     doc[n - 1].get_text()) == 45
    assert_inside(doc)


# ------------------------------------------------------- change order log
def test_co_log_lists_events_and_contract_totals(store):
    add_change_events(store)
    doc = fitz.open()
    res = L.add_co_log(doc, store, HEAD, {"co_log": True})
    page = doc[0]
    assert (page.rect.width, page.rect.height) == (792, 612)
    text = page.get_text()
    assert "Change Order Log" in text and "CHANGE ORDER TOTALS:" in text
    for h in ("No.", "Title", "Reason", "Status", "Sent to Owner",
              "Approved", "Amount", "Days", "CO No."):
        assert h in text
    assert text.index("CE-001") < text.index("CE-006")
    t = res["totals"]
    assert t["original"] == 2450000
    assert t["approved"] == 18450 + 2310
    assert t["revised"] == t["original"] + t["approved"]
    assert t["pending"] == 12600 + 3150
    assert t["open_amount"] == 9800
    assert (t["approved_days"], t["pending_days"]) == (3, 5)
    assert "$2,450,000" in text and "$2,470,760" in text
    assert "$15,750" in text and "($1,200)" in text
    assert "Page 1 of 1" in text
    c = L.counts(store, TODAY)["co"]
    assert c["open"] == 3 and c["total"] == 6
    only = fitz.open()
    L.add_co_log(only, store, HEAD, {"open_only": True})
    assert "Delete irrigation zone 9" not in only[0].get_text()
    assert "Add irrigation zone 10" in only[0].get_text()
    assert_inside(doc)


# ---------------------------------------------------------------- weather
def rain_rows(start=date(2026, 5, 1), end=date(2026, 10, 20)):
    """Made-up daily rain: every 9th day 0.80 in., every 13th 0.30 in."""
    out, d, i = [], start, 0
    while d <= end:
        rain = 0.8 if i % 9 == 0 else (0.3 if i % 13 == 0 else 0.0)
        out.append({"date": d.isoformat(), "rain_in": rain})
        d += timedelta(days=1)
        i += 1
    return out


def test_weather_days_claim_workdays_over_threshold():
    rows = rain_rows()
    days = L.weather_days(rows, 0.5)
    assert len(days) == len(rows)
    for d in days:
        wd = date.fromisoformat(d["date"]).weekday() < 5
        assert d["tracked"] == (d["rain_in"] >= 0.5)
        assert d["claimed"] == (d["tracked"] and wd)
    # exactly at the threshold counts
    d = L.weather_days([("2026-10-19", 0.5)], 0.5)[0]       # a Monday
    assert d["tracked"] and d["claimed"]
    d = L.weather_days([("2026-10-18", 0.9)], 0.5)[0]       # a Sunday
    assert d["tracked"] and not d["claimed"]
    tot = L.weather_totals({"days": days})
    tracked = [r for r in rows if r["rain_in"] >= 0.5]
    claimed = [r for r in tracked
               if date.fromisoformat(r["date"]).weekday() < 5]
    assert tot["impacted"] == len(tracked)
    assert tot["claimed"] == len(claimed)
    assert [m["label"] for m in tot["months"]] == \
        ["May", "June", "July", "August", "Sept", "October"]
    assert sum(m["actual"] for m in tot["months"]) == tot["impacted"]
    assert tot["project_days"] == len(rows)


def test_merge_keeps_user_edits():
    rows = rain_rows()
    days = L.weather_days(rows, 0.5)
    claimed = next(d for d in days if d["claimed"])
    claimed.update(claimed=False, note="Worked under cover", edited=True)
    dry = next(d for d in days if not d["tracked"] and
               date.fromisoformat(d["date"]).weekday() < 5)
    dry.update(tracked=True, claimed=True)        # edited, no flag
    new = rows + [{"date": "2026-10-21", "rain_in": 1.1}]
    merged = {d["date"]: d for d in L.merge_weather(days, new, 0.5)}
    assert merged[claimed["date"]]["claimed"] is False
    assert merged[claimed["date"]]["note"] == "Worked under cover"
    assert merged[dry["date"]]["claimed"] is True
    assert merged["2026-10-21"]["claimed"] is True        # new day, default
    assert len(merged) == len(rows) + 1


def test_merge_keeps_typed_rain_and_shows_the_download():
    """Review 0.12.35 #6: a re-pull never replaces rain the PM typed."""
    days = L.weather_days([{"date": "2026-10-06", "rain_in": 0.0},   # Tue
                           {"date": "2026-10-07", "rain_in": 0.0}], 0.5)
    typed = days[0]
    typed.update(rain_in=1.25, tracked=True, claimed=True, edited=True,
                 source="typed")
    new = [{"date": "2026-10-06", "rain_in": 0.10},
           {"date": "2026-10-07", "rain_in": 0.30}]
    merged = {d["date"]: d for d in L.merge_weather(days, new, 0.5)}
    t = merged["2026-10-06"]
    assert t["rain_in"] == 1.25 and t["source"] == "typed"
    assert t["download_in"] == 0.10
    assert t["tracked"] and t["claimed"]
    assert merged["2026-10-07"]["rain_in"] == 0.30          # downloaded day
    assert "source" not in merged["2026-10-07"]
    # typed but never toggled: the defaults follow the typed amount
    plain = [dict(merged["2026-10-06"], edited=False)]
    again = L.merge_weather(plain, [{"date": "2026-10-06", "rain_in": 0.0}],
                            0.5)[0]
    assert again["rain_in"] == 1.25 and again["claimed"]
    assert again["download_in"] == 0.0
    # both values in the weather log
    weather = {"days": list(merged.values()), "threshold_in": 0.5}
    assert L.typed_rain_notes(weather) == \
        ["10/06/2026: typed 1.25 in (download 0.10 in)"]
    doc = fitz.open()
    L.add_weather_log(doc, HEAD, weather, {})
    text = " ".join(doc[0].get_text().split())
    assert "typed 1.25 in (download 0.10 in)" in text
    assert "1.25" in text and "0.30" in text
    assert_inside(doc)


def test_merge_never_drops_a_claimed_day_silently():
    """Review #1: a re-pull with less rain kept the claim from vanishing
    only by chance. A claimed day whose new rain is under the threshold
    stays claimed with a note saying why; a threshold change or the PM's
    untick still un-claims."""
    days = L.weather_days([("2026-09-29", 1.2), ("2026-09-30", 0.9)], 0.5)
    days[1]["note"] = "Site flooded"
    merged = L.merge_weather(days, [("2026-09-29", 0.1),
                                    ("2026-09-30", 0.0)], 0.5)
    a, b = merged
    assert a["tracked"] and a["claimed"] and a["edited"]
    assert a["rain_in"] == 0.1
    assert a["note"].startswith("Kept as claimed: re-pulled rain 0.10 in "
                                "(was 1.20 in)")
    assert b["claimed"] and b["note"].startswith("Site flooded - Kept as")
    again = L.merge_weather(merged, [("2026-09-29", 0.1)], 0.5)[0]
    assert again["claimed"] and again["note"] == a["note"]  # no repeat
    assert L.weather_counts({"days": merged}) == (2, 2)
    # more rain, the same rain at a higher threshold, or the PM's untick:
    # no note
    up = L.merge_weather(days, [("2026-09-29", 0.6)], 1.0, old_threshold=0.5)
    assert not up[0]["claimed"] and not up[0]["note"]
    off = [dict(days[0], claimed=False, edited=True)]
    assert not L.merge_weather(off, [("2026-09-29", 0.0)], 0.5)[0]["note"]


def test_weather_counts_come_from_the_day_list():
    """Review 0.12.35 #7: one source - the list wins over stale totals."""
    rows = [("2026-10-05", 0.9), ("2026-10-06", 0.8), ("2026-10-07", 0.7),
            ("2026-10-08", 0.1)]                          # Mon-Thu
    days = L.weather_days(rows, 0.5)
    for d in days[1:3]:
        d.update(claimed=False, edited=True)      # 3 tracked, 1 claimed
    w = {"days": days, "threshold_in": 0.5, "impacted": 0, "claimed": 3}
    assert L.weather_counts(w) == (3, 1)
    assert L.weather_gap_line(w).startswith("3 impacted vs 1 claimed")
    tot = L.weather_totals(w)
    assert (tot["impacted"], tot["claimed"]) == (3, 1)
    # no list: the stored (typed) totals are the source
    assert L.weather_counts({"impacted": 5, "claimed": 2}) == (5, 2)


def test_log_pages_embed_the_report_font():
    """Review 0.12.35 #8: Liberation Sans, embedded and subset - no base-14
    font - with Helvetica's widths (the layouts were measured with it)."""
    for s, font in (("IMPACTED WEATHER DAYS: 12", "hebo"),
                    ("Rainfall Records (May to October) 0.80", "helv")):
        a = L.text_width(s, 8.2, font)
        b = fitz.get_text_length(s, fontname=font, fontsize=8.2)
        assert abs(a - b) <= 0.005 * b, (s, a, b)
    doc = fitz.open()
    L.add_weather_log(doc, HEAD, {"days": L.weather_days(rain_rows())}, {})
    doc.subset_fonts()
    data = doc.tobytes(garbage=4, deflate=True)
    with fitz.open("pdf", data) as d2:
        fonts = {f[0]: f for p in d2 for f in d2.get_page_fonts(p.number)}
        assert fonts
        full = os.path.getsize(os.path.join(L.font_dir(),
                                            "LiberationSans-Regular.ttf"))
        for xref, f in fonts.items():
            assert f[1] != "n/a", f                       # embedded
            assert "LiberationSans" in f[3].replace(" ", ""), f
            content = d2.extract_font(xref)[3]
            assert 0 < len(content) < full / 2, f         # subset


def test_report_font_files_and_license_ship():
    from app import legal
    for name in ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf",
                 "OFL.txt"):
        assert os.path.isfile(os.path.join(L.font_dir(), name)), name
    with open(os.path.join(L.font_dir(), "OFL.txt"), encoding="utf-8") as f:
        assert "SIL OPEN FONT LICENSE Version 1.1" in f.read()
    assert any("Liberation Sans" in n and "Open Font License" in lic
               for n, lic, _u in legal.THIRD_PARTY)


def test_weather_gap_line_adds_up():
    days = L.weather_days(rain_rows(), 0.5)
    w = {"days": days, "threshold_in": 0.5}
    # user edits: one tracked workday not claimed (with a note), one
    # sub-threshold workday tracked
    wd = next(d for d in days if d["claimed"])
    wd.update(claimed=False, note="Crew worked inside")
    low = next(d for d in days if d["rain_in"] == 0.3 and
               date.fromisoformat(d["date"]).weekday() < 5)
    low["tracked"] = True
    tot = L.weather_totals(w)
    line = L.weather_gap_line(w)
    m = re.match(r"(\d+) impacted vs (\d+) claimed: (\d+) fell on non-work "
                 r"days, (\d+) were under the 0\.50 in\. threshold"
                 r"(?:, (\d+) other: (.*))?\.$", line)
    assert m, line
    imp, cl, n1, n2 = (int(m.group(i)) for i in range(1, 5))
    n3 = int(m.group(5) or 0)
    assert (imp, cl) == (tot["impacted"], tot["claimed"])
    assert n1 + n2 + n3 == imp - cl
    assert n2 == 1 and n3 == 1 and "Crew worked inside" in m.group(6)
    # equal counts -> no line
    same = [dict(d, claimed=d["tracked"]) for d in days]
    assert L.weather_gap_line({"days": same}) is None
    assert L.weather_gap_line({"impacted": 4, "claimed": 4}) is None


def test_weather_log_page(store):
    days = L.weather_days(rain_rows(), 0.5)
    weather = {"days": days, "threshold_in": 0.5}
    doc = fitz.open()
    res = L.add_weather_log(doc, HEAD, weather, {})
    assert res["pages"] == 1
    page = doc[0]
    assert (page.rect.width, page.rect.height) == (612, 792)
    text = page.get_text()
    assert "Rainfall Records (May to October)" in text
    assert "Year: 2026" in text
    for h in ("TOTAL", "Tracked", "Claimed", "Actual", "Claimed Rain Days",
              "Fri, 01", "Sept", "TOTAL PROJECT DAYS"):
        assert h in text
    tot = L.weather_totals(weather)
    assert res["totals"]["impacted"] == tot["impacted"]
    assert res["totals"]["claimed"] == tot["claimed"]
    assert f"{tot['impacted']:.2f}" in text and f"{tot['claimed']:.2f}" in text
    # tracked / claimed colours are drawn
    fills = {tuple(round(c, 2) for c in d["fill"])
             for d in page.get_drawings() if d.get("fill")}
    assert tuple(round(c, 2) for c in L.CLAIMED_GREEN) in fills
    assert tuple(round(c, 2) for c in L.DAY_YELLOW) in fills
    assert_inside(doc)


def test_weather_log_more_than_six_months_takes_two_pages():
    rows = rain_rows(date(2026, 3, 1), date(2026, 11, 15))   # 9 months
    doc = fitz.open()
    res = L.add_weather_log(doc, HEAD, {"days": L.weather_days(rows)}, {})
    assert res["pages"] == doc.page_count == 2
    assert "Rainfall Records (March to August)" in doc[0].get_text()
    assert "Rainfall Records (September to November)" in doc[1].get_text()
    assert "TOTAL PROJECT DAYS" in doc[1].get_text()
    assert_inside(doc)


def test_weather_log_empty():
    doc = fitz.open()
    res = L.add_weather_log(doc, HEAD, {}, {})
    assert res["pages"] == 1
    assert "Rainfall Records" in doc[0].get_text()
    assert res["totals"]["impacted"] == 0


# --------------------------------------------------------------- forecast
def test_forecast_table():
    rows = []
    for i, rain in enumerate([0.78, 0.01, 0.06, 0.17, 0.49, 0.0, 0.6, 0.04,
                              0.11, 0.07]):
        d = date(2026, 10, 21) + timedelta(days=i)
        rows.append({"date": d.isoformat(), "sky": "Showers", "high": 85,
                     "low": 71, "rain_chance": 40, "rain_in": rain,
                     "wind": 12})
    doc = fitz.open()
    res = L.add_forecast_page(doc, HEAD, {"mode": "table", "rows": rows,
                                          "as_of": "2026-10-20"}, {})
    text = doc[0].get_text()
    assert "10-Day Weather Forecast" in text
    for h in ("Day", "Date", "Sky", "High / Low (F)", "Rain chance",
              "Rain (in.)", "Wind (mph)", "Work day?"):
        assert h in text
    assert "10/21/2026" in text and "85 / 71" in text
    assert text.count("Weekend") == 2          # Oct 24 and 25
    assert text.count("At risk") == 2          # Wed 0.78, Tue 0.60
    assert res["totals"]["at_risk"] == 2
    assert_inside(doc)


def test_forecast_attached_image(tmp_path):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 40), False)
    pix.set_rect(pix.irect, (40, 120, 200))
    path = str(tmp_path / "forecast.png")
    pix.save(path)
    doc = fitz.open()
    res = L.add_forecast_page(doc, HEAD, {"mode": "attach",
                                          "attach_path": path}, {})
    assert res["pages"] == 1 and doc.page_count == 1
    assert len(doc[0].get_images()) == 1
    # a missing attachment falls back to the table page
    doc2 = fitz.open()
    L.add_forecast_page(doc2, HEAD, {"mode": "attach",
                                     "attach_path": str(tmp_path / "x.png"),
                                     "rows": []}, {})
    assert "10-Day Weather Forecast" in doc2[0].get_text()


def test_logo_is_placed(store, tmp_path):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 40), False)
    pix.set_rect(pix.irect, (80, 130, 50))
    logo = str(tmp_path / "logo.png")
    pix.save(logo)
    doc = fitz.open()
    L.add_rfi_log(doc, store, dict(HEAD, logo=logo), {})
    assert len(doc[0].get_images()) == 1
