"""Request Signatures and Signature Requests (tracking) dialogs."""
import html
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import esign, icons, mail, settings, theme


class RequestDialog(QDialog):
    """Who signs, where, and the message. Stays open while you draw
    fields on the page."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Request Signatures")
        self.setModal(False)
        self.resize(640, 640)
        v = QVBoxLayout(self)
        intro = QLabel("Send this PDF to be signed. Signers get an email "
                       "link and sign in any browser - no account needed. "
                       "You get the signed copy with a certificate of "
                       "completion.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        g = QGroupBox("1. Signers (in signing order)")
        gv = QVBoxLayout(g)
        self.signers = QTableWidget(0, 3)
        self.signers.setHorizontalHeaderLabels(["Name", "Email", "Order"])
        self.signers.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.signers.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        self.signers.verticalHeader().setVisible(False)
        self.signers.setFixedHeight(130)
        self.signers.itemChanged.connect(lambda _i: self._signer_names())
        gv.addWidget(self.signers)
        h = QHBoxLayout()
        add = QPushButton("Add signer")
        add.clicked.connect(lambda: self.add_signer())
        rm = QPushButton("Remove")
        rm.clicked.connect(self._remove_signer)
        h.addWidget(add)
        h.addWidget(rm)
        h.addStretch()
        tip = QLabel("Same order number = sign at the same time")
        tip.setObjectName("muted")
        h.addWidget(tip)
        gv.addLayout(h)
        v.addWidget(g)
        g2 = QGroupBox("2. Fields")
        g2v = QVBoxLayout(g2)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Place"))
        self.kind = QComboBox()
        for k in esign.KINDS:
            self.kind.addItem(esign.KIND_LABEL[k], k)
        h2.addWidget(self.kind)
        h2.addWidget(QLabel("for"))
        self.who = QComboBox()
        h2.addWidget(self.who, 1)
        draw = QPushButton("Draw on Page")
        draw.setIcon(icons.icon("fs_signature"))
        draw.clicked.connect(self._draw)
        h2.addWidget(draw)
        g2v.addLayout(h2)
        h3 = QHBoxLayout()
        auto = QPushButton("Find Signature Lines")
        auto.setToolTip("Puts fields on blanks next to 'Signature', "
                        "'Date', 'Initials' and 'Name'")
        auto.clicked.connect(self._auto)
        h3.addWidget(auto)
        h3.addStretch()
        self.count = QLabel()
        h3.addWidget(self.count)
        g2v.addLayout(h3)
        v.addWidget(g2)
        g3 = QGroupBox("3. Message")
        f = QFormLayout(g3)
        self.title = QLineEdit(os.path.splitext(os.path.basename(
            win._path or "Document"))[0])
        self.msg = QPlainTextEdit()
        self.msg.setFixedHeight(70)
        self.msg.setPlaceholderText("Please review and sign.")
        self.days = QSpinBox()
        self.days.setRange(1, 180)
        self.days.setValue(30)
        self.days.setSuffix(" days")
        self.provider = QComboBox()
        self.provider.addItem("QuantiSheet relay (no account needed)", "hub")
        self.provider.addItem("DocuSign (your DocuSign account)",
                              "docusign")
        f.addRow("Subject", self.title)
        f.addRow("Message", self.msg)
        f.addRow("Expires after", self.days)
        f.addRow("Send with", self.provider)
        v.addWidget(g3)
        bb = QDialogButtonBox()
        send = bb.addButton("Send for Signature", QDialogButtonBox.AcceptRole)
        send.setObjectName("primary")
        send.setStyleSheet(f"background:{theme.color('accent').name()};"
                           f"color:white;font-weight:600;padding:6px 14px")
        send.clicked.connect(self._send)
        bb.addButton(QDialogButtonBox.Close).clicked.connect(self.close)
        v.addWidget(bb)
        self.add_signer(settings.author(), settings.get("email", ""), 2)
        self.add_signer()
        self.refresh()

    def add_signer(self, name="", email="", order=1):
        self.signers.blockSignals(True)
        r = self.signers.rowCount()
        self.signers.insertRow(r)
        self.signers.setItem(r, 0, QTableWidgetItem(name))
        self.signers.setItem(r, 1, QTableWidgetItem(email))
        self.signers.setItem(r, 2, QTableWidgetItem(str(order)))
        self.signers.blockSignals(False)
        self._signer_names()

    def _remove_signer(self):
        r = self.signers.currentRow()
        if r >= 0:
            self.signers.removeRow(r)
            self._signer_names()

    def _signer_names(self):
        cur = self.who.currentIndex()
        self.who.clear()
        for r in range(self.signers.rowCount()):
            it = self.signers.item(r, 0)
            self.who.addItem(f"Signer {r + 1}: "
                             f"{(it.text() if it else '') or '(no name)'}")
        if 0 <= cur < self.who.count():
            self.who.setCurrentIndex(cur)

    def signer_list(self):
        out = []
        for r in range(self.signers.rowCount()):
            vals = [(self.signers.item(r, c).text().strip()
                     if self.signers.item(r, c) else "") for c in range(3)]
            if not any(vals):
                continue
            try:
                order = int(vals[2] or 1)
            except ValueError:
                order = 1
            out.append({"name": vals[0], "email": vals[1], "order": order})
        return out

    def refresh(self):
        v = self.win._view
        if not v:
            self.count.setText("Open a PDF first.")
            return
        fl = esign.fields(v.doc)
        per = {}
        for f in fl:
            per[f["signer"]] = per.get(f["signer"], 0) + 1
        self.count.setText(f"{len(fl)} field(s): " + ", ".join(
            f"signer {k + 1}: {n}" for k, n in sorted(per.items()))
            if fl else "No fields yet.")

    def _draw(self):
        v = self.win._view
        if not v:
            return
        v.esign_spec = (self.kind.currentData(), max(0,
                                                     self.who.currentIndex()))
        self.win.set_tool("esign_field", ask=False)
        self.win._flash("Drag a box where they should "
                        f"{self.kind.currentText().lower()} - press Esc "
                        "when done")
        try:
            v.page_changed.connect(self.refresh, Qt.UniqueConnection)
        except (RuntimeError, TypeError):
            pass

    def _auto(self):
        v = self.win._view
        if not v:
            return
        marks = esign.auto_place(v.doc, len(self.signer_list()))
        if not marks:
            QMessageBox.information(self, "Find Signature Lines",
                                    "No signature lines found - draw the "
                                    "fields instead.")
            return
        v.apply_marks(marks)
        self.refresh()
        self.win._flash(f"Placed {len(marks)} field(s) for signer 1 - "
                        "drag them or change who signs in the Markups List")

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def _send(self):
        v = self.win._view
        signers = self.signer_list()
        if not v or not signers:
            return
        bad = [s["email"] for s in signers if not mail.valid(s["email"])]
        if bad or any(not s["name"] for s in signers):
            QMessageBox.information(self, "Signers", "Every signer needs a "
                                    "name and a valid email.")
            return
        if v.dirty or not self.win._path:
            if not self.win.save_file():
                return
        provider = self.provider.currentData()
        if provider == "docusign":
            from . import esign_docusign as ds
            if not ds.configured() and not docusign_settings(self):
                return
        try:
            env = esign.send(self.win._path, signers, self.title.text()
                             .strip(), self.msg.toPlainText().strip(),
                             self.days.value(), provider=provider)
        except Exception as e:
            QMessageBox.warning(self, "Request Signatures", str(e))
            return
        self.win.set_tool(None, ask=False)
        QMessageBox.information(
            self, "Sent", f"Sent \"{env['title']}\" to "
            f"{', '.join(s['name'] for s in env['signers'])}.\n\n"
            "Track it in Document > Signature Requests. When everyone has "
            "signed, get the signed copy there.")
        self.close()


class TrackerDialog(QDialog):
    COLS = ["Document", "Status", "Signed", "Sent", "Waiting on", "With"]

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Signature Requests")
        self.resize(900, 460)
        v = QVBoxLayout(self)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._detail)
        v.addWidget(self.table, 1)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        self.info.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.info.setOpenExternalLinks(True)
        v.addWidget(self.info)
        h = QHBoxLayout()
        for label, fn in (("Refresh", self.refresh_all),
                          ("Remind", self._remind),
                          ("Get Signed PDF", self._finish),
                          ("Cancel Request", self._void)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        h.addWidget(close)
        v.addLayout(h)
        self.envs = []
        self.fill()

    def fill(self):
        reg = esign.registry()
        self.envs = sorted(reg.values(), key=lambda e: e["created"],
                           reverse=True)
        self.table.setRowCount(len(self.envs))
        for i, e in enumerate(self.envs):
            st = e.get("last_status") or {}
            sg = st.get("signers") or [{"status": "sent", **s}
                                       for s in e["signers"]]
            n_signed = sum(1 for s in sg if s.get("status") == "signed")
            waiting = [s["name"] for s in sg
                       if s.get("status") in ("sent", "viewed")]
            vals = [e["title"], e.get("status", "sent").title(),
                    f"{n_signed} of {len(sg)}", e["created"][:10],
                    ", ".join(waiting), "DocuSign" if
                    e["provider"] == "docusign" else "QuantiSheet relay"]
            for c, val in enumerate(vals):
                self.table.setItem(i, c, QTableWidgetItem(val))

    def _cur(self):
        r = self.table.currentRow()
        return self.envs[r] if 0 <= r < len(self.envs) else None

    def _detail(self):
        e = self._cur()
        if not e:
            return
        st = e.get("last_status") or {}
        rows = []
        for s in st.get("signers") or e["signers"]:
            rows.append(f"<b>{html.escape(s['name'])}</b> "
                        f"&lt;{html.escape(s['email'])}&gt; - "
                        f"{html.escape(s.get('status', 'sent'))}"
                        + (f", signed {s['signed'][:16].replace('T', ' ')}"
                           if s.get("signed") else ""))
        if e.get("signed_path"):
            rows.append(f"Signed copy: <a href='{QUrl.fromLocalFile(e['signed_path']).toString()}'>"
                        f"{html.escape(os.path.basename(e['signed_path']))}"
                        "</a>")
        self.info.setText("<br>".join(rows))

    def refresh_all(self):
        errors = []
        for e in self.envs:
            if e.get("status") in ("completed", "voided", "declined",
                                   "expired"):
                continue
            try:
                st = esign.status(e)
                if e["provider"] == "hub" and st["status"] == "sent":
                    esign.notify_ready(e, st)
            except Exception as ex:
                errors.append(f"{e['title']}: {ex}")
        self.fill()
        if errors:
            QMessageBox.warning(self, "Signature Requests",
                                "\n".join(errors[:5]))

    def _remind(self):
        e = self._cur()
        if not e or e["provider"] != "hub":
            return
        st = esign.status(e)
        n = esign.notify_ready(e, st, remind=True)
        self.win._flash(f"Reminded {n} signer(s).")
        self.fill()

    def _finish(self):
        e = self._cur()
        if not e:
            return
        try:
            path = esign.finish(e)
        except Exception as ex:
            QMessageBox.information(self, "Get Signed PDF", str(ex))
            return
        self.fill()
        self.win.open_path(path)

    def _void(self):
        e = self._cur()
        if not e or QMessageBox.question(
                self, "Cancel Request", f"Cancel \"{e['title']}\"? Signers "
                "can no longer open it.") != QMessageBox.Yes:
            return
        try:
            esign.void(e, "Cancelled by sender")
        except Exception as ex:
            QMessageBox.warning(self, "Cancel Request", str(ex))
        self.fill()


def docusign_settings(parent):
    """Ask for the DocuSign account details (kept in Settings)."""
    d = QDialog(parent)
    d.setWindowTitle("DocuSign")
    f = QFormLayout(d)
    note = QLabel("From DocuSign Admin > Apps and Keys: the account's base "
                  "URI and API account ID, and an access token.")
    note.setWordWrap(True)
    f.addRow(note)
    base = QLineEdit(settings.get("docusign_base") or
                     "https://demo.docusign.net/restapi")
    acct = QLineEdit(settings.get("docusign_account") or "")
    from . import secretstore
    tok = QLineEdit(secretstore.get_secret("docusign_token"))
    tok.setEchoMode(QLineEdit.Password)
    f.addRow("Base URI", base)
    f.addRow("API account ID", acct)
    f.addRow("Access token", tok)
    bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    f.addRow(bb)
    if not d.exec():
        return False
    base_url = base.text().strip().rstrip("/")
    if not base_url.endswith("/restapi"):
        base_url += "/restapi"
    settings.set("docusign_base", base_url)
    settings.set("docusign_account", acct.text().strip())
    secretstore.set_secret("docusign_token", tok.text().strip())
    return True
