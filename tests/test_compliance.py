"""Vendor compliance before paying (insurance, license, W-9, lien
waivers), as Sage 300 and Procore enforce it."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                     # noqa: E402
from app.pm import actions, cost, report                     # noqa: E402
from app.pm.store import ProjectStore                        # noqa: E402


def test_compliance_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    s = ProjectStore(str(tmp_path / "job"))
    c = s.save_record("commitment", {
        "title": "Concrete", "vendor": "Sam Sub", "type": "Subcontract",
        "status": "Executed", "insurance_expires": "2020-01-01", "w9": "No",
        "lines": [{"cost_code": "03 30 00", "amount": 100000}]})
    inv = s.save_record("cost", {"date": "2026-10-01", "vendor": "Sam Sub",
                                 "cost_code": "03 30 00", "amount": 25000,
                                 "commitment": c["_id"],
                                 "status": "Pending"})
    issues = cost.compliance(s, inv, "cost", today="2026-10-15")
    assert any("Insurance expired" in i for i in issues)
    assert "No W-9 on file" in issues and "No lien waiver" in issues
    assert "Insurance expired" in report.cell(s, "commitment", c,
                                              "_compliance")
    # paying asks; the default answer is not to pay
    ctx = actions.Ctx(s)
    assert actions.run(ctx, "cost", inv, "Approve")["status"] == "Approved"
    inv = s.get("cost", inv["_id"])
    assert actions.run(ctx, "cost", inv, "Mark Paid") is None
    assert s.get("cost", inv["_id"])["status"] == "Approved"
    # override is recorded
    ctx = actions.Ctx(s, ask=lambda title, options: "Pay anyway")
    out = actions.run(ctx, "cost", inv, "Mark Paid")
    assert out["status"] == "Paid" and "Pat Morgan" in \
        out["compliance_override"]
    # all in order: pays without asking
    c = s.get("commitment", c["_id"])
    c.update(insurance_expires="2099-01-01", w9="Yes")
    s.save_record("commitment", c)
    inv2 = s.save_record("cost", {"date": "2026-10-02", "vendor": "Sam Sub",
                                  "cost_code": "03 30 00", "amount": 1000,
                                  "commitment": c["_id"],
                                  "waiver": "Conditional received",
                                  "status": "Approved"})
    assert cost.compliance(s, inv2, "cost") == []
    asked = []
    ctx = actions.Ctx(s, ask=lambda t, o: asked.append(t) or o[0])
    assert actions.run(ctx, "cost", inv2, "Mark Paid")["status"] == "Paid"
    assert not asked
    assert report.cell(s, "commitment", c, "_compliance") == "OK"
