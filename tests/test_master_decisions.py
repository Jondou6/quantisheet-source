"""Jon's Master Schedule answers (Oct 28): Q2 3rd Thursday, Q3/Q5 a
Dropbox inbox, Q4 owners by CSI code, Q6 MS Project / P6 always reviewed,
Q7 the project manager approves, Q8 subs can't change logic. Made-up job
and a fake Dropbox - nothing goes over the network."""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.pm.master import (apply, cycle, drafts, dropbox_inbox,  # noqa: E402
                           extras, intake, model)
from app.pm.master.formats import excel                          # noqa: E402
from app.pm.store import ProjectStore                            # noqa: E402
from r39_master_fixtures import (ACME, BEST, act, fill,          # noqa: E402
                                 make_store, msp_xml)


@pytest.fixture
def s(tmp_path, monkeypatch):
    return make_store(tmp_path, monkeypatch)


# ---------------------------------------------------------------- Q2
def test_q2_third_thursday_by_default(s):
    c = model.config(s)["cycle"]
    assert c["nth"] == 3
    assert cycle.data_date(c, 2026, 11) == dt.date(2026, 11, 19)
    assert cycle.data_date(c, 2027, 1) == dt.date(2027, 1, 21)


# ---------------------------------------------------------------- Q4
def _bare(s, no, **f):
    a = act(s, no)
    a.update(owner_co="", responsible="", **f)
    s.save_record("activity", a)


def test_q4_concrete_sub_owns_033000_from_settings(s):
    s.save_record("activity", {"name": "033000 Footings", "duration": 4})
    model.set_config(s, csi_owners={"033000": "Example Concrete"})
    props = {p["name"]: p for p in model.propose_owners(s)}
    p = props["033000 Footings"]
    assert p["company"] == "Example Concrete" and p["csi"] == "03 30 00"
    assert "Settings" in p["why"]


def test_q4_commitment_cost_codes_and_csi_group(s):
    _bare(s, "A0002", cost_code="26 05 19 Wire")
    s.save_record("commitment", {"title": "Electrical", "vendor": "Ann Volt",
                                 "type": "Subcontract", "status": "Draft",
                                 "lines": [{"cost_code": "26 05 00",
                                            "amount": 1}]})
    p = {x["_no"]: x for x in model.propose_owners(s)}["A0002"]
    assert p["company"] == ACME             # the vendor's Directory company
    assert "same CSI group" in p["why"]


def test_q4_void_commitment_and_awarded_bid(s):
    _bare(s, "A0003", cost_code="22 11 16")
    s.save_record("commitment", {"title": "Old", "vendor": "Old Pipe Co",
                                 "status": "Void", "lines": [
                                     {"cost_code": "22 11 16"}]})
    s.save_record("bidpkg", {"title": "Plumbing", "trades": "22 11 16",
                             "status": "Awarded", "awarded_to": BEST})
    p = {x["_no"]: x for x in model.propose_owners(s)}["A0003"]
    assert p["company"] == BEST


def test_q4_two_subs_one_section_not_guessed(s):
    _bare(s, "A0003", cost_code="22 11 16")
    for v in (ACME, BEST):
        s.save_record("commitment", {"title": v, "vendor": v, "lines": [
            {"cost_code": "22 11 16"}]})
    assert "A0003" not in {x["_no"] for x in model.propose_owners(s)}
    why = {x["_no"]: x["why"] for x in model.unassigned(s)}["A0003"]
    assert "more than one sub" in why


def test_q4_no_code_falls_back_to_responsible(s):
    a = act(s, "A0003")
    a["owner_co"] = ""
    s.save_record("activity", a)
    p = {x["_no"]: x for x in model.propose_owners(s)}["A0003"]
    assert p["company"] == BEST and "Responsible" in p["why"]


# ---------------------------------------------------------------- Q7
def _as_role(monkeypatch, role):
    monkeypatch.setattr(ProjectStore, "role", property(lambda self: role))


def _pending(s, tmp_path):
    p = str(tmp_path / "u.xlsx")
    excel.generate(s, ACME, p, cycle="2026-11-05")
    fill(p, {"A0002": {"Duration (workdays)": 9}})
    sub = apply.receive(s, p, ACME, channel="manual")
    assert sub["status"] == "Pending review", sub.get("why")
    return sub


