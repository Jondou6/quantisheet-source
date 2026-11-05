"""P2-07 employee self-service (7.1-7.2) and P2-08 mobile / offline punches
(8.1-8.2), against the optional server run in-process (no network)."""
import math
from datetime import datetime, timedelta, timezone

import pytest

from quantisheet_backoffice import hr, payroll, provider, remote, timeentry
from quantisheet_backoffice.server.app import ServerApp

from .m3_helpers import WEEK, add_hr, approve_time

TOKEN = "office-token-0123456789abcdef"
ET = timezone(timedelta(hours=-4))


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def srv(tmp_path):
    from cryptography.fernet import Fernet
    clk = Clock(datetime(2026, 10, 20, 9, 30, tzinfo=ET))
    app = ServerApp(str(tmp_path / "server"), key=Fernet.generate_key(),
                    office_token=TOKEN, now=clk)
    app.clock = clk
    return app


@pytest.fixture
def hro(office):
    add_hr(office)
    office.act_as("hr@bo.test")
    return office


def _two(o, job, srv):
    a = hr.add_employee(o, "M. Chen", "E101", "2026-03-02", labor_class="LAB",
                        address="12 Elm St", ssn="900-00-1234",
                        bank_account="000099996789")
    b = hr.add_employee(o, "J. Park", "E302", "2025-05-01", labor_class="LAB")
    remote.set_password(o, a, "temp-pass-chen1")
    remote.set_password(o, b, "temp-pass-park1")
    # one imported register row each, so each has a pay stub
    ids = []
    for e in (a, b):
        wid = hr.employee(o, e)["worker_id"]
        payroll.pay_setup(o, wid, pay_rate="30.00")
        ids += [timeentry.add_line(o, wid, d, job, "03-3000", "8")
                for d in WEEK]
    approve_time(o, ids)
    pid = payroll.add_period(o, "2026-10-19", "2026-10-25", "2026-10-30")
    payroll.finalize(o, pid)
    m = provider.add_map(o, "Generic CSV")
    provider.import_register(o, pid, m, text=(
        "Employee number,Gross,Employer taxes,Federal tax,Deductions,Net,"
        "Reference\nE101,1200.00,90.00,140.00,0.00,1060.00,ACH-1\n"
        "E302,1200.00,90.00,150.00,0.00,1050.00,ACH-2\n"))
    remote.publish(o, remote.WsgiTransport(srv, TOKEN))
    return a, b


def _login(srv, no, pw):
    t = remote.WsgiTransport(srv, auth="Bearer")
    tok = t.request("POST", "/api/login", {"employee_no": no,
                                           "password": pw})["token"]
    return remote.WsgiTransport(srv, tok, auth="Bearer")


def test_7_1_worker_cannot_open_another_workers_stub(hro, job, srv):
    _two(hro, job, srv)
    chen = _login(srv, "E101", "temp-pass-chen1")
    park = _login(srv, "E302", "temp-pass-park1")
    (mine,) = chen.request("GET", "/api/stubs")
    (theirs,) = park.request("GET", "/api/stubs")
    assert mine["net"] == "1060.00"
    assert chen.request("GET", f"/api/stubs/{mine['id']}")["gross"] == \
        "1200.00"
    with pytest.raises(remote.RemoteError, match="404"):
        chen.request("GET", f"/api/stubs/{theirs['id']}")
    (log,) = srv.logs("stub not found")
    assert log["who"] == "E101" and theirs["id"] in log["detail"]
    me = chen.request("GET", "/api/me")
    assert me["ssn"] == "***-**-1234" and me["bank"] == "********6789"
    assert "900-00" not in str(me)


def test_7_2_address_change_waits_for_hr(hro, job, srv):
    a, _ = _two(hro, job, srv)
    chen = _login(srv, "E101", "temp-pass-chen1")
    chen.request("POST", "/api/me", {"field": "address",
                                     "value": "88 Oak Ave"})
    assert chen.request("GET", "/api/me")["waiting_for_hr"] == [
        {"field": "address", "value": "88 Oak Ave"}]
    res = remote.pull(hro, remote.WsgiTransport(srv, TOKEN))
    assert res["changes"] == 1
    (req,) = hr.change_queue(hro)
    assert (req["name"], req["field"], req["value"], req["source"]) == \
        ("M. Chen", "address", "88 Oak Ave", "self-service")
    assert hr.employee(hro, a)["address"] == "12 Elm St"
    assert remote.pull(hro, remote.WsgiTransport(srv, TOKEN))["changes"] == 0
    hr.decide_change(hro, req["id"], "approve")
    assert hr.employee(hro, a)["address"] == "88 Oak Ave"


