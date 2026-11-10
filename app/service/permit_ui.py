"""Permit and inspections for one work order (1.2 phase 5, #10).

The office's phone and how it schedules are shown with the picked
jurisdiction; anything not confirmed says UNVERIFIED. Nothing is sent
anywhere: the office still calls or uses the portal.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDateEdit, QFileDialog,
                               QFormLayout, QLabel, QLineEdit)
from PySide6.QtCore import QDate

from . import permits, uiutil, workorder


class PermitDialog(uiutil.Desk):
    saved = Signal()

    def __init__(self, store, wo_id, parent=None):
        super().__init__("Permit and Inspections", parent)
        self.resize(720, 560)
        self.store, self.wo_id = store, wo_id
        wo = workorder.get(store, wo_id)
        p = wo.get("permit") or {}
        form = QFormLayout()
        self.job = QComboBox()
        self.job.setAccessibleName("Kind of job")
        self.job.addItem("", "")
        for k, v in permits.TYPES.items():
            self.job.addItem(v + (" (permit)" if permits.needs_permit(k)
                                  else ""), k)
        self.office = QComboBox()
        self.office.setAccessibleName("Permit office")
        self.office.addItem("", "")
        for k, v in permits.OFFICES.items():
            self.office.addItem(v["name"], k)
        self.number = QLineEdit(p.get("number", ""))
        self.number.setAccessibleName("Permit number")
        self.other = QLineEdit(p.get("other_office", ""))
        self.other.setAccessibleName("Other office details")
        self.pdf = QLineEdit(p.get("pdf", ""))
        self.pdf.setAccessibleName("Permit PDF")
        self.info = QLabel("")
        self.info.setWordWrap(True)
        form.addRow("Kind of job", self.job)
        form.addRow("Permit office", self.office)
        form.addRow("", self.info)
        form.addRow("Permit number", self.number)
        form.addRow("Other office", self.other)
        form.addRow("Permit PDF", self.pdf)
        self.root.addLayout(form)
        self.buttons(("Attach permit PDF…", self.pdf_clicked),
                     ("Save permit", self.save_clicked))
        ins = QFormLayout()
        self.kind = QComboBox()
        self.kind.setAccessibleName("Inspection")
        for k in permits.INSPECTIONS:
            self.kind.addItem(k.title(), k)
        self.result = QComboBox()
        self.result.setAccessibleName("Result")
        for r in permits.RESULTS[1:]:
            self.result.addItem(r.title(), r)
        self.when = QDateEdit(QDate.currentDate())
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("yyyy-MM-dd")
        self.when.setAccessibleName("Inspection date")
        self.ins_notes = QLineEdit()
        self.ins_notes.setAccessibleName("Inspection notes")
        ins.addRow("Inspection", self.kind)
        ins.addRow("Date", self.when)
        ins.addRow("Result", self.result)
        ins.addRow("Notes", self.ins_notes)
        self.root.addLayout(ins)
        self.buttons(("Add inspection", self.inspection_clicked),)
        self.table = uiutil.table(["Inspection", "Date", "Result", "Notes"])
        self.table.setAccessibleName("Inspections")
        self.root.addWidget(self.table, 1)
        self.finish()
        self.job.currentIndexChanged.connect(self._show_office)
        self.office.currentIndexChanged.connect(self._show_office)
        self._pick(self.job, p.get("job_type", ""))
        self._pick(self.office, p.get("jurisdiction") or
                   permits.remembered(store, wo))
        self.refresh()

    @staticmethod
    def _pick(combo, data):
        i = combo.findData(data)
        combo.setCurrentIndex(max(i, 0))

    def _show_office(self):
        o = permits.OFFICES.get(self.office.currentData())
        job = self.job.currentData()
        need = ("This kind of job needs a permit (Settings decide which). "
                if job and permits.needs_permit(job) else
                "No permit by the settings for this kind of job. "
                if job else "")
        if not o:
            self.info.setText(need + "Pick the office by whether the site "
                              "is inside city limits, not by the mailing "
                              "address.")
            return
        parts = [need + o["how"]]
        if o["phone"]:
            parts.append("Phone " + o["phone"])
        if o["portal"]:
            parts.append("Portal " + o["portal"])
        if o["unverified"]:
            parts.append(o["unverified"])
        self.info.setText("  ".join(parts))

    def refresh(self):
        wo = workorder.get(self.store, self.wo_id)
        p = wo.get("permit") or {}
        uiutil.fill(self.table, [[i["kind"].title(), i["date"],
                                  i["result"].title(), i["notes"]]
                                 for i in p.get("inspections", [])])
        self._show_office()
        self.msg.setText(permits.summary(wo) + ("  " + permits.close_warning(
            wo) if permits.close_warning(wo) else ""))

    def pdf_clicked(self, _checked=False, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Permit PDF", "",
                                                  "PDF (*.pdf)")
        if path:
            self.pdf.setText(path)

    def save_clicked(self):
        got = self.guard(lambda: permits.set_permit(
            self.store, self.wo_id, job_type=self.job.currentData() or "",
            jurisdiction=self.office.currentData() or "",
            number=self.number.text(), other_office=self.other.text(),
            pdf=self.pdf.text().strip()))
        if got is None:
            return None
        self.saved.emit()
        self.refresh()
        return got

    def inspection_clicked(self):
        got = self.guard(lambda: permits.add_inspection(
            self.store, self.wo_id, self.kind.currentData(),
            self.when.date().toString("yyyy-MM-dd"),
            self.result.currentData(), self.ins_notes.text()))
        if got is None:
            return None
        self.saved.emit()
        self.ins_notes.clear()
        self.refresh()
        return got
