"""Shared fixtures for the 1.1.1 service-desk tests. Made-up data only."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

COMPANY = {
    "name": "Test Plumbing Co",
    "address": "9 Test Ave\nTest City",
    "phone": "555-0100",
    "email": "office@example.test",
    "website": "",
    "license": "T-100",
    "logo": "",
    "signer": "A Tester",
    "title": "Owner",
}


def isolate(tmp_path, monkeypatch):
    """Point settings.DIR at this test's folder. Call from an autouse fixture
    in the test module (pytest does not autouse a fixture that only lives
    in an imported helper)."""
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_cache", {})
    os.makedirs(settings.DIR, exist_ok=True)
    return settings.DIR


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def records():
    from app.estimating import service
    store = service.blank()
    prop = service.add_property(store, "Test Smith house", "1 Test St",
                                customer="Test Smith")
    eq = service.add_equipment(store, prop, "Furnace", make="TestCo",
                               model="TF-80", serial="SN-TEST-1",
                               installed="2024-01-15", warranty_months=12)
    return store, prop, eq


def png(path, rgb=(0.2, 0.45, 0.7)):
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=40, height=30)
    page.draw_rect(fitz.Rect(0, 0, 40, 30), color=None, fill=rgb)
    page.get_pixmap().save(str(path))
    doc.close()
    return str(path)


def use_company(monkeypatch, comp=None):
    from app import proposal
    data = dict(COMPANY if comp is None else comp)
    monkeypatch.setattr(proposal, "company", lambda: dict(data))
    return data
