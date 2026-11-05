"""Compiler pieces: ingest, facts, critical path, completeness, review."""
import datetime as dt
import os

import pytest

from app.pm.schedacc import ai_extract, buildnet, cpm, extract, ingest, merge
from app.pm.schedacc.calendar import standard_specs
from app.pm.schedacc.engine import compile_schedule
from app.pm.schedacc.model import blank_activity, new_schedule
from app.pm.schedacc import options, reviewq, rubric


def _pages(text):
    rows, n = [], 1
    for part in text.strip().split("SECTION "):
        if part.strip():
            rows.append((n, "SECTION " + part))
            n += 1
    return rows


SPEC = """
SECTION 01 32 00 - CONSTRUCTION PROGRESS DOCUMENTATION
The Work shall be substantially complete within one hundred eighty (180) calendar days after Notice to Proceed.

SECTION 01 33 00 - SUBMITTAL PROCEDURES
Submittals will be reviewed within 14 calendar days.

SECTION 03 30 00 - CAST-IN-PLACE CONCRETE
Concrete shall achieve a 28-day cure before structural steel erection.

SECTION 05 12 00 - STRUCTURAL STEEL FRAMING
Structural steel lead time is 12 weeks.
"""


def _compile(**kw):
    kw.setdefault("spec_pages", _pages(SPEC))
    kw.setdefault("project_type", "ground_up_commercial")
    kw.setdefault("ntp", "2026-03-02")
    kw.setdefault("settings", {"allow_ai": False})
    kw.setdefault("holidays", [])
    kw.setdefault("project_name", "Cedar Annex")
    return compile_schedule(**kw)


def test_ingest_sections_drawings_and_blank_pages():
    text = "HEADER\n" + SPEC
    pages = _pages(text)
    # Repeat a running header so it is stripped, and add an empty page.
    pages = [{"page": p, "text": "PROJECT MANUAL\n" + t} for p, t in pages]
    pages.append({"page": 99, "text": "   "})
    bundle = ingest.ingest(pages, [
        {"number": "M-201", "title": "Mechanical plan", "page": 1,
         "text": "SHEET M-201 MECHANICAL PLAN"},
        {"page": 2, "text": ""},
    ], ocr=lambda page: "SECTION 22 11 00 Plumbing rough-in recovered" * 3
       if page["page"] == 99 else "")
    numbers = [s["number"] for s in bundle["spec_sections"]]
    assert "01 32 00" in numbers and "05 12 00" in numbers
    assert "PROJECT MANUAL" not in bundle["spec_sections"][0]["text"]
    blanks = [b["page"] for b in bundle["blank_pages"]]
    assert 2 in blanks
    # Page 99 was empty and the OCR hook filled it, so it is not blank.
    assert 99 not in blanks
    assert bundle["drawings"][0]["prefix"] == "M"
    assert bundle["drawings"][0]["discipline"] == "mechanical"


def test_deterministic_facts_ignore_cure_as_a_lead_time():
    sections, _q = ingest.segment_spec(_pages(SPEC))
    facts, ct = extract.extract(sections, _pages(SPEC))
    merged, conflicts = merge.merge(facts)
    steel = next(f for f in merged if f["kind"] == "long_lead"
                 and f["item"] == "structural steel")
    assert steel["value"] == 12 * 7
    assert steel["lead_source"] == "spec"
    assert not conflicts
    cure = next(f for f in merged if f["kind"] == "cure")
    assert cure["value"] == 28
    review = next(f for f in merged if f["kind"] == "submittal_review")
    assert review["value"] == 14
    assert ct["substantial"]["days"] == 180
    assert any(f["kind"] == "drawing_note" and f["item"] == "NTS"
               for f in extract.extract_sections(
                   [{"number": "00 00 00", "division": "00", "pages": [1],
                     "text": "DETAIL 3 NTS"}]))


