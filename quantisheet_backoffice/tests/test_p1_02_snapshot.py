"""P1-02 snapshot interface v1 (2.1-2.3)."""
import json

import pytest

from quantisheet_backoffice import billing, cents, interface, jobs

from .helpers import import_stage, stage


def test_2_1_maple_ridge_import(office):
    r = import_stage(office, 1)
    assert r.counts["sov"] == 3
    assert r.counts["changes"] == 2          # CO-001 executed + COR-002 pending
    assert sum(1 for c in jobs.section(office, r.job_id, "changes")
               if c["stage"] == "co") == 1
    assert r.certified_apps == 2
    assert r.contract_sum_to_date == cents.to_cents("525000.00")
    assert interface.original_contract(
        jobs.section(office, r.job_id, "sov")) == 50_000_000
    assert r.rejected == []


def test_2_2_float_negative_and_version(office, tmp_path):
    s = stage(1)
    s["estimate"].append({"code": "03-3000", "description": "Rebar",
                          "category": "M", "quantity": 12.5, "unit": "TON",
                          "amount": "900.00"})
    s["estimate"].append({"code": "03-3000", "description": "Forms",
                          "category": "M", "quantity": "-3", "unit": "SF",
                          "amount": "50.00"})
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(s))
    snap = interface.load_snapshot(str(p))
    rej = {r[1]: r[2] for r in snap.rejected}
    assert len(snap.rejected) == 2
    assert any("12.5" in why and "decimal string" in why for why in rej.values())
    assert any("negative" in why for why in rej.values())
    kept = {k for k in snap.sections["estimate"]}
    assert not any("Rebar" in k or "Forms" in k for k in kept)   # never 0
    r = jobs.import_snapshot(office, snap)
    descs = [e["description"] for e in jobs.section(office, r.job_id, "estimate")]
    assert "Rebar" not in descs and "Forms" not in descs
    s["interface_version"] = 2
    p.write_text(json.dumps(s))
    with pytest.raises(interface.SnapshotError, match="interface_version 2"):
        interface.load_snapshot(str(p))


def test_2_3_reimport_lists_one_newly_certified_app(office):
    r1 = import_stage(office, 1)
    billing.set_contract(office, r1.job_id)
    inv = billing.invoice_from_payapp(office, r1.job_id, 1)
    before_inv = office.db.get("ar_invoices", inv)
    app1_before = jobs.record(office, r1.job_id, "payapps", "1")
    r2 = import_stage(office, 2)
    newly = [c for c in r2.changes if c.startswith("Newly certified")]
    assert newly == ["Newly certified pay application 3 (period to 2026-10-31)"]
    assert r2.changes == newly
    assert office.db.get("ar_invoices", inv) == before_inv
    assert jobs.record(office, r2.job_id, "payapps", "1") == app1_before
