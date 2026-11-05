"""Time-and-material tag window. open_window(parent) shows it.

Sign calls app.sign.signer.sign_pdf. Link change event calls Project
Center save_record. Neither of those modules is edited here.
"""
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLineEdit)

from .. import dmoney
from . import files, tmtag, uiutil


class TagWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("T&M Tag", parent)
        self.path = tmtag.default_path()
        top = QHBoxLayout()
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("Customer")
        self.site = QLineEdit()
        self.site.setPlaceholderText("Site")
        self.description = QLineEdit()
        self.description.setPlaceholderText("Description")
        for w in (self.customer, self.site, self.description):
            top.addWidget(w)
        self.root.addLayout(top)
        self.buttons(("New tag", self.new_clicked),)
        line = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(list(tmtag.KINDS))
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("Line")
        self.qty = QLineEdit("1")
        self.unit_name = QLineEdit("ea")
        self.cost = QLineEdit("0")
        self.price = QLineEdit("0")
        for w in (self.kind, self.desc, self.qty, self.unit_name, self.cost,
                  self.price):
            line.addWidget(w)
        self.root.addLayout(line)
        self.buttons(("Add line", self.line_clicked),
                     ("Print tag", self.print_clicked),
                     ("Sign tag", self.sign_clicked))
        self.table = uiutil.table(
            ["Number", "Customer", "Status", "Price", "Change event"])
        self.root.addWidget(self.table, 1)
        self.lines = uiutil.table(
            ["Kind", "Description", "Qty", "Price", "Cost"])
        self.root.addWidget(self.lines)
        self.table.itemSelectionChanged.connect(self._show_lines)
        self.finish()
        self.reload()

    def reload(self):
        self.store = tmtag.load(self.path)
        rows, ids = [], []
        for tag in self.store["tags"]:
            got = tmtag.totals(tag)
            rows.append([tag["number"], tag["customer"], tag["status"],
                         dmoney.fmt(got["price"]), tag.get("change_event_no")
                         or ""])
            ids.append(tag["id"])
        uiutil.fill(self.table, rows, ids)
        self._show_lines()

    def _id(self):
        tid = uiutil.selected_id(self.table)
        if not tid:
            self.msg.setText("Select a tag.")
        return tid

    def new_clicked(self):
        def go():
            return tmtag.add(self.store, self.customer.text(), self.site.text(),
                             self.description.text())
        if self.guard(go):
            tmtag.save(self.store, self.path)
            self.reload()

    def line_clicked(self):
        tid = self._id()
        if not tid:
            return
        def go():
            return tmtag.add_line(
                self.store, tid, self.kind.currentText(), self.desc.text(),
                self.qty.text() or "1", self.unit_name.text() or "ea",
                self.cost.text() or "0", self.price.text() or "0")
        if self.guard(go):
            tmtag.save(self.store, self.path)
            self.reload()

    def _show_lines(self):
        tid = uiutil.selected_id(self.table)
        tag = next((t for t in self.store["tags"] if t["id"] == tid), None)
        rows = []
        if tag:
            rows = [[ln["kind"], ln["desc"], ln["qty"], ln["price"], ln["cost"]]
                    for ln in tag["lines"]]
        uiutil.fill(self.lines, rows)

    def print_to(self, path):
        tid = self._id()
        if not tid:
            return None
        tag = tmtag.get(self.store, tid)
        out = self.guard(lambda: tmtag.build_pdf(tag, path))
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def print_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "T&M tag", files.path_for("TM tag.pdf"), "PDF (*.pdf)")
        if path:
            self.print_to(path)

    def sign_to(self, src, dest, signer_name="QuantiSheet User", key_path=None,
                cert_path=None):
        tid = self._id()
        if not tid:
            return None
        tag = tmtag.get(self.store, tid)
        def go():
            return tmtag.sign(tag, src, dest, signer_name=signer_name,
                              key_path=key_path, cert_path=cert_path)
        out = self.guard(go)
        if out:
            tmtag.save(self.store, self.path)
            self.reload()
            self.msg.setText(f"Signed {out}")
        return out

    def sign_clicked(self):
        tid = self._id()
        if not tid:
            return
        tag = tmtag.get(self.store, tid)
        src, _ = QFileDialog.getSaveFileName(
            self, "Unsigned tag", files.path_for(f"{tag['number']}.pdf"),
            "PDF (*.pdf)")
        if not src:
            return
        if not self.print_to(src):
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Signed tag", files.path_for(f"{tag['number']} signed.pdf"),
            "PDF (*.pdf)")
        if dest:
            self.sign_to(src, dest)

    def link_project(self, pm_store, reason="Other"):
        tid = self._id()
        if not tid:
            return None
        tag = tmtag.get(self.store, tid)
        rec = self.guard(lambda: tmtag.link_change_event(tag, pm_store, reason))
        if rec:
            tmtag.save(self.store, self.path)
            self.reload()
            self.msg.setText(f"Change event {rec.get('_no')}")
        return rec


def open_window(parent=None):
    return uiutil.show(TagWindow(parent))