def test_merge_flags_two_stated_lead_times():
    facts = [
        {"kind": "long_lead", "item": "Chiller", "value": 100, "unit": "calendar",
         "lead_source": "spec", "source": "deterministic", "page": 2,
         "spec_section": "23 64 00", "division": "23", "text": "100 days"},
        {"kind": "long_lead", "item": "chiller", "value": 140, "unit": "calendar",
         "lead_source": "spec", "source": "deterministic", "page": 4,
         "spec_section": "23 64 00", "division": "23", "text": "140 days"},
    ]
    merged, conflicts = merge.merge(facts)
    assert conflicts and merged[0]["value"] is None
    assert {c["page"] for c in merged[0]["citations"]} == {2, 4}


def test_model_json_is_rejected_once_then_kept_and_hints_are_not_durations():
    calls = {"n": 0}

    def ask(prompt, model):
        calls["n"] += 1
        assert "do not write a schedule" in prompt.lower() or "Do not write a schedule" in prompt
        if calls["n"] == 1:
            return "not json"
        return (
            '{"activities":[{"name":"Hang piping","division":"22","spec_section":"22 11 00"}],'
            '"long_lead":[{"item":"pump","lead_time_days":30}],'
            '"submittals":[],"inspections":[{"name":"pressure test"}],'
            '"tests":[],"phasing":[],"sequencing":[],"milestones":[],'
            '"duration_hints":[{"activity":"Hang piping","note":"999 days"}],'
            '"owner_furnished":[],"commissioning":[],"by_others":[]}'
        )

    sections = [{"number": "22 11 00", "division": "22", "pages": [3],
                 "text": "Pump lead time is 30 days. " * 5}]
    facts, errors = ai_extract.extract_sections(
        sections, ask, "qwen2.5:7b-instruct", "llama3.2", 3500, allow=True)
    assert calls["n"] == 2 and not errors
    assert any(f["kind"] == "duration_hint" and "999" in f["text"] for f in facts)
    assert not any(f["kind"] == "long_lead" and f.get("value") == 999 for f in facts)
    with pytest.raises(ai_extract.SchemaError):
        ai_extract.validate({"activities": [], "extra": []})


def test_fallback_model_is_used_when_the_recommended_one_is_missing():
    seen = []

    def ask(prompt, model):
        seen.append(model)
        if model != "llama3.2":
            raise RuntimeError("Model 'qwen2.5:7b-instruct' isn't installed")
        return ('{"activities":[],"long_lead":[],"submittals":[],"inspections":[],'
                '"tests":[],"phasing":[],"sequencing":[],"milestones":[],'
                '"duration_hints":[],"owner_furnished":[],"commissioning":[],'
                '"by_others":[]}')

    facts, errors = ai_extract.extract_sections(
        [{"number": "01 11 00", "division": "01", "pages": [1], "text": "Hello spec " * 20}],
        ask, "qwen2.5:7b-instruct", "llama3.2", 3500, allow=True)
    assert seen[0] == "qwen2.5:7b-instruct" and "llama3.2" in seen
    assert not errors


def test_cpm_matches_the_existing_monday_to_friday_pass(tmp_path, monkeypatch):
    from app import settings
    from app.pm import schedule
    from app.pm.store import ProjectStore
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    doc = new_schedule("T", start="2026-01-05", data_date="2026-01-05")
    doc["calendars"] = standard_specs([])
    def add(code, name, days, typ="task"):
        doc["activities"].append(blank_activity(
            code, name, type=typ, calendar="5day",
            orig_hours=0 if "ms" in typ else days * 8))
    add("NTP", "Notice to Proceed", 0, "start_ms")
    add("MOB", "Mobilization", 5)
    add("EXC", "Excavate", 5)
    add("DONE", "Foundations done", 0, "finish_ms")
    doc["relationships"] = [
        {"pred": "NTP", "succ": "MOB", "type": "FS", "lag_hours": 0},
        {"pred": "MOB", "succ": "EXC", "type": "FS", "lag_hours": 0},
        {"pred": "EXC", "succ": "DONE", "type": "FS", "lag_hours": 0},
    ]
    cpm.schedule(doc)
    store = ProjectStore(str(tmp_path / "job"))
    store.set_setting("project_start", "2026-01-05")
    store.set_setting("data_date", "2026-01-05")
    store.set_setting("holidays", [])
    store.save_record("activity", {"name": "Notice to Proceed", "duration": 0,
                                    "start": "2026-01-05"})
    store.save_record("activity", {"name": "Mobilization", "duration": 5,
                                    "preds": [{"id": "A0001", "type": "FS", "lag": 0}]})
    store.save_record("activity", {"name": "Excavate", "duration": 5,
                                    "preds": [{"id": "A0002", "type": "FS", "lag": 0}]})
    store.save_record("activity", {"name": "Foundations done", "duration": 0,
                                    "preds": [{"id": "A0003", "type": "FS", "lag": 0}]})
    native = schedule.compute(store, dt.date(2026, 1, 5))
    ours = {a["name"]: (a["es"], a["ef"]) for a in doc["activities"]}
    for row in native["rows"]:
        assert ours[row["name"]] == (row["es"].isoformat(), row["ef"].isoformat())


