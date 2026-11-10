"""Refrigerant log window. open_window(parent) shows it.

1.2 (Nov 5): refrigerant class / GWP / residential AC on each unit, the
rule that applies, repair clocks and what's due, the owner's service
record, recovery and cylinders, and the editable rules."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox)

from ..estimating import service as records_api
from . import files, refrigerant, refrigerant_rules, uiutil


class RefrigerantWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Refrigerant Log", parent)
        self.path = refrigerant.default_path()
        self.note = QLabel(refrigerant.rule_note())      # compliance records
        self.note.setWordWrap(True)
        self.root.addWidget(self.note)
        row = QHBoxLayout()
        self.unit = QComboBox()
        self.unit.setAccessibleName("Unit")
        self.gas = QLineEdit()
        self.gas.setPlaceholderText("Refrigerant")
        self.charge = QLineEdit()
        self.charge.setPlaceholderText("Full charge, lb")
        self.category = QComboBox()
        self.category.setAccessibleName("Use")
        for key, label in refrigerant.CATEGORY_LABELS.items():
            self.category.addItem(label, key)
        self.charge_date = QLineEdit()
        self.charge_date.setPlaceholderText("Charge date")
        self.location = QLineEdit()
        self.location.setPlaceholderText("Location (roof, mech room...)")
        for w in (self.unit, self.gas, self.charge, self.category,
                  self.charge_date, self.location):
            row.addWidget(w)
        self.root.addLayout(row)
        row2 = QHBoxLayout()
        self.ref_class = QComboBox()
        self.ref_class.setAccessibleName("Refrigerant class")
        for key in ("unknown", "hfc", "ods", "other"):
            self.ref_class.addItem(refrigerant_rules.CLASSES[key], key)
        self.gwp = QCheckBox("GWP above 53")
        self.residential = QCheckBox("Residential / light-commercial AC or "
                                     "heat pump")
        for w in (QLabel("Class"), self.ref_class, self.gwp,
                  self.residential):
            row2.addWidget(w)
        row2.addStretch(1)
        self.root.addLayout(row2)
        self.buttons(("Add unit", self.add_unit_clicked),
                     ("Confirm class of selected unit…", self.confirm_clicked),
                     ("Rules…", self.rules_clicked))
        visit = QHBoxLayout()
        self.added = QLineEdit("0")
        self.recovered = QLineEdit("0")
        self.cylinder = QLineEdit()
        self.cylinder.setPlaceholderText("Cylinder #")
        self.cert = QLineEdit()
        self.cert.setPlaceholderText("608 cert #")
        self.tech_type = QComboBox()
        self.tech_type.setAccessibleName("608 type")
        for t in refrigerant.TECH_TYPES:
            self.tech_type.addItem(t or "608 type", t)
        self.tech = QLineEdit()
        self.tech.setPlaceholderText("Technician")
        self.when = QLineEdit()
        self.when.setPlaceholderText("Visit date")
        for w, lab in ((self.added, "Added lb"), (self.recovered, "Recovered"),
                       (self.cylinder, ""), (self.cert, ""),
                       (self.tech_type, ""), (self.tech, ""),
                       (self.when, "")):
            if lab:
                visit.addWidget(QLabel(lab))
            visit.addWidget(w)
        self.root.addLayout(visit)
        visit2 = QHBoxLayout()
        self.parts = QLineEdit()
        self.parts.setPlaceholderText("Parts used")
        self.work_done = QLineEdit()
        self.work_done.setPlaceholderText("Work done")
        visit2.addWidget(self.parts)
        visit2.addWidget(self.work_done, 2)
        self.root.addLayout(visit2)
        self.buttons(("Add visit", self.add_visit_clicked),
                     ("Print site log", self.print_clicked),
                     ("Owner record for last visit", self.owner_clicked),
                     ("Recovery && cylinders…", self.recovery_clicked),
                     ("Repair clock…", self.clock_clicked),
                     ("Year-end list…", self.year_clicked))
        self.table = uiutil.table(
            ["Unit", "Refrigerant", "Full charge", "Leak rate", "Limit",
             "Flag", "Rule", "Class"])
        self.table.setAccessibleName("Logged units")
        self.root.addWidget(self.table, 1)
        self.due_label = QLabel("")
        self.due_label.setWordWrap(True)
        self.root.addWidget(self.due_label)
        self.finish()
        self.reload()

    def reload(self):
        self.store = refrigerant.load(self.path)
        self.records = records_api.load()
        self.note.setText(refrigerant.rule_note())
        current = self.unit.currentData()
        self.unit.clear()
        for eq in self.records["equipment"]:
            label = " ".join(p for p in (eq.get("kind"), eq.get("model"),
                                         eq.get("serial")) if p)
            self.unit.addItem(label, eq["id"])
        if current:
            idx = self.unit.findData(current)
            if idx >= 0:
                self.unit.setCurrentIndex(idx)
        rows, ids = [], []
        for u in self.store["units"]:
            info = refrigerant.leak_rate(self.store, u["id"])
            cls = refrigerant_rules.CLASSES.get(u.get("ref_class"), "")
            if u.get("needs_review"):
                cls = "Needs review - suggested: " + \
                    refrigerant_rules.CLASSES.get(
                        u.get("suggested", {}).get("ref_class"), "?")
            rows.append([u["unit"], u["refrigerant"], u["full_charge"],
                         f"{info['rate']}%", f"{info['threshold']}%",
                         refrigerant.flag_text(info), info["why"], cls])
            ids.append(u["id"])
        uiutil.fill(self.table, rows, ids)
        due = refrigerant.due(self.store)
        self.due_label.setText(
            "Due: " + "; ".join(
                f"{u}: {what}" + (" (LATE)" if late else "")
                for _d, u, what, late in due) if due else
            "Nothing due.")

    def _logged_id(self):
        eq = self.unit.currentData()
        for u in self.store["units"]:
            if u["equipment_id"] == eq:
                return u["id"]
        self.msg.setText("Add this unit to the log first.")
        return None

    def _selected_unit(self):
        r = self.table.currentRow()
        if r < 0 and self.table.rowCount():
            r = 0
        it = self.table.item(r, 0) if r >= 0 else None
        from PySide6.QtCore import Qt
        return it.data(Qt.UserRole) if it is not None else None

    def add_unit_clicked(self):
        def go():
            return refrigerant.add_unit(
                self.store, self.records, self.unit.currentData(),
                self.gas.text(), self.charge.text(),
                self.category.currentData(), self.charge_date.text(),
                ref_class=self.ref_class.currentData(),
                gwp_over_53=(self.gwp.isChecked()
                             if self.ref_class.currentData() == "hfc"
                             else None),
                residential_ac=self.residential.isChecked(),
                location=self.location.text())
        if self.guard(go):
            refrigerant.save(self.store, self.path)
            self.reload()
            self.msg.setText("Unit added to the log.")

    def confirm_clicked(self, _checked=False, ask=None):
        """Confirm the suggested class (or the one picked above) for the
        selected unit - one click, logged (Nov 5)."""
        uid = self._selected_unit()
        if not uid:
            self.msg.setText("Pick a unit in the list.")
            return None
        u = refrigerant._unit(self.store, uid)
        sug = u.get("suggested") or {}
        picked = self.ref_class.currentData()
        cls = picked if picked != "unknown" else sug.get("ref_class")
        if cls in (None, "unknown"):
            self.msg.setText("No suggestion for this refrigerant - pick its "
                             "class above, then confirm.")
            return None
        gwp = self.gwp.isChecked() if picked == "hfc" else \
            sug.get("gwp_over_53")
        if cls == "hfc" and gwp is None:
            gwp = self.gwp.isChecked()
        text = (f"{u['unit']} ({u['refrigerant']}): set the class to "
                f"{refrigerant_rules.CLASSES[cls]}"
                + (f", GWP above 53: {'yes' if gwp else 'no'}"
                   if cls == "hfc" else "") +
                (f", residential AC: "
                 f"{'yes' if self.residential.isChecked() else 'no'}") + "?")
        if ask is None:
            ask = lambda t: QMessageBox.question(               # noqa: E731
                self, "Confirm refrigerant class", t) == QMessageBox.Yes
        if not ask(text):
            return None
        res = self.guard(lambda: refrigerant.confirm_class(
            self.store, uid, cls, gwp_over_53=gwp,
            residential_ac=self.residential.isChecked(),
            why=sug.get("why", "confirmed in the log window")))
        if res is not None:
            refrigerant.save(self.store, self.path)
            self.reload()
            self.msg.setText("Class confirmed. " + res["why"])
        return res

    def add_visit_clicked(self):
        uid = self._logged_id()
        if not uid:
            return
        def go():
            return refrigerant.add_visit(
                self.store, uid, self.when.text(), self.added.text() or "0",
                self.recovered.text() or "0", self.cylinder.text(),
                self.cert.text(), self.tech.text(),
                tech_type=self.tech_type.currentData() or "",
                parts=self.parts.text(), work_done=self.work_done.text())
        if self.guard(go):
            refrigerant.save(self.store, self.path)
            self.reload()
            c = refrigerant.open_clock(self.store, uid)
            self.msg.setText("Visit recorded." + (
                f" Repair clock running: repair by {c['repair_by']}."
                if c else ""))

    def print_to(self, path, property_id):
        out = self.guard(lambda: refrigerant.site_log_pdf(
            self.store, self.records, property_id, path))
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def print_clicked(self):
        eq_id = self.unit.currentData()
        eq = records_api.find(self.records, eq_id) if eq_id else None
        if not eq:
            self.msg.setText("Pick a unit.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Refrigerant log", files.path_for("Refrigerant log.pdf"),
            "PDF (*.pdf)")
        if path:
            self.print_to(path, eq.get("property"))

    def owner_clicked(self, _checked=False, path=None):
        uid = self._logged_id()
        if not uid:
            return None
        visits = sorted((v for v in self.store["visits"]
                         if v["unit_id"] == uid), key=lambda v: v["date"])
        if not visits:
            self.msg.setText("No visit on this unit yet.")
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Refrigerant service record",
                files.path_for(f"Refrigerant record {visits[-1]['date']}.pdf"),
                "PDF (*.pdf)")
        if not path:
            return None
        out = self.guard(lambda: refrigerant.owner_record_pdf(
            self.store, self.records, visits[-1]["id"], path))
        if out:
            self.msg.setText(f"Saved {out} - give it to the owner.")
        return out

    def clock_clicked(self, _checked=False):
        uid = self._selected_unit()
        c = refrigerant.open_clock(self.store, uid) if uid else None
        if c is None:
            last = [k for k in self.store.get("clocks", [])
                    if k["unit_id"] == uid]
            c = last[-1] if last else None
        if c is None:
            self.msg.setText("No repair clock on the selected unit.")
            return None
        self._clock = ClockDialog(self, c["id"])
        self._clock.finished.connect(lambda *_: self.reload())
        self._clock.show()
        return self._clock

    def year_clicked(self, _checked=False, path=None, year=None):
        import datetime as dt
        year = year or dt.date.today().year
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Year-end list",
                files.path_for(f"Refrigerant year-end {year}.pdf"),
                "PDF (*.pdf)")
        if not path:
            return None
        out = self.guard(lambda: refrigerant.year_report_pdf(
            self.store, year, path))
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def rules_clicked(self, _checked=False):
        self._rules = RulesDialog(self)
        self._rules.accepted.connect(self.reload)
        self._rules.show()
        return self._rules

    def recovery_clicked(self, _checked=False):
        from . import recovery_ui
        self._recovery = recovery_ui.open_window(self)
        return self._recovery


class ClockDialog(QDialog):
    """One repair clock: repair and initial test, follow-up test,
    industrial shutdown window, extension, retrofit / retire plan."""

    def __init__(self, win, clock_id):
        super().__init__(win)
        self.win, self.clock_id = win, clock_id
        self.setWindowTitle("Repair Clock")
        form = QFormLayout(self)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        form.addRow(self.head)
        self.repaired = QLineEdit()
        self.initial = QLineEdit()
        self.passed = QCheckBox("Initial test passed")
        self.passed.setChecked(True)
        self.followup = QLineEdit()
        self.f_passed = QCheckBox("Follow-up test passed")
        self.f_passed.setChecked(True)
        self.ext_until = QLineEdit()
        self.ext_why = QLineEdit()
        self.plan = QLineEdit()
        self.retire = QCheckBox("Retire the unit (not retrofit)")
        for lab, w in (("Repaired on", self.repaired),
                       ("Initial test on", self.initial),
                       ("", self.passed),
                       ("Follow-up test on", self.followup),
                       ("", self.f_passed),
                       ("Extend repair to", self.ext_until),
                       ("Why more time", self.ext_why),
                       ("Retrofit / retire plan", self.plan),
                       ("", self.retire)):
            if lab:
                w.setAccessibleName(lab)
                form.addRow(lab, w)
            else:
                form.addRow(w)
        from PySide6.QtWidgets import QPushButton
        for text, fn in (("Record repair and initial test", self.repair),
                         ("Record follow-up test", self.follow),
                         ("Industrial: must shut down to repair",
                          self.shutdown),
                         ("Record extension", self.extend),
                         ("Record retrofit / retire plan", self.retrofit)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            form.addRow(b)
        self.err = QLabel("")
        self.err.setWordWrap(True)
        form.addRow(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.show_clock()

    def clock(self):
        return refrigerant._clock(self.win.store, self.clock_id)

    def show_clock(self):
        c = self.clock()
        u = refrigerant._unit(self.win.store, c["unit_id"])
        by = (c.get("extension") or {}).get("until") or c["repair_by"]
        self.head.setText(
            f"{u['unit']}: {c['rule']} clock opened {c['opened']} "
            f"(leak rate {c['rate']}%). Repair by {by}. "
            f"Status: {c['status']}."
            + (f" Follow-up test due {c['followup_due']}."
               if c.get("followup_due") and not c.get("followup_test")
               else ""))

    def _do(self, fn):
        try:
            fn()
        except ValueError as e:
            self.err.setText(str(e))
            return False
        refrigerant.save(self.win.store, self.win.path)
        self.err.setText("Saved.")
        self.show_clock()
        return True

    def repair(self):
        return self._do(lambda: refrigerant.record_repair(
            self.win.store, self.clock_id, self.repaired.text(),
            self.initial.text(), self.passed.isChecked()))

    def follow(self):
        return self._do(lambda: refrigerant.record_followup(
            self.win.store, self.clock_id, self.followup.text(),
            self.f_passed.isChecked()))

    def shutdown(self):
        return self._do(lambda: refrigerant.set_shutdown(
            self.win.store, self.clock_id, True))

    def extend(self):
        return self._do(lambda: refrigerant.request_extension(
            self.win.store, self.clock_id, self.ext_until.text(),
            self.ext_why.text()))

    def retrofit(self):
        return self._do(lambda: refrigerant.retrofit_plan(
            self.win.store, self.clock_id, self.plan.text(),
            self.retire.isChecked()))


class RulesDialog(QDialog):
    """Every number the refrigerant rules use, editable (Jon, Nov 4: keep
    thresholds in data, not code). The licensed tech's review is noted
    here; until then the log says NOT YET REVIEWED."""

    NUMBERS = (("84.106 applies at (lb)", ("rules", "84.106", "min_lbs")),
               ("84.106 GWP above", ("rules", "84.106", "gwp_over")),
               ("82.157 applies at (lb)", ("rules", "82.157", "min_lbs")),
               ("Industrial process limit (%)",
                ("limits", "industrial_process")),
               ("Commercial refrigeration limit (%)",
                ("limits", "commercial_refrigeration")),
               ("Comfort cooling limit (%)", ("limits", "comfort_cooling")),
               ("Other appliances limit (%)", ("limits", "other")),
               ("Repair within (days)", ("repair_days",)),
               ("Industrial shutdown repair (days)",
                ("repair_days_industrial_shutdown",)),
               ("Follow-up test within (days)", ("followup_test_days",)),
               ("Chronic leaker (% of charge a year)",
                ("chronic_leak_pct",)),
               ("Automatic leak detection from (lb)",
                ("auto_leak_detection_lbs",)),
               ("Keep records (years)", ("records_years",)),
               ("Disposal records from (lb)", ("disposal_min_lbs",)),
               ("Disposal records up to (lb)", ("disposal_max_lbs",)),
               ("Disposable cylinder statement from",
                ("disposable_cylinder_from",)),
               ("Disposable cylinder vacuum (in-Hg)",
                ("disposable_cylinder_vacuum_inhg",)))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Refrigerant Rules")
        self.rules = refrigerant_rules.load()
        form = QFormLayout(self)
        form.addRow(QLabel(refrigerant_rules.DECISION))
        self.fields = {}
        for label, key in self.NUMBERS:
            e = QLineEdit(str(self._get(key)))
            e.setAccessibleName(label)
            self.fields[key] = e
            form.addRow(label, e)
        self.reviewed = QCheckBox("Reviewed by the licensed tech")
        self.reviewed.setChecked(bool(self.rules.get("reviewed")))
        self.reviewer = QLineEdit(self.rules.get("reviewer", ""))
        self.reviewer.setAccessibleName("Reviewer")
        self.review_date = QLineEdit(self.rules.get("review_date", ""))
        self.review_date.setAccessibleName("Review date")
        form.addRow(self.reviewed)
        form.addRow("Reviewer", self.reviewer)
        form.addRow("Review date", self.review_date)
        self.err = QLabel("")
        form.addRow(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Save |
                              QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _get(self, key):
        v = self.rules
        for k in key:
            v = v[k]
        return v

    def _set(self, key, value):
        v = self.rules
        for k in key[:-1]:
            v = v[k]
        old = v[key[-1]]
        if isinstance(old, int) and not isinstance(old, bool):
            value = int(value)
        elif key[-1].endswith("_from"):
            files.iso_date(value, "Date", blank_ok=False)
        else:
            from decimal import Decimal, InvalidOperation
            try:
                Decimal(str(value))
            except InvalidOperation:
                raise ValueError from None
            if isinstance(old, int):
                value = int(value)
        v[key[-1]] = value

    def save(self):
        for label, key in self.NUMBERS:
            try:
                self._set(key, self.fields[key].text().strip())
            except (ValueError, files.FileError):
                self.err.setText(f"{label}: that isn't a number (or date).")
                return None
        self.rules["reviewed"] = self.reviewed.isChecked()
        self.rules["reviewer"] = self.reviewer.text().strip()
        self.rules["review_date"] = self.review_date.text().strip()
        if self.rules["reviewed"] and not (self.rules["reviewer"] and
                                           self.rules["review_date"]):
            self.err.setText("Name the reviewer and the review date.")
            return None
        out = refrigerant_rules.save(self.rules)
        self.accept()
        return out


def open_window(parent=None):
    return uiutil.show(RefrigerantWindow(parent))
