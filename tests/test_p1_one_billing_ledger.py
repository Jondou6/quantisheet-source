"""P1 'one billing ledger': the Contract & Billing ledger kept inside a
PDF comes into the drawing's Project Center job once; nothing is merged
into a job that already has billing (made-up job)."""
import fitz
import pytest

from app import money, settings
from app.pm import ledger_import as li
from app.pm.store import ProjectStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    return ProjectStore(str(tmp_path / "job"))


def _ledger():
    d = fitz.open()
    d.new_page()
    money.set_info(d, owner="Example Owner")
    money.set_sov(d, [{"item": "1", "desc": "Sitework", "scheduled": 1000},
                      {"item": "2", "desc": "Concrete", "scheduled": 3000}])
    money.new_pay_app(d, "2026-11-30")
    money.set_progress(d, 1, "1", work=400)
    money.certify(d, 1)
    return d


def test_ledger_comes_into_the_job_once(store):
    d = _ledger()
    pv = li.preview(d, store)
    assert (pv["contract"], pv["pay_apps"], pv["certified"],
            pv["blocked"]) == (2, 1, 1, "")
    li.run(d, store)
    assert sorted(c["item"] for c in store.list("contract")) == ["1", "2"]
    apps = store.list("payapp")
    assert len(apps) == 1 and apps[0]["status"] == "Certified"
    assert apps[0]["certified_values"]                # frozen (NW-07)
    assert store.setting("billing_ledger") == "project"
    assert store.setting("owner") == "Example Owner"
    assert li.preview(d, store)["blocked"]            # not twice
    with pytest.raises(li.LedgerImportError):
        li.run(d, store)


def test_an_empty_pdf_ledger_brings_nothing(store):
    d = fitz.open()
    d.new_page()
    assert "no billing" in li.preview(d, store)["blocked"]