def test_seven_day_cure_includes_the_weekend():
    doc = new_schedule("T", start="2026-01-05", data_date="2026-01-05")
    doc["calendars"] = standard_specs([])
    doc["activities"] = [
        blank_activity("POUR", "Pour", calendar="5day", orig_hours=8),
        blank_activity("CURE", "Cure", calendar="7day", orig_hours=7 * 8),
        blank_activity("NEXT", "Strip", calendar="5day", orig_hours=8),
    ]
    doc["relationships"] = [
        {"pred": "POUR", "succ": "CURE", "type": "FS", "lag_hours": 0},
        {"pred": "CURE", "succ": "NEXT", "type": "FS", "lag_hours": 0},
    ]
    cpm.schedule(doc)
    by = {a["code"]: a for a in doc["activities"]}
    # Monday pour, cure starts Tuesday and runs seven calendar days.
    assert by["POUR"]["es"] == "2026-01-05"
    assert by["CURE"]["es"] == "2026-01-06"
    assert by["CURE"]["ef"] == "2026-01-12"
    assert by["NEXT"]["es"] == "2026-01-13"
    assert by["CURE"]["why"]
    assert "Cure" in by["NEXT"]["why"]


def test_weather_calendar_skips_a_shutdown_month():
    doc = new_schedule("T", start="2026-01-05", data_date="2026-01-05")
    doc["calendars"] = standard_specs([], weather_months=[1, 2])
    doc["activities"] = [
        blank_activity("NTP", "Notice", type="start_ms", calendar="5day", orig_hours=0),
        blank_activity("UG", "Excavate", calendar="weather", orig_hours=5 * 8),
    ]
    doc["relationships"] = [
        {"pred": "NTP", "succ": "UG", "type": "FS", "lag_hours": 0}]
    cpm.schedule(doc)
    ug = doc["activities"][1]
    assert ug["es"] >= "2026-03-01"


def test_no_ai_path_covers_divisions_and_does_not_call_the_model():
    called = {"n": 0}

    def ask(prompt, model):
        called["n"] += 1
        return "{}"

    events = []
    doc = _compile(ask=ask, progress=lambda e: events.append(e["stage"]),
                   takeoff=[{"division": "03", "quantity": 400, "unit": "SF",
                             "id": "T1", "cost_code": "03 30 00"}])
    assert called["n"] == 0
    assert "cpm" in events and "rubric" in events
    divs = {a.get("division") for a in doc["activities"]}
    assert {"01", "03", "05"} <= divs
    assert doc["status"] == "finished"
    assert doc["settings"]["recommended_model"].startswith("qwen2.5")
    assert doc["settings"]["fallback_model"] == "llama3.2"
    # The model did not author a duration.
    assert all(a.get("duration_kind") in ("computed", "estimated", "")
               for a in doc["activities"])
    assert "999" not in " ".join(a.get("basis") or "" for a in doc["activities"])
    assert "Primavera" not in doc["narrative"] and "P6" not in doc["narrative"]