def test_q7_only_the_pm_approves(s, tmp_path, monkeypatch):
    sub = _pending(s, tmp_path)
    for role in ("estimator", "sub", "viewer"):
        _as_role(monkeypatch, role)
        assert not model.can_approve(s)
        with pytest.raises(PermissionError):
            apply.approve(s, sub["_id"])
        with pytest.raises(PermissionError):
            apply.decline(s, sub["_id"], "no")
        with pytest.raises(PermissionError):
            extras.approve_lines(s, sub["_id"], [])
    _as_role(monkeypatch, "pm")
    assert apply.approve(s, sub["_id"])["status"] == "Approved"
    _as_role(monkeypatch, "estimator")
    with pytest.raises(PermissionError):
        apply.revert(s, sub["_id"])


def test_q7_inbox_checked_only_by_the_pm(s, tmp_path, monkeypatch):
    model.set_config(s, inbox=str(tmp_path / "in"))
    _as_role(monkeypatch, "estimator")
    r = intake.scan(s, {})
    assert r["picked"] == [] and "project manager" in r["errors"][0]


# ---------------------------------------------------------------- Q6
def test_q6_msp_file_always_reviewed(s, tmp_path):
    model.set_config(s, cycle={"nth": 1})
    p = msp_xml(tmp_path / "a.xml", [
        {"uid": 1, "name": "Rough-in electrical", "hours": 40, "pct": 60,
         "astart": "2026-11-04", "text30": "A0002"},
        {"uid": 2, "name": "Trim electrical", "hours": 24,
         "text30": "A0005"}])
    sub = apply.receive(s, p, ACME, channel="manual")
    assert sub["status"] == "Pending review"
    assert any("project manager" in w for w in sub["why"])
    assert act(s, "A0002")["percent"] == 20


# ---------------------------------------------------------------- Q8
def test_q8_subs_cannot_add_links_by_default(s):
    assert model.config(s)["sub_links"] is False


# ------------------------------------------------------------- Q3 / Q5
class FakeDropbox:
    def __init__(self):
        self.files = {}           # path -> bytes
        self.revs = {}
        self.moves = []

    def _entries(self, folder):
        folder = folder.rstrip("/")
        seen, out = set(), []
        for p in self.files:
            if not p.lower().startswith(folder.lower() + "/"):
                continue
            rest = p[len(folder) + 1:]
            head = rest.split("/")[0]
            if "/" in rest:
                if head not in seen:
                    seen.add(head)
                    out.append({".tag": "folder", "name": head,
                                "path_display": f"{folder}/{head}",
                                "path_lower": f"{folder}/{head}".lower()})
            else:
                out.append({".tag": "file", "name": head, "path_display": p,
                            "path_lower": p.lower(),
                            "rev": self.revs.get(p, "1")})
        return out

    def list_folder(self, path=""):
        return self._entries(path)

    def download(self, path, dest, progress=None, cancel=None):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(self.files[path])
        return {}

    def rpc(self, endpoint, args=None):
        assert endpoint == "files/move_v2"
        self.files[args["to_path"]] = self.files.pop(args["from_path"])
        self.moves.append((args["from_path"], args["to_path"]))
        return {"metadata": {"path_display": args["to_path"]}}

    def upload(self, local, path, mode="add", **k):
        with open(local, "rb") as f:
            self.files[path] = f.read()
        return {}


def test_q3_dropbox_inbox_round_trip(s, tmp_path, monkeypatch):
    fake = FakeDropbox()
    monkeypatch.setattr(dropbox_inbox, "_client", lambda: fake)
    model.set_config(s, inbox=dropbox_inbox.as_setting("/Jobs/Sched"),
                     cycle={"nth": 1})
    p = str(tmp_path / "u.xlsx")
    excel.generate(s, ACME, p, cycle="2026-11-05")
    fill(p, {"A0002": {"% complete": 60}})
    with open(p, "rb") as f:
        fake.files["/Jobs/Sched/Acme Electric/acme.xlsx"] = f.read()
    fake.files["/Jobs/Sched/Nobody Inc/x.xlsx"] = b"x"
    state = intake.state_for(s)
    r = intake.scan(s, state)
    assert [x["status"] for x in r["picked"]] == ["Auto-accepted"], r
    assert act(s, "A0002")["percent"] == 60
    assert any("Nobody Inc" in t for t in r["skipped"])
    assert "/Jobs/Sched/Nobody Inc/x.xlsx" in fake.files   # left alone
    r2 = intake.scan(s, state)                 # result goes back to Dropbox
    assert fake.moves == [("/Jobs/Sched/Acme Electric/acme.xlsx",
                           "/Jobs/Sched/Acme Electric/Processed/acme.xlsx")]
    assert r2["picked"] == []
    intake.scan(s, state)                      # nothing taken twice
    assert len(model.submissions(s)) == 1


