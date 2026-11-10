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
from . import backflow, files, testers, uiutil


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
        self.repairs = {}
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
                if phase == "repair":
                    # what was repaired or replaced on this part - not a
                    # pass / fail; fills the district form's Repairs box
                    # for it (Chief's estimator test, Nov 7)
                    note = QLineEdit()
                    note.setPlaceholderText("repaired / replaced")
                    note.setMaxLength(120)
                    note.setAccessibleName(f"{label}: repairs and materials")
                    self.repairs[pid] = note
                    lay.addWidget(note)
                    grid.addWidget(cell, r, c)
                    continue
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
        self.comments.setMinimumHeight(72)
        form.addRow("Repairs and materials", self.materials)
        self.so1_type, self.so2_type = QComboBox(), QComboBox()
        for box, lab in ((self.so1_type, "Shutoff valve 1 is a"),
                         (self.so2_type, "Shutoff valve 2 is a")):
            box.addItems(list(backflow.VALVE_TYPES))
            box.setAccessibleName(lab)
            form.addRow(lab, box)
        form.addRow("Tester", self.tester)
        self.gauge = QComboBox()
        self.gauge.setEditable(True)
        self.gauge.setAccessibleName("Gauge serial")
        form.addRow("Gauge (serial)", self.gauge)
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
        # 1.2 phase 4 (Nov 5): the district's own form as an overlay, the
        # tester / gauge checks and the submission record
        self.buttons(("Fill the District Form…", self.overlay_clicked),
                     ("Map the form…", self.map_clicked),
                     ("Testers && gauges…", self.testers_clicked),
                     ("Mark submitted", self.submitted_clicked))
        self.submit = QLabel(testers.submit_line({}))
        self.submit.setWordWrap(True)
        self.root.addWidget(self.submit)
        self.finish()
        self.reload()

    def reload(self):
        self.testers = testers.load()
        cur = self.gauge.currentText() if hasattr(self, "gauge") else ""
        self.gauge.clear()
        self.gauge.addItem("")
        for g in self.testers["gauges"]:
            self.gauge.addItem(g["serial"])
        self.gauge.setCurrentText(cur)
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
            "gauge_serial": self.gauge.currentText().strip(),
            "so1_type": self.so1_type.currentText(),
            "so2_type": self.so2_type.currentText(),
        })
        for (pid, phase, which), box in self.boxes.items():
            data[f"{pid}_{phase}_{which}"] = box.isChecked()
        for pid, edit in self.repairs.items():
            data[f"{pid}_repair_note"] = edit.text()
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

    def checks_ok(self, report, ask=None):
        """Tester certificate, gauge calibration and retest-after-repair
        warnings before anything prints. True to go ahead."""
        from PySide6.QtWidgets import QMessageBox
        warns = testers.check(report, self.testers)
        if not warns:
            return True
        text = "\n".join(("STOP: " if k == "stop" else "") + t
                          for k, t in warns)
        if ask is None:
            ask = lambda t: QMessageBox.warning(                # noqa: E731
                self, "Before printing", t + "\n\nPrint anyway?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes
        ok = ask(text)
        if not ok:
            self.msg.setText("Not printed: " + text)
        return ok

    def print_clicked(self, _checked=False, path=None, ask=None):
        if not self.checks_ok(self.report(), ask):
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Backflow report", files.path_for(
                    "Backflow report.pdf"), "PDF (*.pdf)")
        if path:
            return self.print_to(path)
        return None

    def overlay_clicked(self, _checked=False, path=None, ask=None):
        """The district's own form with this report laid on it."""
        from . import district_form
        rep = self.report()
        if not self.checks_ok(rep, ask):
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Filled district form", files.path_for(
                    f"Backflow test {rep.get('dev_serial') or ''}.pdf"),
                "PDF (*.pdf)")
        if not path:
            return None
        out = self.guard(lambda: district_form.fill(rep, path))
        if not out:
            return None
        notes = []
        if out["overflow"]:
            notes.append("too long for their box (on an extra page): " +
                         ", ".join(out["overflow"]))
        if out["scaled"]:
            notes.append("the form page isn't the size it was mapped on - "
                         "check the calibration print")
        self.msg.setText(f"Saved {out['file']}. " + testers.submit_line(rep)
                         + (" Note: " + "; ".join(notes) if notes else ""))
        return out

    def map_clicked(self, _checked=False):
        from . import district_form_ui
        self._map = district_form_ui.open_window(self)
        return self._map

    def testers_clicked(self, _checked=False):
        self._testers = TestersWindow(self)
        self._testers.finished.connect(lambda *_: self.reload())
        uiutil.show(self._testers)
        return self._testers

    def submitted_clicked(self, _checked=False, how="", when=None):
        """Record that the last saved report went to the district."""
        if not self.store["reports"]:
            self.msg.setText("Save the report first.")
            return None
        rep = self.store["reports"][-1]
        got = self.guard(lambda: testers.mark_submitted(rep, how, when))
        if got is None:
            return None
        backflow.save(self.store, self.path)
        self.msg.setText(f"{rep['number']} recorded as submitted by "
                         f"{got['how']} on {got['on']}.")
        return got


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


