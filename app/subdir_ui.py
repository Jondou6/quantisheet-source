"""Company Directory window: search your subcontractor contacts, mark
favorites, keep certifications, insurance and prequalification, import from
Excel. The list stays on this computer (see app/subdir.py)."""
import html
import os
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import icons, subdir

COLS = [("favorite", "★"), ("company", "Company"), ("contact", "Contact"),
        ("division", "Div"), ("trade", "Trade"), ("phone", "Phone"),
        ("email", "Email"), ("city", "City"), ("state", "State"),
        ("certs", "Certs"), ("_prequal", "Prequal"),
        ("insurance_exp", "Insurance exp.")]
DIVISIONS = ["", "02", "03", "04", "05", "06", "07", "08", "09", "10",
             "11", "12", "13", "14", "21", "22", "23", "26", "27", "28",
             "31", "32", "33", "40", "43", "46"]
EDIT = [("company", "Company"), ("contact", "Contact"),
        ("division", "CSI division"), ("trade", "Trade"), ("type", "Type"),
        ("phone", "Phone"), ("email", "Email"), ("address", "Address"),
        ("city", "City"), ("state", "State"), ("zip", "ZIP"),
        ("certs", "Certifications"), ("license", "License no."),
        ("license_exp", "License expires"),
        ("insurance_exp", "Insurance expires"),
        ("bond_limit", "Bonding limit $"), ("rating", "Rating (1-5)"),
        ("prequal", "Prequalification"), ("prequal_limit",
                                          "Prequalified up to $"),
        ("prequal_exp", "Prequalified until")]


class ContactDialog(QDialog):
    """Add or edit one contact."""

    def __init__(self, parent=None, contact=None):
        super().__init__(parent)
        self.contact = dict(contact or {})
        self.setWindowTitle("Edit Contact" if contact else "New Contact")
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.w = {}
        for key, label in EDIT:
            if key == "prequal":
                w = QComboBox()
                w.addItems(subdir.PREQUAL)
                w.setCurrentText(self.contact.get(key) or "")
            elif key == "certs":
                w = QLineEdit(self.contact.get(key) or "")
                w.setPlaceholderText(", ".join(subdir.CERTS))
            else:
                w = QLineEdit(str(self.contact.get(key) or ""))
                if key.endswith("_exp"):
                    w.setPlaceholderText("YYYY-MM-DD")
            self.w[key] = w
            f.addRow(label, w)
        self.fav = QCheckBox("Favorite (listed first)")
        self.fav.setChecked(bool(self.contact.get("favorite")))
        f.addRow("", self.fav)
        self.notes = QPlainTextEdit(self.contact.get("notes") or "")
        self.notes.setFixedHeight(70)
        f.addRow("Notes", self.notes)
        v.addLayout(f)
        if self.contact.get("company"):
            st = subdir.stats(self.contact["company"])
            rate = f"{st['win_rate']:.0%}" if st["win_rate"] is not None \
                else "-"
            hist = QLabel(f"Bid history: {st['bids']} bid(s), {st['wins']} "
                          f"won ({rate})" + (f", last {st['last']}"
                                              if st["last"] else ""))
            hist.setObjectName("muted")
            v.addWidget(hist)
        pq = self.contact.get("prequal_data")
        if isinstance(pq, dict) and pq:
            from . import prequal
            pts, notes, _st, _lim = prequal.score(pq)
            lab = QLabel(f"Prequal answers received {pq.get('received', '')}"
                         f": score {pts}/100. " + " ".join(notes))
            lab.setWordWrap(True)
            v.addWidget(lab)
        bb = QDialogButtonBox(QDialogButtonBox.Save |
                              QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self):
        c = dict(self.contact)
        for k, w in self.w.items():
            c[k] = w.currentText() if isinstance(w, QComboBox) else \
                w.text().strip()
        c["favorite"] = "1" if self.fav.isChecked() else ""
        c["notes"] = self.notes.toPlainText().strip()
        return c

    def _ok(self):
        if not self.w["company"].text().strip():
            QMessageBox.warning(self, "Contact", "Enter the company name.")
            return
        self.accept()


class DirectoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("Search company, contact, trade, city…")
        self.text.setClearButtonEnabled(True)
        # filter 250 ms after the last keystroke, not per keystroke over a
        # 36,000-company list (review 3b C5)
        from PySide6.QtCore import QTimer
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(250)
        self._typing.timeout.connect(self.refresh)
        self.text.textChanged.connect(self._typed)
        row.addWidget(self.text, 1)
        row.addWidget(QLabel("Division:"))
        self.div = QComboBox()
        self.div.addItems(["All"] + DIVISIONS[1:])
        self.div.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.div)
        row.addWidget(QLabel("State:"))
        self.state = QComboBox()
        self.state.setEditable(True)
        self.state.addItems(["All", "NC", "SC", "GA", "VA", "TN", "FL"])
        self.state.currentTextChanged.connect(self.refresh)
        row.addWidget(self.state)
        row.addWidget(QLabel("Cert:"))
        self.cert = QComboBox()
        self.cert.addItems(["Any"] + subdir.CERTS)
        self.cert.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.cert)
        self.favs = QCheckBox("★ only")
        self.favs.toggled.connect(self.refresh)
        row.addWidget(self.favs)
        self.pq = QCheckBox("Prequalified only")
        self.pq.toggled.connect(self.refresh)
        row.addWidget(self.pq)
        v.addLayout(row)
        row = QHBoxLayout()
        for label, icon, fn, tip in (
                ("New", "new", self.add, "Add a company"),
                ("Edit", "edit", self.edit, "Edit the selected company"),
                ("★ Favorite", "star", self.favorite,
                 "Favorites are listed first and offered first for bids"),
                ("Delete", "delete", self.delete, ""),
                ("Send Prequal Form…", "mail", self.send_prequal,
                 "Email a fillable prequalification PDF"),
                ("Read Returned Prequal…", "import", self.read_prequal,
                 "Read a filled-in prequalification PDF and score it"),
                ("Import from Excel…", "import", self.import_file, ""),
                ("Unlock Company Contacts…", "lock", self.unlock_contacts,
                 "Add the company's contact list that came with this "
                 "build (needs the password)")):
            if fn == self.unlock_contacts:
                from . import sealed_contacts
                if not sealed_contacts.available():
                    continue
            b = QPushButton(label)
            try:
                b.setIcon(icons.icon(icon))
            except Exception:
                pass
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.alerts = QLabel()
        self.alerts.setWordWrap(True)
        v.addWidget(self.alerts)
        self.table = QTableWidget(0, len(COLS))
        self.table.setObjectName("pcList")
        self.table.setHorizontalHeaderLabels([c[1] for c in COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda _i: self.edit())
        v.addWidget(self.table, 1)
        self.note = QLabel()
        self.note.setObjectName("muted")
        v.addWidget(self.note)
        self.contacts = subdir.load()
        self.refresh()

    # ----------------------------------------------------------- list
    DEBOUNCE_OVER = 2000          # companies; smaller lists filter at once

    def _typed(self, *_):
        if len(getattr(self, "contacts", None) or ()) > self.DEBOUNCE_OVER:
            self._typing.start()
        else:
            self.refresh()

    def refresh(self, *_):
        self._typing.stop()
        div = self.div.currentText()
        st = self.state.currentText()
        cert = self.cert.currentText()
        rows = subdir.search(self.text.text(),
                             "" if div == "All" else div,
                             "" if st in ("All", "") else st,
                             contacts=self.contacts,
                             favorites=self.favs.isChecked(),
                             cert="" if cert == "Any" else cert,
                             prequalified=self.pq.isChecked())
        self.table.setSortingEnabled(False)
        self.table.setRowCount(min(len(rows), 3000))
        for i, c in enumerate(rows[:3000]):
            for j, (k, _l) in enumerate(COLS):
                if k == "favorite":
                    val = "★" if c.get("favorite") else ""
                elif k == "_prequal":
                    val = subdir.prequal_status(c)
                    if val == "Not prequalified":
                        val = ""
                else:
                    val = str(c.get(k) or "")
                it = QTableWidgetItem(val)
                it.setData(Qt.UserRole, c.get("id"))
                self.table.setItem(i, j, it)
        self.table.setSortingEnabled(True)
        al = subdir.alerts(self.contacts)
        if al:
            bits = [f"{html.escape(c.get('company') or '')}: {what} "
                    f"{'expired' if ex else 'expires'} {d}"
                    for c, what, d, ex in al[:6]]
            more = f" and {len(al) - 6} more" if len(al) > 6 else ""
            self.alerts.setText("<span style='color:#b45309'>⚠ " +
                                "; ".join(bits) + more + "</span>")
        else:
            self.alerts.setText("")
        self.note.setText(
            f"{len(rows)} of {len(self.contacts)} contacts. Kept only on this "
            f"computer ({subdir.path()}) - never in the program or an "
            "installer.")
        return rows

    def selected(self):
        r = self.table.currentRow()
        if r < 0 or self.table.item(r, 0) is None:
            return None
        return subdir.get(self.table.item(r, 0).data(Qt.UserRole),
                          self.contacts)

    def _reload(self):
        self.contacts = subdir.load()
        self.refresh()

    # ----------------------------------------------------------- edits
    def add(self, values=None):
        if values is None:
            dlg = ContactDialog(self)
            if not dlg.exec():
                return None
            values = dlg.values()
        c = subdir.upsert(values)
        self._reload()
        return c

    def edit(self, values=None):
        c = self.selected()
        if c is None:
            return None
        if values is None:
            dlg = ContactDialog(self, c)
            if not dlg.exec():
                return None
            values = dlg.values()
        out = subdir.upsert(dict(values, id=c["id"]))
        self._reload()
        return out

    def favorite(self):
        c = self.selected()
        if c is None:
            return None
        on = subdir.toggle_favorite(c["id"])
        self._reload()
        return on

    def delete(self, confirm=True):
        c = self.selected()
        if c is None:
            return 0
        if confirm and QMessageBox.question(
                self, "Company Directory",
                f"Delete {c.get('company')} "
                f"({c.get('contact') or c.get('email') or ''})?") \
                != QMessageBox.Yes:
            return 0
        n = subdir.remove(c["id"])
        self._reload()
        return n

    # ----------------------------------------------------------- prequal
    def send_prequal(self, gc=None):
        from . import mail, prequal, settings
        c = self.selected()
        if c is None:
            QMessageBox.information(self, "Prequalification",
                                    "Select a company first.")
            return None
        if not c.get("email"):
            QMessageBox.warning(self, "Prequalification",
                                f"{c.get('company')} has no email.")
            return None
        gc = gc if gc is not None else (settings.get("company_name") or "")
        safe = "".join(ch for ch in c.get("company", "") if ch.isalnum()
                       or ch in " -")[:40].strip() or "company"
        path = os.path.join(tempfile.gettempdir(),
                            f"Prequalification - {safe}.pdf")
        prequal.make_form(path, c.get("company", ""), gc)
        how = mail.send([c["email"]],
                        "Subcontractor prequalification" +
                        (f" - {gc}" if gc else ""),
                        f"{c.get('contact') or c.get('company')},\n\n"
                        "Please fill in the attached prequalification form, "
                        "save it and email it back to us. Thank you.",
                        attachments=[path])
        if how:
            c["prequal"] = c.get("prequal") if c.get("prequal") in (
                "Approved",) else "Sent"
            subdir.upsert(c)
            self._reload()
        return how

    def read_prequal(self, path=None, decide=None):
        """Read a returned form onto the selected company (or the one the
        form names). decide(score, notes, status, limit) -> (status,
        limit) or None; without it you're asked."""
        from . import prequal
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Returned Prequalification", "", "PDF (*.pdf)")
        if not path:
            return None
        try:
            ans = prequal.read_form(path)
        except Exception as e:
            QMessageBox.warning(self, "Prequalification", str(e))
            return None
        c = self.selected()
        name = (ans.get("legal_name") or "").strip().lower()
        if name and (c is None or name not in (c.get("company") or "")
                     .lower()):
            c = next((x for x in self.contacts if name and
                      (x.get("company") or "").lower() == name), c)
        if c is None:
            c = {"company": ans.get("legal_name") or "?"}
        pts, notes, status, limit = prequal.score(ans)
        if decide is not None:
            got = decide(pts, notes, status, limit)
        else:
            msg = (f"{c.get('company')}: score {pts}/100.\n\n" +
                   ("\n".join("• " + n for n in notes) or "No concerns.") +
                   f"\n\nSuggested: {status}" +
                   (f", up to ${limit:,.0f}" if limit else "") + ".")
            opts = ["Approve", "Keep pending", "Reject"]
            pick, ok = QInputDialog.getItem(self, "Prequalification", msg,
                                            opts, 0 if status == "Approved"
                                            else 1, False)
            got = None if not ok else (
                {"Approve": "Approved", "Keep pending": "Pending",
                 "Reject": "Rejected"}[pick], limit)
        if got is None:
            return None
        st, lim = got
        prequal.apply(c, ans, st, lim)
        out = subdir.upsert(c)
        self._reload()
        return out

    def unlock_contacts(self, password=None):
        """Add the password-protected contact list shipped with this
        build to this computer's directory."""
        from . import sealed_contacts
        if password is None:
            password = _ask_password(self)
            if password is None:
                return None
        try:
            added, updated, total = sealed_contacts.import_into_directory(
                password)
        except sealed_contacts.WrongPassword as e:
            QMessageBox.warning(self, "Company Contacts", str(e))
            return None
        except Exception as e:
            QMessageBox.warning(self, "Company Contacts",
                                f"Couldn't open the contact list: {e}")
            return None
        self.contacts = subdir.load()
        self.refresh()
        QMessageBox.information(self, "Company Contacts",
                                f"{added} contacts added, {updated} "
                                f"updated. {total} in the directory.")
        return added, updated, total

    def import_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import Contacts", "", "Excel (*.xlsx *.xlsm)")
        if not path:
            return None
        try:
            rep = subdir.import_xlsx(path)
        except Exception as e:
            QMessageBox.warning(self, "Company Directory", str(e))
            return None
        self.contacts = subdir.load()
        self.refresh()
        QMessageBox.information(
            self, "Company Directory",
            f"Read {rep['rows']} contacts from sheet \"{rep['sheet']}\": "
            f"{rep['added']} added, {rep['updated']} updated. "
            f"{rep['total']} in the directory.")
        return rep


def _ask_password(parent):
    from PySide6.QtWidgets import QLineEdit
    pw, ok = QInputDialog.getText(parent, "Company Contacts",
                                  "Password:", QLineEdit.Password)
    return pw if ok else None


class DirectoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Company Directory")
        self.resize(1300, 760)
        v = QVBoxLayout(self)
        self.w = DirectoryWidget(self)
        v.addWidget(self.w)
        from .closebutton import ensure       # (Chief, Nov 7)
        self.close_button = ensure(self)


class DirectoryPage(QWidget):
    """Project Center page."""

    def __init__(self, center):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        t = QLabel("Company Directory")
        t.setObjectName("pcH1")
        v.addWidget(t)
        self.w = DirectoryWidget(self)
        v.addWidget(self.w, 1)

    def refresh(self):
        self.w.contacts = subdir.load()
        self.w.refresh()
