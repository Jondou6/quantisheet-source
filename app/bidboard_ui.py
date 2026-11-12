"""The Bid Board window (Estimate > Bid Board…): invitations to bid that
came to us, their dates, who is pricing them and how they came out. See
bidboard.py. Nothing here sends anything."""
import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from . import bidboard as B, settings

COLS = [("project", "Project"), ("gc", "GC"), ("trade", "Trade"),
        ("due", "Due"), ("due_time", "Time"), ("job_walk", "Job walk"),
        ("rfi_due", "Questions due"), ("estimator", "Estimator"),
        ("status", "Status"), ("amount", "Our bid"), ("_go", "Go / no-go"),
        ("_same", "Same project?")]
STATUS_BG = {"Won": "#cdf0cd", "Lost": "#ffcdcd", "Declined": "#e6e6e6",
             "Submitted": "#c8e6ff", "Accepted": "#fff1bd"}
EDIT = [("project", "Project *"), ("gc", "GC (who invited us)"),
        ("trade", "Trade / scope"), ("address", "Address"),
        ("location", "City, state"), ("due", "Bid due (date)"),
        ("due_time", "Bid due (time)"),
        ("job_walk", "Job walk (date and time)"),
        ("rfi_due", "Questions due (date)"), ("estimator", "Estimator"),
        ("amount", "Our bid $")]


def _money(text):
    if not text:
        return ""
    whole, _dot, cents = text.partition(".")
    return f"${int(whole):,}.{(cents + '00')[:2]}"


