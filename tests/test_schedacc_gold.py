"""Three made-up jobs, scored against a hand-built expectation.

The figures in the specs are invented. Nothing here is a real project.
The existing generator is run on the same text when it can run without
a window, and both scorecards are checked.
"""
import os

from app.pm.schedacc.engine import compile_schedule
from app.pm.schedacc.score import run_legacy, score, score_legacy

HERE = os.path.join(os.path.dirname(__file__), "data", "schedacc")

# What a careful schedule for that text has to contain. Thresholds are
# the bar for the new compiler. The existing generator is scored with
# the same measures so the two can be compared; it is not expected to
# clear the long-lead bar.
JOBS = (
    {
        "file": "ground_up.txt",
        "type": "ground_up_commercial",
        "legacy_type": "new_building",
        "divisions": ["01", "03", "05", "07", "08", "09", "21", "22", "23",
                      "26", "31", "32"],
        "long_leads": ["structural steel", "air handler", "switchgear",
                       "curtain wall", "generator", "roofing"],
        "forbid_divisions": [],
    },
    {
        "file": "tenant_improvement.txt",
        "type": "tenant_improvement",
        "legacy_type": "renovation",
        "divisions": ["01", "02", "09", "22", "23", "26"],
        "long_leads": ["air handler"],
        "forbid_divisions": ["07", "05", "03"],
    },
    {
        "file": "mep_retrofit.txt",
        "type": "mep_retrofit",
        "legacy_type": "hvac_replacement",
        "divisions": ["01", "23", "26"],
        "long_leads": ["rooftop unit", "switchgear"],
        "forbid_divisions": ["03", "07"],
    },
)

# An expert draft clears these. High float is reported and may miss the
# pamphlet's 5 percent line when parallel procurement is shorter than the
# field; the other health points have to pass.
HEALTH_FLOOR = 85
MUST_PASS = ("logic", "leads", "lags", "rel_types", "neg_float",
             "high_duration", "invalid_dates", "resources", "cp_test", "cpli")


def _load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        text = fh.read()
    pages, n = [], 1
    for part in text.strip().split("SECTION "):
        if part.strip():
            pages.append((n, "SECTION " + part))
            n += 1
    return pages


def _drawings(kind):
    if kind == "tenant_improvement":
        return [{"number": "A-101", "title": "Demolition plan", "page": 1,
                 "text": "SHEET A-101 DEMOLITION PLAN tenant improvement"},
                {"number": "M-101", "title": "Mechanical plan", "page": 2,
                 "text": "SHEET M-101"}]
    if kind == "mep_retrofit":
        return [{"number": "M-101", "title": "Roof mechanical plan", "page": 1,
                 "text": "SHEET M-101 ROOF MECHANICAL"},
                {"number": "E-101", "title": "Electrical plan", "page": 2,
                 "text": "SHEET E-101"}]
    return [{"number": "A-101", "title": "First floor plan", "page": 1,
             "text": "SHEET A-101 FIRST FLOOR PLAN"},
            {"number": "S-101", "title": "Foundation plan", "page": 2,
             "text": "SHEET S-101"},
            {"number": "C-101", "title": "Site plan", "page": 3,
             "text": "SHEET C-101"}]


def _run(job):
    pages = _load(job["file"])
    drawings = _drawings(job["type"])
    doc = compile_schedule(
        spec_pages=pages, drawings=drawings, project_type=job["type"],
        ntp="2026-03-02", settings={"allow_ai": False}, holidays=[],
        project_name="Sample " + job["type"])
    expected = {"divisions": job["divisions"], "long_leads": job["long_leads"],
                "max_days": 44}
    new = score(doc, expected)
    legacy_acts, err = run_legacy(pages, drawings, job["legacy_type"])
    old = score_legacy(legacy_acts, expected) if not err else {"error": err}
    return doc, new, old


def test_gold_jobs_clear_the_expert_bar():
    compared = []
    for job in JOBS:
        doc, new, old = _run(job)
        compared.append((job["type"], new, old, doc["status"]))
        assert new["division_recall"] == 1.0, compared
        assert new["long_lead_coverage"] == 1.0, compared
        assert new["logic_validity"] >= 0.95, compared
        assert new["duration_plausibility"] >= 0.90, compared
        assert new["citation_accuracy"] >= 0.95, compared
        assert new["rubric_passed"] is True, (job["type"], doc["rubric"]["gaps"])
        assert new["status"] == "finished"
        assert new["health_score"] >= HEALTH_FLOOR, compared
        for key in MUST_PASS:
            assert new["health_items"].get(key) is True, (job["type"], key, new)
        divs = {a.get("division") for a in doc["activities"]}
        for banned in job["forbid_divisions"]:
            assert banned not in divs, (job["type"], banned)
        # The previous generator runs headless on the same text. Long-lead
        # coverage is the gap the new compiler is there to close.
        assert "error" not in old, old
        assert old["long_lead_coverage"] < new["long_lead_coverage"]
    # Keep the comparison visible when the test is run with output enabled.
    print("GOLD", compared)


def test_service_job_stands_without_a_building():
    pages = _load("service.txt")
    doc = compile_schedule(
        spec_pages=pages, project_type="plumbing_hvac_service",
        ntp="2026-03-02", settings={"allow_ai": False}, holidays=[],
        project_name="Harbor pump repair")
    expected = {"divisions": ["01", "22"], "long_leads": ["water heater"],
                "max_days": 44}
    new = score(doc, expected)
    assert new["division_recall"] == 1.0
    assert new["long_lead_coverage"] == 1.0
    assert new["rubric_passed"] is True, doc["rubric"]["gaps"]
    assert new["health_score"] >= HEALTH_FLOOR
    assert "swppp" not in {a.get("cls") for a in doc["activities"]}
    assert any(a.get("cls") == "service_repair" for a in doc["activities"])
    assert "Primavera" not in doc["narrative"]
