"""Company file-name rule: date first (Jon, Oct 23 2026)."""
from datetime import date

from app import reportname as rn


def test_example_from_jon():
    assert rn.report_file_name("PPR Report", "Project Name", 1,
                               date(2026, 10, 23)) == \
        "2026.10.23 Project Name PPR Report 001.pdf"


def test_iso_text_date_padding_and_bad_characters():
    assert rn.report_file_name("PPR Report", 'Main St: "Phase 2"/A', "12",
                               "2026-01-05") == \
        "2026.01.05 Main St- -Phase 2-A PPR Report 012.pdf"
    assert rn.report_file_name("Daily Log", "", None, "2026-03-09",
                               ext=".xlsx") == "2026.03.09 Daily Log.xlsx"
    assert rn.report_file_name("PPR Report", "X", "A-3", "2026-03-09") == \
        "2026.03.09 X PPR Report A-3.pdf"


def test_date_always_first_and_today_when_missing():
    name = rn.report_file_name("PPR Report", "Job", 7)
    assert name.startswith(date.today().strftime("%Y.%m.%d") + " ")
    assert sorted([rn.report_file_name("R", "J", 1, "2026-12-01"),
                   rn.report_file_name("R", "J", 2, "2027-01-02")])[0] \
        .startswith("2026.12.01")
