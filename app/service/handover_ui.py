"""Build-to-service handover window. open_window(parent) shows it.

Approved submittal text (pasted, or read from a project) and O&M PDFs
become service-record equipment. The agreement is offered and saved only
when Accept agreement is used.
"""
import os

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit)

from ..estimating import service as records_api
from . import agreements, handover, uiutil


class HandoverWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Build-to-Service Handover", parent)
        self.records_path = records_api.default_path()
        self.agree_path = agreements.default_path()
        row = QHBoxLayout()
        self.site = QComboBox()
        self.start = QLineEdit()
        self.start.setPlaceholderText("Warranty start YYYY-MM-DD")
        self.price = QLineEdit()
        self.price.setPlaceholderText("Agreement price")
        self.visits = QLineEdit("2")
        row.addWidget(self.site, 1)
        row.addWidget(self.start)
        row.addWidget(self.price)
        row.addWidget(self.visits)
        self.root.addLayout(row)
        self.root.addWidget(QLabel(
            "Paste equipment from the closeout set. One block per unit: "
            "Make, Model, Serial, Warranty."))
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText(
            "Rooftop unit\nMake: \nModel: \nSerial: \nWarranty: 12 months")
        self.root.addWidget(self.body, 1)
        self.root.addWidget(QLabel("O&M PDF paths, one per line"))
        self.docs = QPlainTextEdit()
        self.docs.setFixedHeight(50)
        self.root.addWidget(self.docs)
        self.buttons(("Read equipment", self.read_clicked),
                     ("Add to service records", self.import_clicked),
                     ("Accept PM agreement", self.accept_clicked))
        self.table = uiutil.table(
            ["Kind", "Make", "Model", "Serial", "Warranty months"])
        self.root.addWidget(self.table, 1)
        self.offer_lbl = QLabel("")
        self.offer_lbl.setWordWrap(True)
        self.root.addWidget(self.offer_lbl)
        self.finish()
        self.offer = None
        self.reload()

    def reload(self):
        self.records = records_api.load(self.records_path)
        self.agree = agreements.load(self.agree_path)
        current = self.site.currentData()
        self.site.clear()
        for p in self.records["properties"]:
            self.site.addItem(p["name"], p["id"])
        if current:
            idx = self.site.findData(current)
            if idx >= 0:
                self.site.setCurrentIndex(idx)

    def _submittals_from_text(self):
        text = self.body.toPlainText().strip()
        if not text:
            return []
        return [{"title": "Closeout notes", "status": "Approved",
                 "type": "O&M Manuals", "description": text}]

    def _documents(self):
        return [ln.strip() for ln in self.docs.toPlainText().splitlines()
                if ln.strip()]

    def read_clicked(self):
        found = []
        for rec in self._submittals_from_text():
            found.extend(handover.parse_text(rec["description"]))
        for path in self._documents():
            if os.path.isfile(path):
                try:
                    found.extend(handover.parse_text(handover.text_of_pdf(path)))
                except Exception as e:                    # noqa: BLE001
                    self.msg.setText(str(e))
        uiutil.fill(self.table, [[e.get("kind"), e.get("make"), e.get("model"),
                                  e.get("serial"), e.get("warranty_months")]
                                 for e in found])
        self.msg.setText(f"{len(found)} unit(s) read. Nothing saved yet.")

    def import_clicked(self):
        def go():
            return handover.import_closeout(
                self.records, self.site.currentData() or "",
                self.start.text(), submittals=self._submittals_from_text(),
                documents=self._documents())
        result = self.guard(go)
        if not result:
            return
        records_api.save(self.records, self.records_path)
        from . import warranty                 # 1.2 #9: registration clock
        wst = warranty.load()
        n_reg = len(warranty.sync_from_records(
            wst, self.records, ids=set(result["equipment_ids"])))
        if n_reg:
            warranty.save(wst)
        self.offer = result["offer"]
        self.reload()
        uiutil.fill(self.table, [[e.get("kind"), e.get("make"), e.get("model"),
                                  e.get("serial"), e.get("warranty_months")]
                                 for e in result["created"]])
        if self.offer:
            self.offer_lbl.setText(
                f"PM agreement offered for {self.offer['customer']} at "
                f"{self.offer['site']}: {self.offer['visits_per_year']} "
                f"visits, renews {self.offer['renewal']}. "
                "Enter a price and accept it. It is not saved yet.")
        else:
            self.offer_lbl.setText("No equipment with a model or serial was found.")
        self.msg.setText(f"{len(result['created'])} unit(s) added to the "
                         "service records." + (
                             f" {n_reg} warranty registration(s) now "
                             "counting down (Service > Warranty)."
                             if n_reg else ""))
        return result

    def accept_clicked(self):
        def go():
            return handover.accept_offer(
                self.offer, self.agree, self.price.text(),
                visits_per_year=self.visits.text() or None,
                records=self.records)
        aid = self.guard(go)
        if not aid:
            return
        agreements.save(self.agree, self.agree_path)
        self.msg.setText("PM agreement saved.")
        self.offer_lbl.setText("Agreement saved.")


def open_window(parent=None):
    return uiutil.show(HandoverWindow(parent))
