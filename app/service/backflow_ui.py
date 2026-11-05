"""Backflow test report window. open_window(parent) shows it.

The PDF fields match the report. Fill from the service record copies the
account, the device and the company phone, and sets the next test one
year out.
"""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QScrollArea, QWidget)

from .. import proposal
from ..estimating import service as records_api
from . import backflow, files, uiutil


class BackflowWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Backflow Test Report", parent)
        self.path = backflow.default_path()
        self.records = records_api.load()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        form = QFormLayout(host)
        self.site = QComboBox()
        self.device = QComboBox()
        self.site.currentIndexChanged.connect(self._fill_devices)
        self.acct = QLineEdit()
        self.address = QLineEdit()
        self.acct_no = QLineEdit()
        self.meter = QLineEdit()
        self.dev_name = QLineEdit()
        self.model = QLineEdit()
        self.serial = QLineEdit()
        self.size = QLineEdit()
        self.application = QComboBox()
        self.application.addItems(list(backflow.APPLICATIONS))
        self.location = QLineEdit()
        self.test_date = QLineEdit()
        self.test_date.setPlaceholderText("YYYY-MM-DD")
        self.next_due = QLabel("")
        form.addRow("Site", self.site)
        form.addRow("Device on the record", self.device)
        form.addRow("Account name", self.acct)
        form.addRow("Address", self.address)
        form.addRow("Account no.", self.acct_no)
        form.addRow("Meter no.", self.meter)
        form.addRow("Device", self.dev_name)
        form.addRow("Model", self.model)
        form.addRow("Serial", self.serial)
        form.addRow("Size", self.size)
        form.addRow("Application", self.application)
        form.addRow("Location", self.location)
        form.addRow("Test date", self.test_date)
        form.addRow("Next test due", self.next_due)
        self.boxes = {}
        self.psis = {}
        grid = QGridLayout()
        grid.addWidget(QLabel(""), 0, 0)
        for c, (_phase, label) in enumerate(backflow.PHASES, start=1):
            grid.addWidget(QLabel(label), 0, c)
        for r, (pid, label, kind) in enumerate(backflow.POINTS, start=1):
            grid.addWidget(QLabel(label), r, 0)
            for c, (phase, _plab) in enumerate(backflow.PHASES, start=1):
                cell = QWidget()
                lay = QHBoxLayout(cell)
                lay.setContentsMargins(0, 0, 0, 0)
                if kind != "psi":
                    leaked = QCheckBox("Leaked")
                    tight = QCheckBox("Closed tight")
                    self.boxes[(pid, phase, "leaked")] = leaked
                    self.boxes[(pid, phase, "tight")] = tight
                    lay.addWidget(leaked)
                    lay.addWidget(tight)
                if kind != "valve":
                    psi = QLineEdit()
                    psi.setPlaceholderText("psi")
                    psi.setFixedWidth(56)
                    self.psis[(pid, phase)] = psi
                    lay.addWidget(psi)
                grid.addWidget(cell, r, c)
        form.addRow(grid)
        self.materials = QPlainTextEdit()
        self.materials.setFixedHeight(48)
        self.tester = QLineEdit()
        self.cert_no = QLineEdit()
        self.company = QLineEdit()
        self.phone = QLineEdit()
        self.category = QComboBox()
        self.category.addItems(list(backflow.CATEGORIES))
        self.method = QComboBox()
        self.method.addItems(list(backflow.METHODS))
        self.kit = QComboBox()
        self.kit.addItems(list(backflow.KITS))
        self.signature = QLineEdit()
        self.comments = QPlainTextEdit()
        self.comments.setFixedHeight(48)
        form.addRow("Repairs and materials", self.materials)
        form.addRow("Tester", self.tester)
        form.addRow("Certification no.", self.cert_no)
        form.addRow("Company", self.company)
        form.addRow("Phone", self.phone)
        form.addRow("Category", self.category)
        form.addRow("Method", self.method)
        form.addRow("Test kit", self.kit)
        form.addRow("Signature", self.signature)
        form.addRow("Comments", self.comments)
        scroll.setWidget(host)
        self.root.addWidget(scroll, 1)
        self.buttons(("Fill from service record", self.fill_clicked),
                     ("Save report", self.save_clicked),
                     ("Print PDF", self.print_clicked),
                     ("Data for District Form…", self.district_clicked))
        self.finish()
        self.reload()

    def reload(self):
        self.store = backflow.load(self.path)
        self.records = records_api.load()
        self.site.blockSignals(True)
        self.site.clear()
        self.site.addItem("", "")
        for p in self.records["properties"]:
            self.site.addItem(p["name"], p["id"])
        self.site.blockSignals(False)
        self._fill_devices()

    def _fill_devices(self):
        pid = self.site.currentData() or ""
        self.device.clear()
        self.device.addItem("", "")
        for eq in self.records["equipment"]:
            if pid and eq.get("property") != pid:
                continue
            label = " ".join(p for p in (eq.get("kind"), eq.get("model"),
                                         eq.get("serial")) if p)
            self.device.addItem(label, eq["id"])

    def fill_clicked(self):
        def go():
            return backflow.from_service(
                self.records, self.site.currentData() or "",
                self.device.currentData() or "", comp=proposal.company(),
                test_date=self.test_date.text())
        report = self.guard(go)
        if not report:
            return
        self.acct.setText(report["acct_name"])
        self.address.setText(report["acct_address"])
        self.dev_name.setText(report["dev_name"])
        self.model.setText(report["dev_model"])
        self.serial.setText(report["dev_serial"])
        self.company.setText(report["cert_company"])
        self.phone.setText(report["cert_phone"])
        self.next_due.setText(report.get("next_due") or "")
        self.msg.setText("Filled from the service record.")

    def report(self):
        data = backflow.empty_report()
        data.update({
            "property_id": self.site.currentData() or "",
            "equipment_id": self.device.currentData() or "",
            "acct_name": self.acct.text(), "acct_address": self.address.text(),
            "acct_no": self.acct_no.text(), "meter_no": self.meter.text(),
            "dev_name": self.dev_name.text(), "dev_model": self.model.text(),
            "dev_serial": self.serial.text(), "dev_size": self.size.text(),
            "dev_application": self.application.currentText(),
            "dev_location": self.location.text(),
            "test_date": self.test_date.text(),
            "repair_materials": self.materials.toPlainText(),
            "tester": self.tester.text(), "cert_no": self.cert_no.text(),
            "cert_company": self.company.text(), "cert_phone": self.phone.text(),
            "category": self.category.currentText(),
            "method": self.method.currentText(), "kit": self.kit.currentText(),
            "signature": self.signature.text(),
            "comments": self.comments.toPlainText(),
        })
        for (pid, phase, which), box in self.boxes.items():
            data[f"{pid}_{phase}_{which}"] = box.isChecked()
        for (pid, phase), edit in self.psis.items():
            data[f"{pid}_{phase}_psi"] = edit.text()
        return data

    def save_clicked(self):
        def go():
            return backflow.add(self.store, self.report())
        rid = self.guard(go)
        if not rid:
            return
        backflow.save(self.store, self.path)
        report = backflow.get(self.store, rid)
        self.next_due.setText(report.get("next_due") or "")
        self.msg.setText(f"Saved {report['number']}. Next test {report['next_due']}.")
        return rid

    def print_to(self, path, report=None):
        out = self.guard(lambda: backflow.write_pdf(report or self.report(), path))
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def print_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Backflow report", files.path_for("Backflow report.pdf"),
            "PDF (*.pdf)")
        if path:
            self.print_to(path)


    def district_clicked(self, _checked=False, path=None):
        """Many districts accept only their own form: one page with every
        value, to copy onto it (review 2, Nov 4)."""
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Data for the district's form",
                files.path_for("Backflow data for district form.pdf"),
                "PDF (*.pdf)")
        if not path:
            return None
        out = self.guard(lambda: backflow.write_data_sheet(self.report(),
                                                           path))
        if out:
            self.msg.setText(f"Saved {out}")
        return out


def open_window(parent=None):
    return uiutil.show(BackflowWindow(parent))
