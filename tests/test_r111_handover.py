"""Closeout equipment becomes service records, then a PM agreement is offered."""
import os

import fitz
import pytest

from app.estimating import service
from app.service import agreements, handover
from r111_support import isolate, qapp, records  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


TEXT = """\
Rooftop unit
Make: TestAir
Model: TA-100
Serial: SN-TEST-9
Warranty: 12 months

Air handler
Make: TestAir
Model: AH-2
Serial: SN-AH-2
Warranty: 5 years
"""


def test_parser_reads_blocks_and_warranty_years():
    found = handover.parse_text(TEXT)
    assert len(found) == 2
    assert found[0]["kind"] == "Rooftop unit"
    assert found[0]["model"] == "TA-100"
    assert found[0]["serial"] == "SN-TEST-9"
    assert found[0]["warranty_months"] == 12
    assert found[1]["warranty_months"] == 60
    assert found[1]["make"] == "TestAir"


def test_approved_submittals_and_om_pdfs_become_records(tmp_path):
    rec, prop, _eq = records()
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in ("Boiler", "Make: TestHeat", "Model: TB-1",
                 "Serial: SN-OM-1", "Warranty: 24 months"):
        page.insert_text((72, y), line, fontsize=12)
        y += 16
    pdf = str(tmp_path / "om.pdf")
    doc.save(pdf)
    doc.close()
    submittals = [
        {"_no": "23 00 00-001", "title": "RTU", "status": "Approved",
         "type": "O&M Manuals", "description": TEXT},
        {"title": "Draft unit", "status": "Draft", "type": "Product Data",
         "description": "Model: HIDDEN\nSerial: SN-NOPE"},
        {"title": "Noted", "status": "Approved as Noted", "type": "Warranty",
         "description": "Pump\nMake: TestFlo\nModel: P-9\nSerial: SN-P-9\n"
                        "Warranty: 18 months"},
    ]
    result = handover.import_closeout(
        rec, prop, "2026-06-01", submittals=submittals, documents=[pdf])
    serials = {e["serial"] for e in rec["equipment"]}
    assert "SN-TEST-9" in serials
    assert "SN-AH-2" in serials
    assert "SN-P-9" in serials
    assert "SN-OM-1" in serials
    assert "SN-NOPE" not in serials
    assert "SN-TEST-1" in serials  # the furnace already on the record
    created = {c["serial"]: c for c in result["created"]}
    assert created["SN-AH-2"]["warranty_months"] == 60
    unit = service.find(rec, created["SN-OM-1"]["id"])
    assert unit["installed"] == "2026-06-01"
    assert unit["model"] == "TB-1"
    assert service.warranty_end(unit).isoformat() == "2028-06-01"
    offer = result["offer"]
    assert offer["price"] == ""
    assert offer["visits_per_year"] == 2
    assert offer["renewal"] == "2027-06-01"
    assert offer["customer"] == "Test Smith"
    ag = agreements.blank()
    assert ag["agreements"] == []
    aid = handover.accept_offer(offer, ag, "480", records=rec)
    agr = agreements.get(ag, aid)
    assert agr["price"] == "480.00"
    assert agr["visits_per_year"] == 2
    assert agr["property_id"] == prop
    # running it again does not duplicate the serials
    again = handover.import_closeout(
        rec, prop, "2026-06-01", submittals=submittals, documents=[pdf])
    assert again["created"] == []
    assert again["offer"] is not None
    assert any(s["why"].startswith("already") for s in again["skipped"])


def test_window_imports_pasted_closeout_and_accepts_the_agreement(qapp):
    from app.service.handover_ui import HandoverWindow
    rec, _prop, _eq = records()
    service.save(rec)
    win = HandoverWindow()
    win.body.setPlainText(TEXT)
    win.start.setText("2026-06-01")
    win.read_clicked()
    assert win.table.rowCount() == 2
    assert len(service.load()["equipment"]) == 1  # nothing saved yet
    win.import_clicked()
    assert len(service.load()["equipment"]) == 3
    assert "not saved yet" in win.offer_lbl.text()
    assert agreements.load()["agreements"] == []
    win.price.setText("480")
    win.accept_clicked()
    saved = agreements.load()["agreements"]
    assert len(saved) == 1
    assert saved[0]["price"] == "480.00"
    assert saved[0]["renewal"] == "2027-06-01"
    win.close()
    assert os.path.isdir(os.path.dirname(service.default_path()))