class OpportunityDialog(QDialog):
    """Add or edit one opportunity. `found`: fields read from an email,
    shown so the user knows what to check."""

    def __init__(self, parent=None, opp=None, found=None, items=None):
        super().__init__(parent)
        self.opp = dict(opp or {"status": "Undecided"})
        self.items = items
        self.setWindowTitle("Opportunity" if opp and opp.get("id")
                            else "New Opportunity")
        self.resize(560, 560)
        v = QVBoxLayout(self)
        if found is not None:
            names = dict(EDIT)
            names["plan_links"] = "Plan links"
            v.addWidget(QLabel(
                "<b>Read from the email - check every field before you "
                "save.</b> Found: " + (", ".join(
                    names.get(k, k).rstrip(" *") for k in found) or
                    "nothing") + ". Nothing was sent, and the email was "
                "not changed."))
        f = QFormLayout()
        self.w = {}
        for key, label in EDIT:
            e = QLineEdit(self.opp.get(key) or "")
            if key in ("due", "rfi_due"):
                e.setPlaceholderText("2026-12-04 or 12/4/2026")
            if key == "job_walk":
                e.setPlaceholderText("2026-11-20 10:00 AM")
            self.w[key] = e
            f.addRow(label, e)
        self.status = QComboBox()
        self.status.addItems(B.STATUSES)
        self.status.setCurrentText(self.opp.get("status") or "Undecided")
        f.addRow("Status", self.status)
        self.links = QPlainTextEdit(self.opp.get("plan_links") or "")
        self.links.setMaximumHeight(60)
        f.addRow("Plan links", self.links)
        self.notes = QPlainTextEdit(self.opp.get("notes") or "")
        self.notes.setMaximumHeight(80)
        f.addRow("Notes (ours)", self.notes)
        v.addLayout(f)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        v.addWidget(self.warn)
        bb = QDialogButtonBox(QDialogButtonBox.Save |
                              QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.saved = None
        self._warned = None

    def values(self):
        o = dict(self.opp)
        for key, _l in EDIT:
            o[key] = self.w[key].text()
        o["status"] = self.status.currentText()
        o["plan_links"] = self.links.toPlainText()
        o["notes"] = self.notes.toPlainText()
        return o

    def save(self, confirm=None):
        """Save, after one warning when it looks like a project already
        on the board (Save again keeps both; they are then shown as the
        same project)."""
        try:
            o = B.clean(self.values())
        except B.BoardError as e:
            self.warn.setText(f"<span style='color:#b00020'>{e}</span>")
            return None
        for key in ("due", "rfi_due"):
            if self.w[key].text().strip() and not o[key]:
                self.warn.setText(
                    "<span style='color:#b00020'>That date wasn't "
                    f"understood: {self.w[key].text()!r}. Use 2026-12-04 "
                    "or 12/4/2026.</span>")
                return None
        dups = B.duplicates(o, self.items)
        sig = tuple(x["id"] for x, _w in dups)
        if dups and self._warned != sig and confirm is None:
            self._warned = sig
            self.warn.setText(
                "<b>This looks like a project already on the board:</b>"
                "<br>" + "<br>".join(
                    f"{x['project']} ({x['gc'] or 'no GC'}, {x['status']}"
                    + (f", {x['estimator']}" if x["estimator"] else "")
                    + "): " + "; ".join(w) for x, w in dups) +
                "<br>Save again to keep both (they will be shown as the "
                "same project), or Cancel.")
            return None
        self.saved = B.save(o)
        self.accept()
        return self.saved


class GoDialog(QDialog):
    """The go / no-go checklist. It gives a score and a recommendation;
    the person decides, and the reason is kept."""

    def __init__(self, opp, parent=None, items=None):
        super().__init__(parent)
        self.opp = opp
        self.setWindowTitle(f"Go / No-Go - {opp['project']}")
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{opp['project']}</b>" + (
            f" for {opp['gc']}" if opp["gc"] else "")))
        f = QFormLayout()
        self.box = {}
        old = (opp.get("go") or {}).get("answers") or {}
        hist = B.history_answer(opp["gc"], items)
        for key, label in B.FACTORS:
            c = QComboBox()
            c.addItems([""] + [a for a, _v in B.ANSWERS])
            c.setCurrentText(old.get(key) or
                             (hist if key == "history" else ""))
            c.currentIndexChanged.connect(lambda _i: self.refresh())
            self.box[key] = c
            f.addRow(label, c)
        v.addLayout(f)
        if hist:
            v.addWidget(QLabel(f"\"We win with this GC\" starts at {hist} "
                               "from your results on this board."))
        self.score = QLabel("")
        self.score.setWordWrap(True)
        v.addWidget(self.score)
        self.reason = QLineEdit((opp.get("go") or {}).get("reason") or "")
        self.reason.setPlaceholderText("Why (kept with the decision)")
        v.addWidget(self.reason)
        row = QHBoxLayout()
        for text, fn in (("Decide Go", lambda: self.decide("Go")),
                         ("Decide No-Go", lambda: self.decide("No-go")),
                         ("Weights…", self.weights),
                         ("Cancel", self.reject)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f_=fn: f_())
            row.addWidget(b)
        v.addLayout(row)
        self.result_opp = None
        self.refresh()

    def answers(self):
        return {k: c.currentText() for k, c in self.box.items()
                if c.currentText()}

    def refresh(self):
        sc = B.go_score(self.answers())
        if sc["score"] is None:
            self.score.setText("Answer what you know; blanks are left out "
                               "of the score.")
        else:
            self.score.setText(
                f"Score <b>{sc['score']:g}</b> of 100 on {sc['answered']} "
                f"of {sc['of']} answered. Recommendation: <b>"
                f"{sc['recommendation']}</b>. The decision is yours.")
        return sc

    def decide(self, decision):
        if not self.reason.text().strip():
            self.score.setText(self.score.text().split("<br>")[0] +
                               "<br><span style='color:#b00020'>Give a "
                               "reason first - it is kept with the "
                               "decision.</span>")
            return None
        o = B.record_decision(dict(self.opp), self.answers(), decision,
                              self.reason.text(),
                              settings.get("author", "") or "")
        self.result_opp = B.save(o)
        self.accept()
        return self.result_opp

    def weights(self, values=None):
        """Edit the weights and the two scores (they are your settings)."""
        cfg = B.go_settings()
        if values is None:
            d = QDialog(self)
            d.setWindowTitle("Go / No-Go Weights")
            f = QFormLayout(d)
            spins = {}
            for key, label in B.FACTORS:
                s = QDoubleSpinBox()
                s.setRange(0, 1000)
                s.setDecimals(0)
                s.setValue(cfg["weights"][key])
                spins[key] = s
                f.addRow(label, s)
            go, maybe = QDoubleSpinBox(), QDoubleSpinBox()
            for s, val in ((go, cfg["go"]), (maybe, cfg["maybe"])):
                s.setRange(0, 100)
                s.setDecimals(0)
                s.setValue(val)
            f.addRow("Go at a score of", go)
            f.addRow("No-go below", maybe)
            bb = QDialogButtonBox(QDialogButtonBox.Ok |
                                  QDialogButtonBox.Cancel)
            bb.accepted.connect(d.accept)
            bb.rejected.connect(d.reject)
            f.addRow(bb)
            if d.exec() != QDialog.Accepted:
                return None
            values = {"weights": {k: s.value() for k, s in spins.items()},
                      "go": go.value(), "maybe": maybe.value()}
        try:
            cfg = B.set_go_settings(values.get("weights"), values.get("go"),
                                    values.get("maybe"))
        except B.BoardError as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return None
        self.refresh()
        return cfg