def test_q3_packets_upload_and_reminder_link(s, monkeypatch):
    fake = FakeDropbox()
    monkeypatch.setattr(dropbox_inbox, "_client", lambda: fake)
    model.set_config(s, inbox="dropbox:/Sched", upload_links={
        ACME: "https://www.dropbox.com/request/EXAMPLE"})
    out = intake.prepare_packets(s, cycle_date="2026-11-19")
    assert out and all(dropbox_inbox.mirror_dir(s) in p for p in out)
    dropbox_inbox.sync(s)
    assert any(k.startswith("/Sched/Acme Electric/Outbox/")
               for k in fake.files)
    ob = model.config(s)["outbox"]
    acme = [d for d in ob if d["company"] == ACME][-1]
    assert "dropbox.com/request/EXAMPLE" in acme["body"]
    best = [d for d in ob if d["company"] == BEST][-1]
    assert "dropbox" not in best["body"].lower()
    assert drafts.reminder(s, ACME, "2026-11-19")["body"]


def test_q3_not_signed_in_reports_error(s, monkeypatch):
    from app import dropbox_sync as dbx

    def nope():
        raise dbx.NotSignedIn("Sign in to Dropbox first")
    monkeypatch.setattr(dropbox_inbox, "_client", nope)
    model.set_config(s, inbox="dropbox:/Sched")
    r = intake.scan(s, {})
    assert any("Sign in to Dropbox" in e for e in r["errors"])


def test_q3_make_a_dropbox_folder_for_each_sub(s, monkeypatch):
    class Fake(FakeDropbox):
        def __init__(self):
            super().__init__()
            self.folders = {"/Sched/Acme Electric"}

        def get_metadata(self, path):
            return {"x": 1} if path in self.folders else None

        def create_folder(self, path):
            self.folders.add(path)
            return {}
    fake = Fake()
    model.set_config(s, inbox="dropbox:/Sched")
    r = dropbox_inbox.make_sub_folders(s, client=fake)
    assert r["had"] == ["/Sched/Acme Electric"]
    assert r["made"] == ["/Sched/Best Plumbing"]
    assert r["errors"] == []
    model.set_config(s, inbox="C:/local")
    assert dropbox_inbox.make_sub_folders(s, client=fake)["errors"]


def test_blank_status_is_not_listed_as_a_change(s, tmp_path):
    """Review r41 F06: 'status (blank) -> Not Started' showed for an
    activity whose duration the sub changed."""
    assert not act(s, "A0003").get("status")
    p = str(tmp_path / "b.xlsx")
    excel.generate(s, BEST, p, cycle="2026-11-05")
    fill(p, {"A0003": {"Duration (workdays)": 4}})
    sub = apply.receive(s, p, BEST, channel="manual")
    fields = [(c["_no"], c["field"]) for c in sub.get("changes") or []]
    assert ("A0003", "duration") in fields
    assert ("A0003", "status") not in fields


def test_received_shown_as_date_and_time():
    """Review r41 F07: the queue showed a cut-off ISO stamp."""
    from app.pm.master.ui import _when
    out = _when("2026-10-29T08:14:05")
    assert out == "2026-10-29 08:14"
    assert _when("") == "" and "T" not in _when("2026-10-29T08:14:05+00:00")


def test_no_project_offers_to_make_one(tmp_path, monkeypatch):
    """GUI user test r42 F05: no project -> 'Make a project in this
    drawing's folder' instead of a bare folder picker."""
    from app import master_hook, settings
    from app.pm.store import ProjectStore
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test"})
    job = tmp_path / "Example Job"
    job.mkdir()

    class Win:
        _path = str(job / "plans.pdf")
    assert master_hook.where_to_start(Win(), choose=lambda: None) is None
    assert not ProjectStore.exists(str(job))
    st = master_hook.where_to_start(Win(), choose=lambda: "make")
    assert st is not None and ProjectStore.exists(str(job))
    other = tmp_path / "Other"
    other.mkdir()
    said = []
    assert master_hook.where_to_start(Win(), choose=lambda: "pick",
                                      pick=lambda: str(other),
                                      say=said.append) is None
    assert said and "no Project Center project" in said[0]
