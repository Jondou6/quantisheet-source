"""Which civil sheets the pipe takeoff reads (a 309-sheet treatment-plant
set: titles say "PROCESS PIPING PLAN AREA 1", nothing matched, and the
takeoff fell back to all 28 civil sheets - notes, demolition, erosion
control, grading, overall plans and details - and counted pipe several
times over)."""
from app import heavy, sheets

PLANT = [
    ("C001", "GENERAL CIVIL NOTES"),
    ("C002", "EXISTING SITE CONDITIONS"),
    ("C002A", "PRE-DEVELOPMENT DRAINAGE AND GRADING PLAN"),
    ("C003", "INITIAL LAND DISTURBANCE PHASE SEDIMENT AND EROSION CONTROL "
             "PLAN"),
    ("C005", "DEMOLITION PLAN"),
    ("C006", "OVERALL SITE PLAN"),
    ("C007", "OVERALL PROCESS PIPING PLAN"),
    ("C008", "PROCESS PIPING PLAN AREA 1"),
    ("C009", "PROCESS PIPING PLAN AREA 2"),
    ("C012", "OVERALL POTABLE AND NON-POTABLE PIPING PLAN"),
    ("C013", "POTABLE AND NON-POTABLE PIPING PLAN AREA 1"),
    ("C017", "GRADING PLAN"),
    ("C017A", "POST-DEVELOPMENT DRAINAGE AND GRADING PLAN"),
    ("C018", "PAVING AND STAKING PLAN"),
    ("C019", "FINAL STABILIZATION AND PERMANENT EROSION CONTROL PLAN"),
    ("CD01", "STANDARD CIVIL DETAILS"),
    ("CD03", "STANDARD CIVIL DETAILS"),
]


def _fake(monkeypatch, rows):
    def scan(doc, pages=None, numbers=True):
        out = [{"page": i, "number": n, "title": t}
               for i, (n, t) in enumerate(rows)]
        return [r for r in out if pages is None or r["page"] in pages]
    monkeypatch.setattr(sheets, "scan", scan)


def _nums(rows, pages):
    return [rows[p][0] for p in pages]


def test_plant_set_takes_off_the_area_piping_plans(monkeypatch):
    _fake(monkeypatch, PLANT)
    got = _nums(PLANT, heavy.pipe_plan_pages(None))
    # pre/post-development drainage plans are drainage-area maps
    assert got == ["C008", "C009", "C013"]


def test_overall_plan_kept_when_it_is_the_only_one(monkeypatch):
    rows = [("C101", "OVERALL UTILITY PLAN"), ("CD01", "DETAILS")]
    _fake(monkeypatch, rows)
    assert _nums(rows, heavy.pipe_plan_pages(None)) == ["C101"]


def test_plan_and_profile_is_a_pipe_sheet(monkeypatch):
    rows = [("C201", "SANITARY SEWER PLAN AND PROFILE"),
            ("C202", "SANITARY SEWER PROFILES")]
    _fake(monkeypatch, rows)
    assert _nums(rows, heavy.pipe_plan_pages(None)) == ["C201"]


def test_loose_never_takes_notes_details_or_demolition(monkeypatch):
    rows = [("C001", "GENERAL NOTES"), ("C005", "DEMOLITION PLAN"),
            ("C100", "YARD PLAN"), ("C017", "GRADING PLAN"),
            ("CD01", "STANDARD DETAILS")]
    _fake(monkeypatch, rows)
    assert heavy.pipe_plan_pages(None) == []
    assert _nums(rows, heavy.pipe_plan_pages(None, loose=True)) == ["C100"]


def test_plumbing_sheets_are_not_civil(monkeypatch):
    rows = [("P201", "WATER PIPING PLAN"), ("C300", "WATER PLAN")]
    _fake(monkeypatch, rows)
    assert _nums(rows, heavy.pipe_plan_pages(None)) == ["C300"]


def test_titles_read_from_the_title_block_feed_the_picker():
    """Hazen title blocks have no TITLE label: the title sits left of
    DRAWING NUMBER in the sheet number's lettering."""
    words = [(2005, 1452, 2050, 1471, "CIVIL"),
             (1886, 1475, 1975, 1494, "PROCESS"),
             (1983, 1475, 2045, 1494, "PIPING"),
             (2052, 1475, 2100, 1494, "PLAN"),
             (2107, 1475, 2155, 1494, "AREA"),
             (2163, 1475, 2175, 1494, "1"),
             (2239, 1477, 2290, 1487, "DRAWING"),
             (2239, 1488, 2290, 1498, "NUMBER:"),
             (2337, 1395, 2365, 1409, "MAY"),
             (1736, 1434, 1760, 1453, "SC"),
             (2355, 1517, 2400, 1536, "C008")]
    num, title = sheets.sheet_info(words, 2448, 1584)
    assert num == "C008"
    assert title == "CIVIL PROCESS PIPING PLAN AREA 1"