class BidBoard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bid Board")
        self.resize(1180, 640)
        self.setAcceptDrops(True)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)
        # ---- the pipeline
        pw = QWidget()
        pv = QVBoxLayout(pw)
        top = QHBoxLayout()
        top.addWidget(QLabel("Show"))
        self.filter = QComboBox()
        self.filter.addItems(["Open (undecided, accepted, submitted)",
                              "Everything"] + list(B.STATUSES))
        self.filter.currentIndexChanged.connect(lambda _i: self.refresh())
        top.addWidget(self.filter)
        for text, fn, tip in (
                ("Add…", self.add, "Type in an invitation"),
                ("From Email…", self.from_email,
                 "Read a saved invitation email (.eml). You can also drag "
                 "the file onto this window. Nothing is sent and the email "
                 "is not changed"),
                ("Paste Email Text…", self.from_text,
                 "Paste the text of an invitation"),
                ("Edit…", self.edit, ""),
                ("Go / No-Go…", self.go, "Checklist, score, your decision"),
                ("Set Status…", self.set_status, ""),
                ("Not the Same Project", self.not_same,
                 "The selected row was matched to another by mistake"),
                ("Remove", self.remove, "")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, f_=fn: f_())
            top.addWidget(b)
        top.addStretch(1)
        pv.addLayout(top)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLS])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().hide()
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.edit())
        pv.addWidget(self.table, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        pv.addWidget(self.note)
        tabs.addTab(pw, "Pipeline")
        # ---- the calendar
        cw = QWidget()
        cv = QVBoxLayout(cw)
        self.cal = QTableWidget(0, 4)
        self.cal.setHorizontalHeaderLabels(["Date", "Time", "What",
                                            "Project (GC)"])
        self.cal.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cal.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        cv.addWidget(self.cal, 1)
        b = QPushButton("Export Calendar File (.ics)…")
        b.setToolTip("A file to import into Outlook or another calendar. "
                     "Nothing is sent")
        b.clicked.connect(lambda: self.export_ics())
        cv.addWidget(b, 0, Qt.AlignLeft)
        tabs.addTab(cw, "Calendar")
        # ---- results
        sw = QWidget()
        sv = QVBoxLayout(sw)
        sv.addWidget(QLabel("<b>Win rate by GC</b> (counts Won and Lost "
                            "only)"))
        self.by_gc = QTableWidget(0, 6)
        self.by_gc.setHorizontalHeaderLabels(
            ["GC", "Won", "Lost", "Win rate", "Waiting", "Declined"])
        sv.addWidget(self.by_gc, 2)
        sv.addWidget(QLabel("<b>Bids per month</b> (by due date)"))
        self.by_month = QTableWidget(0, 4)
        self.by_month.setHorizontalHeaderLabels(
            ["Month", "Bids sent", "Won", "Lost"])
        sv.addWidget(self.by_month, 1)
        sv.addWidget(QLabel("<b>Workload</b> (open bids per estimator)"))
        self.load_t = QTableWidget(0, 4)
        self.load_t.setHorizontalHeaderLabels(
            ["Estimator", "Open bids", "Due within 7 days", "Next due"])
        sv.addWidget(self.load_t, 1)
        tabs.addTab(sw, "Results")
        for t in (self.by_gc, self.by_month, self.load_t):
            t.setEditTriggers(QTableWidget.NoEditTriggers)
            t.horizontalHeader().setSectionResizeMode(0,
                                                      QHeaderView.Stretch)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.items, self.shown = [], []
        self.refresh()

    # ------------------------------------------------------------- data
    def refresh(self, select=None):
        self.items = B.load()
        pick = self.filter.currentText()
        if pick.startswith("Open"):
            rows = [o for o in self.items
                    if o["status"] in B.OPEN + ("Submitted",)]
        elif pick == "Everything":
            rows = list(self.items)
        else:
            rows = [o for o in self.items if o["status"] == pick]
        rows.sort(key=B.sort_key)
        self.shown = rows
        same = B.groups(self.items)
        today = _dt.date.today().isoformat()
        t = self.table
        t.setRowCount(len(rows))
        for r, o in enumerate(rows):
            for c, (key, _label) in enumerate(COLS):
                if key == "_go":
                    g = o.get("go") or {}
                    sc = g.get("score")
                    text = "" if not g else (
                        f"{g.get('decision')} (score "
                        f"{'-' if sc is None else format(sc, 'g')})")
                elif key == "_same":
                    text = f"#{same[o['id']][0]}: {same[o['id']][1]}" \
                        if o["id"] in same else ""
                elif key == "amount":
                    text = _money(o["amount"])
                else:
                    text = o.get(key) or ""
                it = QTableWidgetItem(text)
                if key == "status" and o["status"] in STATUS_BG:
                    it.setBackground(QColor(STATUS_BG[o["status"]]))
                    it.setForeground(QColor("#111111"))
                if key == "due" and o["due"] and o["due"] < today and \
                        o["status"] in B.OPEN:
                    it.setText(text + " (past)")
                    it.setBackground(QColor("#ffcdcd"))
                    it.setForeground(QColor("#111111"))
                if key == "_same" and text:
                    it.setBackground(QColor("#ffe1aa"))
                    it.setForeground(QColor("#111111"))
                t.setItem(r, c, it)
            if select and o["id"] == select:
                t.selectRow(r)
        t.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        n_same = len({g[0] for g in same.values()})
        self.note.setText(
            f"{len(rows)} shown of {len(self.items)}." + (
                f" {n_same} project(s) came from more than one invitation "
                "- price each once and send every GC the same number."
                if n_same else "") + (
                "" if self.items else " Add an invitation, or drag a saved "
                "email (.eml) here."))
        ev = B.events(self.items)
        self.cal.setRowCount(len(ev))
        for r, e in enumerate(ev):
            for c, text in enumerate((e["date"], e["time"], e["what"],
                                      e["project"] + (f" ({e['gc']})"
                                                      if e["gc"] else ""))):
                self.cal.setItem(r, c, QTableWidgetItem(text))
        gc = B.win_rate_by_gc(self.items)
        self.by_gc.setRowCount(len(gc))
        for r, x in enumerate(gc):
            for c, text in enumerate((
                    x["gc"], x["won"], x["lost"],
                    "not enough yet" if x["rate"] is None
                    else f"{x['rate']:g}%", x["pending"], x["declined"])):
                self.by_gc.setItem(r, c, QTableWidgetItem(str(text)))
        mo = B.bids_per_month(self.items)
        self.by_month.setRowCount(len(mo))
        for r, x in enumerate(mo):
            for c, text in enumerate((x["month"], x["submitted"], x["won"],
                                      x["lost"])):
                self.by_month.setItem(r, c, QTableWidgetItem(str(text)))
        wl = B.workload(self.items)
        self.load_t.setRowCount(len(wl))
        for r, x in enumerate(wl):
            for c, text in enumerate((x["estimator"], x["open"], x["due_7"],
                                      x["next_due"])):
                self.load_t.setItem(r, c, QTableWidgetItem(str(text)))
        return rows

    def current(self):
        r = self.table.currentRow()
        return self.shown[r] if 0 <= r < len(self.shown) else None

    def _need(self):
        o = self.current()
        if o is None:
            QMessageBox.information(self, self.windowTitle(),
                                    "Select a row first.")
        return o

    # ---------------------------------------------------------- actions
    def add(self, opp=None, found=None, show=True):
        dlg = OpportunityDialog(self, opp, found, self.items)
        if show:
            if dlg.exec() == QDialog.Accepted and dlg.saved:
                self.refresh(dlg.saved["id"])
            return dlg.saved
        return dlg

    def edit(self):
        o = self._need()
        if o is None:
            return None
        dlg = OpportunityDialog(self, o, None, self.items)
        if dlg.exec() == QDialog.Accepted and dlg.saved:
            self.refresh(dlg.saved["id"])
        return dlg.saved

    def from_email(self, path=None, show=True):
        """A draft from a saved invitation email, for the user to check
        and save. Nothing is saved until they do."""
        from . import bidinvite
        if path is None:
            path, _f = QFileDialog.getOpenFileName(
                self, "Invitation Email", "",
                "Saved email (*.eml);;Text (*.txt)")
            if not path:
                return None
        try:
            draft, found = bidinvite.from_file(path)
        except B.BoardError as e:
            QMessageBox.information(self, self.windowTitle(), str(e))
            return None
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, self.windowTitle(),
                                f"That email couldn't be read: {e}")
            return None
        return self.add(draft, found, show)

    def from_text(self, text=None, show=True):
        from . import bidinvite
        if text is None:
            text, ok = QInputDialog.getMultiLineText(
                self, "Paste Email Text", "The invitation's text:")
            if not ok or not text.strip():
                return None
        draft, found = bidinvite.parse(text=text)
        return self.add(draft, found, show)

    def go(self, show=True):
        o = self._need()
        if o is None:
            return None
        dlg = GoDialog(o, self, self.items)
        if show:
            if dlg.exec() == QDialog.Accepted:
                self.refresh(o["id"])
            return dlg.result_opp
        return dlg

    def set_status(self, status=None, amount=None):
        o = self._need()
        if o is None:
            return None
        if status is None:
            status, ok = QInputDialog.getItem(
                self, "Status", o["project"], list(B.STATUSES),
                B.STATUSES.index(o["status"]), False)
            if not ok:
                return None
            if status in ("Submitted", "Won", "Lost") and not o["amount"]:
                amount, ok = QInputDialog.getText(
                    self, "Our Bid", "Our bid $ (leave blank to skip):")
                if not ok:
                    return None
        try:
            got = B.set_status(o["id"], status, amount or None)
        except B.BoardError as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return None
        self.refresh(o["id"])
        return got

    def not_same(self):
        o = self._need()
        if o is None:
            return None
        dups = B.duplicates(o, self.items)
        if not dups:
            return None
        for x, _why in dups:
            B.dismiss(o, x["id"])
        got = B.save(o)
        self.refresh(o["id"])
        return got

    def remove(self, confirm=None):
        o = self._need()
        if o is None:
            return False
        if confirm is None:
            confirm = QMessageBox.question(
                self, self.windowTitle(),
                f"Remove \"{o['project']}\" from the board? This can't be "
                "undone.") == QMessageBox.Yes
        if not confirm:
            return False
        B.remove(o["id"])
        self.refresh()
        return True

    def export_ics(self, path=None):
        ev = B.events(self.items)
        if not ev:
            QMessageBox.information(self, self.windowTitle(),
                                    "No dates on open bids to export.")
            return None
        if path is None:
            path, _f = QFileDialog.getSaveFileName(
                self, "Calendar File", "Bid Board.ics", "Calendar (*.ics)")
            if not path:
                return None
        return B.to_ics(ev, path)

    # ------------------------------------------------- drag an email in
    def dragEnterEvent(self, e):                          # noqa: N802
        if any(u.toLocalFile().lower().endswith((".eml", ".txt", ".msg"))
               for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):                               # noqa: N802
        for u in e.mimeData().urls():
            self.from_email(u.toLocalFile())


def show(win=None):
    dlg = BidBoard(win)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    dlg.show()
    return dlg
