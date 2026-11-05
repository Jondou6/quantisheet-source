"""Master Schedule: the watched shared folder (per-sub subfolders) and
update packets."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import mail                                            # noqa: E402
from app.pm.master import apply, intake, model                  # noqa: E402
from app.pm.master.formats import excel                         # noqa: E402
from r39_master_fixtures import (ACME, BEST, CYCLE, act, fill,  # noqa: E402
                                 make_store)


@pytest.fixture
def job(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    inbox = tmp_path / "Schedule Inbox"
    for c in (ACME, BEST):
        (inbox / c).mkdir(parents=True)
    model.set_config(s, inbox=str(inbox))
    return s, inbox


def _drop(s, tmp_path, inbox, company, edits, folder=None, name="u.xlsx"):
    p = excel.generate(s, company, str(tmp_path / ("t_" + name)),
                       cycle=CYCLE)
    fill(p, edits)
    dst = inbox / (folder or company) / name
    os.replace(p, dst)
    return dst


def test_no_inbox_set(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    r = intake.scan(s, {})
    assert r["errors"] and "inbox" in r["errors"][0].lower()


def test_unreadable_inbox_is_reported(job, tmp_path):
    s, inbox = job
    model.set_config(s, inbox=str(tmp_path / "gone"))
    r = intake.scan(s, {})
    assert r["errors"] and r["picked"] == []


def test_file_picked_only_when_stable(job, tmp_path):
    s, inbox = job
    f = _drop(s, tmp_path, inbox, ACME, {"A0002": {"% complete": 60}})
    st = {}
    r1 = intake.scan(s, st)
    assert r1["picked"] == [] and r1["waiting"] == [str(f)]
    r2 = intake.scan(s, st)
    assert [x["status"] for x in r2["picked"]] == ["Auto-accepted"]
    assert r2["picked"][0]["channel"] == "folder"
    assert not f.exists()
    assert (inbox / ACME / "Processed" / "u.xlsx").exists()
    assert act(s, "A0002")["percent"] == 60


def test_changed_between_polls_waits_again(job, tmp_path):
    s, inbox = job
    f = _drop(s, tmp_path, inbox, ACME, {"A0002": {"% complete": 60}})
    st = {}
    intake.scan(s, st)
    with open(f, "ab") as fh:
        fh.write(b"\0")
    r = intake.scan(s, st)
    assert r["picked"] == [] and r["waiting"] == [str(f)]


def test_lock_and_temp_files_skipped(job):
    s, inbox = job
    for n in ("~$u.xlsx", "x.tmp", ".hidden.xlsx", "u.xlsx.part"):
        (inbox / ACME / n).write_bytes(b"x")
    st = {}
    intake.scan(s, st)
    r = intake.scan(s, st)
    assert r["picked"] == [] and r["waiting"] == []
    assert sorted(os.listdir(inbox / ACME)) == sorted(
        ["~$u.xlsx", "x.tmp", ".hidden.xlsx", "u.xlsx.part"])


def test_rejected_file_moved_with_reason_file(job, tmp_path):
    s, inbox = job
    _drop(s, tmp_path, inbox, ACME, {"A0002": {"% complete": 120,
                                               "Actual start": "soon"}})
    st = {}
    intake.scan(s, st)
    r = intake.scan(s, st)
    assert r["picked"][0]["status"] == "Rejected"
    rej = inbox / ACME / "Rejected"
    assert (rej / "u.xlsx").exists()
    why = (rej / "u.xlsx.reason.txt").read_text(encoding="utf-8")
    assert "0 to 100" in why and "isn't a date" in why


def test_wrong_folder_is_company_mismatch(job, tmp_path):
    s, inbox = job
    _drop(s, tmp_path, inbox, ACME, {"A0002": {"% complete": 60}},
          folder=BEST)
    st = {}
    intake.scan(s, st)
    r = intake.scan(s, st)
    assert r["picked"][0]["status"] == "Rejected"
    assert act(s, "A0002")["percent"] == 20


def test_duplicate_goes_to_processed_with_note(job, tmp_path):
    s, inbox = job
    f = _drop(s, tmp_path, inbox, ACME, {"A0002": {"% complete": 0}})
    data = f.read_bytes()
    st = {}
    intake.scan(s, st)
    intake.scan(s, st)
    (inbox / ACME / "again.xlsx").write_bytes(data)
    intake.scan(s, st)
    r = intake.scan(s, st)
    assert r["picked"] == [] and r["duplicates"] == [str(inbox / ACME /
                                                          "again.xlsx")]
    note = (inbox / ACME / "Processed" / "again.xlsx.reason.txt")
    assert "duplicate" in note.read_text(encoding="utf-8").lower()
    assert len(model.submissions(s)) == 1


def test_unknown_company_folder_left_alone(job, tmp_path):
    s, inbox = job
    (inbox / "Random Co").mkdir()
    (inbox / "Random Co" / "x.xlsx").write_bytes(b"x")
    st = {}
    intake.scan(s, st)
    r = intake.scan(s, st)
    assert any("Random Co" in x for x in r["skipped"])
    assert (inbox / "Random Co" / "x.xlsx").exists()


def test_prepare_packets_writes_templates_and_drafts_only(job,
                                                         monkeypatch):
    s, inbox = job
    sent = []
    monkeypatch.setattr(mail, "send", lambda *a, **k: sent.append(a))
    out = intake.prepare_packets(s, CYCLE)
    assert sorted(os.path.dirname(p) for p in out) == sorted(
        str(inbox / c / "Outbox") for c in (ACME, BEST))
    assert all(p.endswith(".xlsx") and os.path.exists(p) for p in out)
    ob = model.config(s)["outbox"]
    assert sorted(d["company"] for d in ob) == [ACME, BEST]
    assert all(d["kind"] == "reminder" and d["opened"] is None for d in ob)
    assert sent == []
    # the Outbox folder is never read as a submission
    st = {}
    intake.scan(s, st)
    assert intake.scan(s, st)["picked"] == []
