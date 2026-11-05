"""Master Schedule: settings, ownership slice, assign-subs helper, cycle."""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.pm import schema                                       # noqa: E402
from app.pm.master import cycle, model                         # noqa: E402
from r39_master_fixtures import ACME, BEST, act, make_store     # noqa: E402


def test_activity_has_owning_subcontractor_field():
    keys = [f["key"] for f in schema.TOOLS["activity"]["fields"]]
    assert "owner_co" in keys
    f = next(f for f in schema.TOOLS["activity"]["fields"]
             if f["key"] == "owner_co")
    assert f["label"] == "Owning subcontractor" and not f["quick"]
    # nothing else about the activity tool moved
    assert keys[-1] == "notes" and keys.index("owner_co") == len(keys) - 2
    assert "schedsub" not in schema.TOOLS       # no new Project Center page


def test_defaults_are_jons_rules_and_open_defaults(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    c = model.config(s)
    assert c["auto_accept"] == {"progress_only": True,
                                "max_slip_workdays": 0}
    assert c["cycle"]["nth"] == 3 and c["cycle"]["weekday"] == "Thu"
    assert c["rollup"] == "one_line"                 # OPEN Q5 default
    assert c["approval"] == "whole"                  # OPEN Q7 default
    assert c["sub_links"] is False                   # OPEN Q8 default
    assert c["manual_entry_review"] is True          # OPEN Q11 default
    assert c["web_upload"] is False                  # OPEN Q5(hub) default
    assert c["inbox_layout"] == "per_sub"            # OPEN Q3 default
    # reading the defaults writes nothing
    assert s.setting(model.SETTING) is None


def test_config_cannot_raise_slip_threshold_above_zero(tmp_path,
                                                        monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        model.set_config(s, auto_accept={"progress_only": True,
                                         "max_slip_workdays": 3})
    model.set_config(s, auto_accept={"progress_only": False,
                                     "max_slip_workdays": 0})
    assert model.config(s)["auto_accept"]["progress_only"] is False


def test_project_id_and_key_are_stable(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    a, k = model.project_id(s), model.template_key(s)
    assert a == model.project_id(s) and k == model.template_key(s)
    assert len(k) == 32


def test_slice_is_owner_company_without_milestones(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    ids = model.slice_ids(s, "acme electric")
    assert sorted(act(s, n)["_id"] for n in ("A0002", "A0005")) == \
        sorted(ids)
    m = act(s, "A0006")
    m["owner_co"] = ACME
    s.save_record("activity", m)                 # milestones stay GC-owned
    assert m["_id"] not in model.slice_ids(s, ACME)
    assert model.companies(s) == [ACME, BEST]


def test_assign_subs_helper_needs_confirm(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    a = act(s, "A0003")
    a["owner_co"] = ""
    s.save_record("activity", a)
    props = model.propose_owners(s)
    assert [(p["_no"], p["company"]) for p in props] == [("A0003", BEST)]
    before = s.list("activity")
    with pytest.raises(PermissionError):
        model.apply_owners(s, props)                 # never silently
    assert s.list("activity") == before
    assert model.apply_owners(s, props, confirm=True) == 1
    assert act(s, "A0003")["owner_co"] == BEST


@pytest.mark.parametrize("nth,month,want", [
    ("last", (2026, 10), "2026-10-29"), ("last", (2026, 11), "2026-11-26"),
    (1, (2026, 11), "2026-11-05"), (2, (2026, 12), "2026-12-10"),
    (4, (2027, 2), "2027-02-25"), ("last", (2027, 4), "2027-04-29")])
def test_monthly_thursday(nth, month, want):
    assert cycle.data_date({"nth": nth, "weekday": "Thu"}, *month) == \
        dt.date.fromisoformat(want)


def test_24_months_all_thursdays_in_month():
    for nth in (1, 2, 3, 4, "last"):
        for k in range(24):
            y, m = 2026 + (k // 12), k % 12 + 1
            d = cycle.data_date({"nth": nth, "weekday": "Thu"}, y, m)
            assert d.weekday() == 3 and (d.year, d.month) == (y, m)
            if nth == "last":
                assert (d + dt.timedelta(days=7)).month != m


def test_next_cycle_and_holiday_warning(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    cfg = dict(model.config(s)["cycle"], nth="last")   # default is 3rd now
    assert cycle.next_date(cfg, dt.date(2026, 11, 6)) == \
        dt.date(2026, 11, 26)
    assert cycle.next_date(cfg, dt.date(2026, 11, 27)) == \
        dt.date(2026, 12, 31)
    w = cycle.warnings(s, dt.date(2026, 11, 26))
    assert w and "holiday" in w[0].lower()       # Thanksgiving (4.16)
    assert cycle.warnings(s, dt.date(2026, 12, 31)) == []
    with pytest.raises(ValueError):
        cycle.data_date({"nth": 5, "weekday": "Thu"}, 2026, 1)