def test_short_contract_is_not_called_finished_until_float_is_acknowledged():
    short = SPEC.replace("one hundred eighty (180)", "thirty (30)")
    doc = _compile(spec_pages=_pages(short))
    assert doc["status"] == "incomplete"
    assert any("Negative float" in g for g in doc["rubric"]["gaps"])
    rubric.acknowledge_negative_float(doc, "The contract date is short of the work.")
    assert doc["status"] == "finished"
    assert doc["project"]["negative_float_ack"]


def test_confirming_a_row_updates_the_template(tmp_path):
    doc = _compile()
    mob = next(a for a in doc["activities"] if a.get("template_slot") == "MOB")
    reviewq.confirm(doc, mob["code"], template_dir=str(tmp_path), changes={"days": 7})
    lib = __import__("json").load(open(os.path.join(tmp_path, "schedacc_templates.json")))
    saved = next(s for s in lib["slots"] if s["code"] == "MOB")
    assert saved["days"] == 7
    assert mob["human_edited"] and mob["confirmed"]
    options.save(str(tmp_path), {"model": "qwen2.5:7b-instruct", "allow_ai": False})
    loaded = options.load(str(tmp_path))
    assert loaded["allow_ai"] is False
    assert loaded["fallback_model"] == "llama3.2"


def test_progress_override_ignores_an_unfinished_predecessor():
    doc = new_schedule("T", start="2026-01-05", data_date="2026-01-12")
    doc["calendars"] = standard_specs([])
    doc["options"]["out_of_sequence"] = "override"
    doc["activities"] = [
        blank_activity("A", "First", calendar="5day", orig_hours=10 * 8,
                       status="active", actual_start="2026-01-05", percent=10),
        blank_activity("B", "Second", calendar="5day", orig_hours=8,
                       status="active", actual_start="2026-01-06", percent=5),
    ]
    doc["relationships"] = [
        {"pred": "A", "succ": "B", "type": "FS", "lag_hours": 0}]
    cpm.schedule(doc)
    second = doc["activities"][1]
    # Override lets the started successor resume at the data date.
    assert second["es"] == "2026-01-12"
    assert any("out of sequence" in line.lower() for line in doc["log"])


def test_baseline_earned_value_and_leveling():
    doc = new_schedule("T", start="2026-01-05", data_date="2026-01-09")
    doc["calendars"] = standard_specs([])
    doc["activities"] = [
        blank_activity("A", "Crew A", calendar="5day", orig_hours=10 * 8,
                       roles=("Crew",), budget_cost=1000),
        blank_activity("B", "Crew B", calendar="5day", orig_hours=2 * 8,
                       roles=("Crew",), budget_cost=500),
        blank_activity("END", "Done", type="finish_ms", calendar="5day",
                       orig_hours=0),
    ]
    doc["relationships"] = [
        {"pred": "A", "succ": "END", "type": "FS", "lag_hours": 0},
        {"pred": "B", "succ": "END", "type": "FS", "lag_hours": 0},
    ]
    cpm.schedule(doc)
    cpm.take_baseline(doc, "project")
    b = next(a for a in doc["activities"] if a["code"] == "B")
    assert b["free_float_days"] > 0
    saved = b["ef"]
    b["ef"] = "2026-02-02"
    assert cpm.variance_days(doc, b, "finish") < 0
    b["ef"] = saved
    ev = cpm.earned_value(doc)
    assert ev["bac"] == 1500 and ev["bcws"] > 0
    before = b["es"]
    cpm.level_resources(doc, max_units=1)
    b = next(a for a in doc["activities"] if a["code"] == "B")
    assert b["unleveled_es"] == before
    assert b["es"] > before


def test_rules_round_trip_and_project_type_detection(tmp_path):
    from app.pm.schedacc import rules
    rules.save(str(tmp_path), rules.defaults())
    assert len(rules.load(str(tmp_path))) >= 10
    assert buildnet.detect_type("tenant improvement of suite 4", ["01", "09"]) == \
        "tenant_improvement"
    assert buildnet.detect_type("plumbing service call", ["22"]) == \
        "plumbing_hvac_service"
    assert buildnet.detect_type("replace the existing rooftop units", ["23"]) == \
        "mep_retrofit"
