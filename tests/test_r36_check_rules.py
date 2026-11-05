"""r36 v2 step 6 item 3: the schedule and crew-output checks are Error
Check rules; every rule can be switched off on its own (kept in the
settings file) and has How To text. Made-up data only."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                       # noqa: E402

from app import assemblies, estimate_lines as EL, settings       # noqa: E402
from app.estimating import checks, guides                        # noqa: E402
from estimate_helpers import blank_doc                           # noqa: E402

NEW = ("sched_missing", "sched_count", "sched_extra", "crew_rate",
       "crew_hours_day", "crew_days", "unit_cost_far")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


@pytest.fixture()
def app():
    return QApplication.instance() or QApplication([])


def _doc():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test zero", 0, "ea", mat=5),
               EL.new_line("Test no price", 3, "ea")])
    return d


def test_new_rules_are_listed_with_how_to_text():
    for r in NEW:
        assert r in checks.RULES and r in checks.SEVERITY
    for r in checks.RULES:
        h = checks.HOW_TO[r]
        assert len(h) > 40 and h.strip()[-1] in ".)", r


def test_every_rule_can_be_switched_off_on_its_own():
    d = _doc()
    rules = {f["rule"] for f in checks.run(d)}
    assert rules == {"zero_qty", "no_cost"}
    checks.set_rule_on("no_cost", False)
    assert checks.rules_off() == {"no_cost"}
    assert {f["rule"] for f in checks.run(d)} == {"zero_qty"}
    # kept in the settings file, so it survives a restart
    settings._cache = None
    assert checks.rules_off() == {"no_cost"}
    checks.set_rule_on("no_cost", True)
    assert {f["rule"] for f in checks.run(d)} == {"zero_qty", "no_cost"}
    # an explicit set wins over the saved one
    assert {f["rule"] for f in checks.run(d, off={"zero_qty"})} == \
        {"no_cost"}


def test_unknown_rule_names_are_refused():
    with pytest.raises(ValueError):
        checks.set_rule_on("no_such_rule", False)


def test_the_guide_explains_the_rule_switches():
    _t, text = guides.guide("check")
    assert "Rules" in text and "off" in text
    assert "schedule" in text.lower() and "crew" in text.lower()


def test_rules_dialog_switches_rules_and_shows_how_to(app):
    from app.estimating import ui
    dlg = ui.RulesDialog(None)
    assert set(dlg.boxes) == set(checks.RULES)
    assert all(b.isChecked() for b in dlg.boxes.values())
    assert checks.HOW_TO["crew_days"] in dlg.boxes["crew_days"].toolTip()
    dlg.boxes["crew_days"].setChecked(False)
    dlg.boxes["sched_extra"].setChecked(False)
    dlg.save()
    assert checks.rules_off() == {"crew_days", "sched_extra"}
    dlg2 = ui.RulesDialog(None)
    assert not dlg2.boxes["crew_days"].isChecked()


def test_check_page_has_a_rules_button_and_says_what_is_off(app):
    from test_gui import win, qapp                       # noqa: F401
    from app.estimating import ui
    src = open(ui.__file__, encoding="utf-8").read()
    assert '"Rules…"' in src or "'Rules…'" in src
    checks.set_rule_on("zero_qty", False)
    assert "1 rule(s) switched off" in ui.off_note()
    checks.set_rule_on("zero_qty", True)
    assert ui.off_note() == ""
