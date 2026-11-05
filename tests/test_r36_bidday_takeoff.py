"""r36 v2 step 2: a bid-day package made from takeoff groups goes out as a
blank bid form and comes back as the bidders' CSV without losing which
takeoff group each item is - so nothing is retyped and Error Check knows
the groups are priced by the package. Made-up data only."""
import csv
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog                             # noqa: E402

from app import assemblies, estimate, settings                    # noqa: E402
from app.estimating import bidday, checks, ui                     # noqa: E402
from estimate_helpers import area, blank_doc                      # noqa: E402
from test_gui import ANSWERS, win, qapp                            # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)


def _doc():
    d = blank_doc()
    area(d, "Test ceiling A", 10, 10)
    area(d, "Test ceiling B", 10, 20, x0=300)
    return d


def test_blank_form_out_bidders_csv_back_groups_kept(tmp_path):
    d = _doc()
    sheet = bidday.new_sheet("Test ceilings", bidday.scope_from_takeoff(
        estimate.lines(d)), [])
    bidday.save(d, sheet)
    form = bidday.export_form(sheet, str(tmp_path / "form.csv"))
    rows = list(csv.reader(open(form, encoding="utf-8-sig")))
    assert rows[0][:5] == ["Item", "Description", "Unit", "Qty", "My plug"]
    assert rows[1][:4] == ["1", "Test ceiling A", "sq ft", "100"]
    rows[0] += ["Test Sub A", "Test Sub B"]
    rows[1] += ["600", "550"]
    rows[2] += ["1200", "excl"]
    back = tmp_path / "back.csv"
    with open(back, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    s2 = bidday.read_csv(str(back), "Test ceilings",
                         base=bidday.load(d, "Test ceilings"))
    assert s2["scope"][1]["group"]["name"] == "Test ceiling B"
    bidday.save(d, s2)
    bidday.apply_quote(d, "Test ceilings")
    assert not [f for f in checks.run(d) if f["rule"] == "unpriced_takeoff"]


def test_bidday_page_package_from_takeoff(win, qapp):
    d = win._view.doc
    area(d, "Test ceiling A", 10, 10)
    pg = ui.open_tools(win, "bidday").page("bidday")
    pg.refresh()
    pg.from_takeoff("Test pkg", [("Test ceiling A", "area", "sq ft")])
    s = bidday.load(d, "Test pkg")
    assert s["scope"][0]["group"]["name"] == "Test ceiling A"
    assert pg.package.currentText() == "Test pkg"
