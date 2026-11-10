"""QW6 callback flag and the wider customer history (1.2 phase 2, Nov
5): a return to the same unit within N days is a callback; history adds
backflow tests and agreement visits. Made-up data only."""
import pytest

from app import settings
from app.estimating import service
from app.service import agreements, backflow, history, workorder
from r111_support import isolate, qapp, records  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _close(st, w, when):
    workorder.add_time(st, w, "A Tester", "1", when=when)
    workorder.no_parts(st, w)
    workorder.close(st, w, notes="Checked it.", when=when)


def test_callback_within_n_days_on_the_same_unit():
    rec, prop, eq = records()
    other = service.add_equipment(rec, prop, "AC", serial="SN-2")
    st = workorder.blank()
    workorder.set_rates(st, "100", "40")
    w1 = workorder.add(st, rec, property_id=prop, equipment_id=eq,
                       complaint="No heat", when="2026-10-01")
    _close(st, w1, "2026-10-02")
    w2 = workorder.add(st, rec, property_id=prop, equipment_id=eq,
                       complaint="No heat again", when="2026-10-20")
    assert workorder.get(st, w2)["callback_of"] == "WO-0001"
    w3 = workorder.add(st, rec, property_id=prop, equipment_id=other,
                       complaint="Noise", when="2026-10-21")
    assert "callback_of" not in workorder.get(st, w3)      # other unit
    w4 = workorder.add(st, rec, property_id=prop, equipment_id=eq,
                       complaint="Tune-up", call_type="pm",
                       when="2026-10-22")
    assert "callback_of" not in workorder.get(st, w4)      # planned visit
    settings.set("service_callback_days", 10)
    w5 = workorder.add(st, rec, property_id=prop, equipment_id=other,
                       complaint="Noise", when="2026-11-05")
    assert "callback_of" not in workorder.get(st, w5)      # 15 days > 10
    settings.set("service_callback_days", 0)                # turned off
    w6 = workorder.add(st, rec, property_id=prop, equipment_id=eq,
                       complaint="x", when="2026-10-23")
    assert "callback_of" not in workorder.get(st, w6)


def test_history_has_backflow_visits_and_callbacks():
    rec, prop, eq = records()
    st = workorder.blank()
    workorder.set_rates(st, "100", "40")
    w1 = workorder.add(st, rec, property_id=prop, equipment_id=eq,
                       complaint="No heat", when="2026-10-01")
    _close(st, w1, "2026-10-01")
    workorder.add(st, rec, property_id=prop, equipment_id=eq,
                  complaint="No heat again", when="2026-10-15")
    ag = agreements.blank()
    agreements.add(ag, "", "900", 2, "2027-01-01", property_id=prop,
                   start="2026-01-01", records=rec)
    bf = backflow.blank()
    rep = backflow.from_service(rec, prop, eq)
    rep.update(test_date="2026-05-01", dev_name="RPZ", dev_serial="BF-SN-1",
               tester="A Tester")
    backflow.add(bf, rep)
    h = history.history(customer="Test Smith", records=rec, orders=st,
                        agreements=ag, backflow=bf, today="2026-08-01")
    assert h["totals"]["callbacks"] == 1
    assert h["totals"]["backflow_tests"] == 1
    whats = [e[1] for e in h["events"]]
    assert "Backflow test" in whats and "Agreement visit" in whats
    assert any("CALLBACK (after WO-0001)" in e[3] for e in h["events"])
    states = {v["date"]: v["state"] for v in h["visits"]}
    assert states == {"2026-01-01": "due", "2026-07-01": "due"}
    assert "1 callback(s)" in history.summary_lines(h)[0]