class TestersWindow(uiutil.Desk):
    """Tester certificates and gauge calibrations (QW3)."""

    def __init__(self, parent=None):
        super().__init__("Backflow Testers & Gauges", parent)
        self.store = testers.load()
        r1 = QHBoxLayout()
        self.t_name, self.t_cert, self.t_exp = (QLineEdit(), QLineEdit(),
                                                QLineEdit())
        for w, hint in ((self.t_name, "Tester name"),
                        (self.t_cert, "Certificate no."),
                        (self.t_exp, "Certificate expires YYYY-MM-DD")):
            w.setPlaceholderText(hint)
            r1.addWidget(w)
        self.root.addLayout(r1)
        self.buttons(("Save tester", self.tester_clicked))
        r2 = QHBoxLayout()
        self.g_serial, self.g_cal, self.g_make = (QLineEdit(), QLineEdit(),
                                                  QLineEdit())
        for w, hint in ((self.g_serial, "Gauge serial"),
                        (self.g_cal, "Last calibration YYYY-MM-DD"),
                        (self.g_make, "Make / model")):
            w.setPlaceholderText(hint)
            r2.addWidget(w)
        self.root.addLayout(r2)
        self.buttons(("Save gauge", self.gauge_clicked))
        self.table = uiutil.table(["Tester / gauge", "Number", "Date",
                                   "Detail"])
        self.table.setAccessibleName("Testers and gauges")
        self.root.addWidget(self.table, 1)
        note = QLabel(testers.rule_note() + " (Setting "
                      "service_gauge_calibration_months.)")
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.finish()
        self.fill()

    def fill(self):
        rows = [[t["name"], t["cert_no"], t["cert_expires"],
                 "certificate expires"] for t in self.store["testers"]]
        rows += [[g["serial"], g.get("make", ""), g["calibrated"],
                  "last calibration; " + g.get("accuracy", "")]
                 for g in self.store["gauges"]]
        uiutil.fill(self.table, rows)

    def tester_clicked(self):
        if self.guard(lambda: testers.set_tester(
                self.store, self.t_name.text(), self.t_cert.text(),
                self.t_exp.text())):
            testers.save(self.store)
            self.fill()
            self.msg.setText("Tester saved.")

    def gauge_clicked(self):
        if self.guard(lambda: testers.set_gauge(
                self.store, self.g_serial.text(), self.g_cal.text(),
                self.g_make.text())):
            testers.save(self.store)
            self.fill()
            self.msg.setText("Gauge saved.")


def open_window(parent=None):
    return uiutil.show(BackflowWindow(parent))
