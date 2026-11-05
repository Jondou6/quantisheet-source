"""Exports open as PDF, PMXML, MSPDI and a workbook."""
import os

import fitz
import openpyxl
import pytest
from xml.etree import ElementTree as ET

from app.pm.schedacc.engine import compile_schedule
from app.pm.schedacc.export_pdf import export_pdf
from app.pm.schedacc.export_xlsx import export_xlsx
from app.pm.schedacc.export_xml import export_mspdi, export_pmxml

PM = "http://xmlns.oracle.com/Primavera/P6/V25.12/API/BusinessObjects"
MSP = "http://schemas.microsoft.com/project"


def _doc():
    text = """
SECTION 01 32 00 - CONSTRUCTION PROGRESS DOCUMENTATION
The Work shall be substantially complete within one hundred eighty (180) calendar days after Notice to Proceed.
SECTION 03 30 00 - CAST-IN-PLACE CONCRETE
Concrete shall achieve a 28-day cure.
SECTION 05 12 00 - STRUCTURAL STEEL FRAMING
Structural steel lead time is 10 weeks.
"""
    pages, n = [], 1
    for part in text.strip().split("SECTION "):
        if part.strip():
            pages.append((n, "SECTION " + part))
            n += 1
    return compile_schedule(
        spec_pages=pages, project_type="ground_up_commercial",
        ntp="2026-03-02", settings={"allow_ai": False}, holidays=[],
        project_name="Cedar Annex")


def test_pdf_has_narrative_table_and_bars(tmp_path):
    doc = _doc()
    path = export_pdf(doc, str(tmp_path / "schedule.pdf"))
    pdf = fitz.open(path)
    assert pdf.page_count >= 2
    text = "\n".join(page.get_text() for page in pdf)
    assert "Basis of schedule" in text
    assert "Cedar Annex" in text
    assert "NOT FINISHED" in text or "FINISHED" in text
    assert "Activities" in text
    # A drawn bar is a filled path, not just text.
    assert any(page.get_drawings() for page in pdf)
    low = text.lower()
    assert "primavera" not in low and "microsoft project" not in low


def test_pmxml_and_mspdi_parse(tmp_path):
    doc = _doc()
    px = export_pmxml(doc, str(tmp_path / "schedule.xml"))
    mx = export_mspdi(doc, str(tmp_path / "schedule.msp.xml"))
    proot = ET.parse(px).getroot()
    assert proot.tag == f"{{{PM}}}APIBusinessObjects"
    acts = proot.findall(f".//{{{PM}}}Activity")
    rels = proot.findall(f".//{{{PM}}}Relationship")
    cals = proot.findall(f".//{{{PM}}}Calendar")
    assert len(acts) == len(doc["activities"])
    assert len(rels) == len(doc["relationships"])
    assert len(cals) == len(doc["calendars"])
    types = {a.findtext(f"{{{PM}}}Type") for a in acts}
    assert "Task Dependent" in types
    assert "Start Milestone" in types or "Finish Milestone" in types
    rel_types = {r.findtext(f"{{{PM}}}Type") for r in rels}
    assert "Finish to Start" in rel_types
    # Hours, not a prose duration.
    assert proot.find(f".//{{{PM}}}PlannedDuration").text
    week = cals[0].find(f"{{{PM}}}StandardWorkWeek")
    assert len(week.findall(f"{{{PM}}}StandardWorkHours")) == 7

    mroot = ET.parse(mx).getroot()
    tasks = mroot.findall(f".//{{{MSP}}}Task")
    assert len(tasks) > len(doc["activities"])  # WBS summaries plus activities
    assert mroot.find(f".//{{{MSP}}}PredecessorLink") is not None
    # Losses stay off the file the user opens.
    xml = open(mx, encoding="utf-8").read().lower()
    assert "primavera" not in xml
    assert doc["export_losses"] == [] or all(
        "saved as" in line or "was not written" in line
        for line in doc["export_losses"])


def test_workbook_columns(tmp_path):
    doc = _doc()
    path = export_xlsx(doc, str(tmp_path / "schedule.xlsx"))
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    headers = [c.value for c in ws[1]]
    for name in ("WBS", "Activity ID", "Duration (workdays)", "Total float",
                 "Predecessors", "Calendar", "Early start"):
        assert name in headers
    assert ws.max_row == len(doc["activities"]) + 1
    assert ws["B2"].value


def test_apply_to_store_uses_the_existing_health_check(tmp_path, monkeypatch):
    from app import settings
    from app.pm import schedule_check
    from app.pm.schedacc.apply import apply_to_store
    from app.pm.store import ProjectStore
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    doc = _doc()
    store = ProjectStore(str(tmp_path / "job"))
    store.data["name"] = "Cedar Annex"
    result = apply_to_store(store, doc, replace=True)
    assert result["activities"] == len(doc["activities"])
    assert store.list("activity")
    native = schedule_check.check(store, today="2026-03-02")
    assert len(native["items"]) == 14
    # The store pass is the existing one, reported beside ours.
    from app.pm.schedacc import health
    report = health.check(doc, store=store, today="2026-03-02")
    assert "native" in report and len(report["native"]["items"]) == 14
