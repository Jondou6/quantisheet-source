"""Package Tracker (Nov 3): FedEx, UPS, USPS and DHL numbers recognised,
pulled out of a pasted email, kept in a list, Track opens the carrier's
page. Made-up numbers only."""
import os

import pytest

from app import packages


def test_detect_carriers():
    assert packages.carrier("1Z999AA10123456784") == "UPS"
    assert packages.carrier("9400 1000 0000 0000 0000 00") == "USPS"
    assert packages.carrier("RA123456785US") == "USPS"
    assert packages.carrier("123456789012") == "FedEx"
    assert packages.carrier("123456789012345") == "FedEx"
    assert packages.carrier("1234567890") == "DHL"
    assert packages.carrier("JJD0123456789") == "DHL"
    assert packages.detect("9212345678901234567890")[:2] == ["USPS", "FedEx"]
    assert packages.carrier("hello") is None
    assert packages.carrier("12345") is None


def test_urls_are_the_carriers_own_pages():
    assert packages.url("1Z999AA10123456784").startswith(
        "https://www.ups.com/track?tracknum=1Z999AA10123456784")
    assert packages.url("123456789012").startswith("https://www.fedex.com/")
    assert packages.url("9400100000000000000000").startswith(
        "https://tools.usps.com/")
    assert packages.url("1234567890").startswith("https://www.dhl.com/")
    assert packages.url("1234567890", "UPS").startswith("https://www.ups.com")
    assert packages.url("zz") is None


def test_numbers_out_of_a_pasted_email():
    text = ("Your order shipped via UPS 1Z 999 AA1 01 2345 6784 and USPS "
            "tracking 9405 5118 9922 3197 4284 90. Order #12345. "
            "Questions? Call 803-555-1234.")
    assert packages.find_numbers(text) == [
        ("1Z999AA10123456784", "UPS"), ("9405511899223197428490", "USPS")]
    assert packages.find_numbers("FedEx tracking: 1234 5678 9012") == [
        ("123456789012", "FedEx")]
    assert packages.find_numbers("Call 803-555-1234 or fax 8035551235") == []


def test_list_saved_once_per_number(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path))
    items = packages.load()
    assert items == []
    a = packages.add(items, "1z999aa1 0123456784", what="Tile", job="Unit 4")
    b = packages.add(items, "1Z999AA10123456784")
    assert a is b and len(items) == 1 and a["carrier"] == "UPS"
    packages.save(items)
    assert packages.load()[0]["what"] == "Tile"
    assert os.path.isfile(os.path.join(str(tmp_path), "packages.json"))


def test_window(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from app import packages_ui, settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path))
    opened = []
    monkeypatch.setattr(packages_ui, "open_url", opened.append)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: 0))
    d = packages_ui.PackageTracker()
    d.entry.setPlainText("Shipped UPS 1Z999AA10123456784 and USPS "
                         "9405 5118 9922 3197 4284 90")
    assert "UPS" in d.found.text() and "USPS" in d.found.text()
    d.what.setText("Grout")
    assert d.add_from_entry() == 2
    assert d.table.rowCount() == 2 and len(packages.load()) == 2
    d.table.selectRow(0)
    assert d.track() == 1 and opened[-1].startswith("https://")
    assert d.track_all() == 2
    assert d.copy_number()
    assert d.change_carrier("FedEx") == "FedEx"
    from PySide6.QtCore import Qt
    d.table.item(0, 0).setCheckState(Qt.Checked)      # delivered
    app.processEvents()
    assert d.table.rowCount() == 1
    d.show_done.setChecked(True)
    assert d.table.rowCount() == 2
    d.entry.setPlainText("ABC")
    d.carrier.setCurrentIndex(0)
    assert d.add_from_entry() == 0
    d.table.selectRow(0)
    assert d.remove() == 1 and len(packages.load()) == 1
    d.close()


def test_expected_late_and_jobs(tmp_path, monkeypatch):
    import datetime
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path))
    t = datetime.date(2026, 11, 3)
    assert packages.parse_date("11/6", t) == datetime.date(2026, 11, 6)
    assert packages.parse_date("1/5", datetime.date(2026, 12, 20)) == \
        datetime.date(2027, 1, 5)
    assert packages.parse_date("2026-11-01") == datetime.date(2026, 11, 1)
    assert packages.parse_date("soon") is None
    assert packages.is_late({"expected": "2026-11-01"}, t)
    assert not packages.is_late({"expected": "2026-11-01",
                                 "delivered": True}, t)
    assert not packages.is_late({"expected": ""}, t)
    items = []
    packages.add(items, "1Z999AA10123456784", job="Unit 4",
                 expected="2026-11-06")
    packages.add(items, "1234567890", job="Aiken Shop")
    assert items[0]["expected"] == "2026-11-06"
    assert packages.jobs(items) == ["Aiken Shop", "Unit 4"]


def test_window_late_and_job_filter(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import packages_ui, settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path))
    items = []
    packages.add(items, "1Z999AA10123456784", job="Unit 4",
                 expected="2020-01-02")
    packages.add(items, "1234567890", job="Shop")
    packages.save(items)
    d = packages_ui.PackageTracker()
    assert d.table.rowCount() == 2 and d.late_label.text() == "1 late"
    i = d.job_filter.findText("Unit 4")
    d.job_filter.setCurrentIndex(i)
    assert d.table.rowCount() == 1
    assert "LATE" in d.table.item(0, 6).text()
    d.job_filter.setCurrentIndex(0)
    assert d.table.rowCount() == 2
    d.close()