def _north(lat, metres):
    return lat + math.degrees(metres / 6_371_000)


def _punch_setup(hro, job, srv):
    _two(hro, job, srv)
    remote.set_geofence(hro, job, "45.5231", "-122.6765", 200)
    remote.publish(hro, remote.WsgiTransport(srv, TOKEN))
    return _login(srv, "E101", "temp-pass-chen1")


def test_8_1_offline_punch_keeps_punch_time_and_sync_time(hro, job, srv):
    chen = _punch_setup(hro, job, srv)
    srv.clock.t = datetime(2026, 10, 20, 9, 30, tzinfo=ET)
    (r,) = chen.request("POST", "/api/punch", {"punches": [{
        "id": "p-1", "kind": "in", "time": "2026-10-20T06:58:00-04:00",
        "job": "2611", "cost_code": "03-3000", "lat": "45.5232",
        "lon": "-122.6765", "accuracy": "8"}]})
    assert r["stored"] and r["synced"] == "2026-10-20T09:30:00-04:00"
    remote.pull(hro, remote.WsgiTransport(srv, TOKEN))
    (p,) = remote.punches(hro, "2026-10-20")
    assert p["punch_time"] == "2026-10-20T06:58:00-04:00"
    assert p["synced_at"] == "2026-10-20T09:30:00-04:00"
    assert p["when"] == "in 06:58 (synced 09:30)"
    assert p["flags"] == []
    # the phone re-sends the same punch: still one
    chen.request("POST", "/api/punch", {"punches": [{
        "id": "p-1", "kind": "in", "time": "2026-10-20T06:58:00-04:00",
        "job": "2611"}]})
    remote.pull(hro, remote.WsgiTransport(srv, TOKEN))
    assert len(remote.punches(hro, "2026-10-20")) == 1


def test_8_2_punch_outside_geofence_accepted_and_flagged(hro, job, srv):
    chen = _punch_setup(hro, job, srv)
    lat = _north(45.5231, 600)
    r, _ = chen.request("POST", "/api/punch", {"punches": [{
        "id": "p-2", "kind": "in", "time": "2026-10-27T07:01:00-04:00",
        "job": "2611", "cost_code": "03-3000", "lat": str(lat),
        "lon": "-122.6765", "accuracy": "10"}, {
        "id": "p-3", "kind": "out", "time": "2026-10-27T15:31:00-04:00",
        "job": "2611", "cost_code": "03-3000", "lat": "45.5231",
        "lon": "-122.6765"}]})
    assert r["stored"] and r["inside"] is False and r["distance_m"] == 600
    remote.pull(hro, remote.WsgiTransport(srv, TOKEN))
    (x,) = remote.exceptions(hro)
    assert x["flags"] == ["outside the 200 m geofence (600 m away)"]
    wid = hr.by_number(hro, "E101")["worker_id"]
    (lid,) = remote.punches_to_time(hro, wid, "2026-10-27")
    ln = hro.db.get("time_lines", lid)
    assert (ln["hours"], ln["status"], ln["source"]) == (850, "Draft", "punch")


def test_photo_needs_consent_and_server_needs_office_token(hro, job, srv):
    chen = _punch_setup(hro, job, srv)
    (r,) = chen.request("POST", "/api/punch", {"punches": [{
        "id": "p-4", "kind": "in", "time": "2026-10-21T07:00:00-04:00",
        "job": "2611", "photo": "data:image/jpeg;base64,/9j/AA=="}]})
    assert r["photo_note"] == "photo not kept: no written consent on file"
    with pytest.raises(remote.RemoteError, match="401"):
        remote.WsgiTransport(srv, "wrong-token").request("GET", "/office/pull")
    with pytest.raises(remote.RemoteError, match="401"):
        remote.WsgiTransport(srv, "nope", auth="Bearer").request(
            "GET", "/api/stubs")
