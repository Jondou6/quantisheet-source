"""Windows for the project assistants (Nov 23, Jon): Draft Daily Log From
Notes, Check Submittal Against Spec, and Project Risk Flags. Each opens
from Project Center (the Daily Log page, a submittal page, Home) and from
the AI tab / Review or Project menus."""
import datetime as dt
import os

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QHeaderView, QLabel, QListWidget,
                               QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import pmassist as pa


def _ai(prompt, num_predict=300):
    from .ai import review
    return review.stream(prompt, num_ctx=4096, num_predict=num_predict)


# --------------------------------------------------------------- daily log
class DailyDraftDialog(QDialog):
    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store
        self.photos = []
        self.rec = None
        self.saved = None
        self.setWindowTitle("Draft Daily Log From Notes")
        self.resize(760, 680)
        v = QVBoxLayout(self)
        intro = QLabel("Type or paste the day's notes, one item per line "
                       "(\"Example Plumbing 4 men 8 hrs rough-in level 2\", "
                       "\"Concrete delivered from ...\", \"Rained 2 hrs\"). "
                       "They are sorted into the log's parts for you to "
                       "check before saving.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        f = QFormLayout()
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        f.addRow("Date", self.day)
        v.addLayout(f)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("The day's notes...")
        v.addWidget(self.notes, 2)
        self.photo_list = QListWidget()
        self.photo_list.setMaximumHeight(70)
        v.addWidget(self.photo_list)
        self.tidy = QCheckBox("Tidy the work wording with the AI on this PC "
                              "(when it's running)")
        v.addWidget(self.tidy)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        v.addWidget(self.preview, 2)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b = bb.addButton("Add Photos…", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.add_photos())
        b = bb.addButton("Draft", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.draft())
        self.save_btn = bb.addButton("Save as Draft Daily Log",
                                     QDialogButtonBox.ActionRole)
        self.save_btn.clicked.connect(lambda: self.save())
        self.save_btn.setEnabled(store is not None)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def add_photos(self, paths=None):
        if paths is None:
            paths, _f = QFileDialog.getOpenFileNames(
                self, "Photos", "", "Pictures (*.jpg *.jpeg *.png *.heic)")
        for p in paths or []:
            if p not in self.photos:
                self.photos.append(p)
                self.photo_list.addItem(os.path.basename(p))
        return self.photos

    def draft(self, ask=None):
        rec = pa.draft_daily(self.notes.toPlainText(),
                             self.day.date().toString("yyyy-MM-dd"),
                             self.photos)
        if self.tidy.isChecked() and rec["work"].strip():
            try:
                text = (ask or _ai)(pa.tidy_prompt(rec["work"]))
                if text and text.strip():
                    rec["work"] = text.strip()
            except Exception as e:                        # noqa: BLE001
                self.status.setText(f"The AI on this PC isn't answering "
                                    f"({str(e)[:100]}); the notes are kept "
                                    "as typed.")
        self.rec = rec
        self.preview.setPlainText(self.text(rec))
        return rec

    @staticmethod
    def text(rec):
        out = [f"Daily log {rec['date']} (draft)"]
        if rec["manpower"]:
            out.append("Manpower:")
            out += [f"  {m['company']}: {m['workers']} x {m['hours']:g} h"
                    + (f" - {m['notes']}" if m["notes"] else "")
                    for m in rec["manpower"]]
        for key, label in (("work", "Work performed"),
                           ("safety", "Safety"),
                           ("inspections_note", "Inspections")):
            if rec[key]:
                out.append(f"{label}:\n  " + rec[key].replace("\n", "\n  "))
        for key, label, fmt in (
                ("deliveries", "Deliveries",
                 lambda d: f"{d['time']} {d['supplier']}: {d['contents']}"),
                ("delays", "Delays",
                 lambda d: f"{d['cause']} {d['hours']:g} h: "
                           f"{d['description']}"),
                ("visitors", "Visitors", lambda d: d["purpose"])):
            if rec[key]:
                out.append(f"{label}:")
                out += ["  " + fmt(d).strip() for d in rec[key]]
        return "\n".join(out)

    def save(self):
        if self.store is None:
            return None
        rec = self.rec or self.draft()
        rec = dict(rec)
        if self.photos:
            rec["photos"] = [self.store.attach(p, defer=True)
                             for p in self.photos if os.path.exists(p)]
        self.saved = self.store.save_record("daily", rec)
        self.status.setText("Saved as a draft daily log - open it on the "
                            "Daily Log page to check and submit it.")
        return self.saved


# -------------------------------------------------------------- submittals
class SubmittalCheckDialog(QDialog):
    def __init__(self, parent=None, store=None, spec_doc=None, rec=None):
        super().__init__(parent)
        self.store = store
        self.spec_doc = spec_doc
        self.sub_path = None
        self.rows = []
        self.setWindowTitle("Check Submittal Against Spec")
        self.resize(900, 600)
        v = QVBoxLayout(self)
        intro = QLabel("Pick the submittal and its PDF. The spec section is "
                       "read for its listed manufacturers, the standards it "
                       "names, the warranty and the submittal items it asks "
                       "for, and the submittal is checked for each. It is a "
                       "first look, not the architect's review.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        f = QFormLayout()
        self.pick = QComboBox()
        self.pick.addItem("(type the spec section below)", None)
        for r in (store.list("submittal") if store is not None else []):
            self.pick.addItem(f"{r.get('_no') or ''} {r.get('title') or ''} "
                              f"({r.get('spec') or 'no section'})".strip(),
                              r)
        if rec is not None:
            i = next((k for k in range(self.pick.count())
                      if (self.pick.itemData(k) or {}).get("_id") ==
                      rec.get("_id")), -1)
            if i >= 0:
                self.pick.setCurrentIndex(i)
        f.addRow("Submittal", self.pick)
        from PySide6.QtWidgets import QLineEdit
        self.code = QLineEdit()
        self.code.setPlaceholderText("e.g. 08 71 00")
        self.pick.currentIndexChanged.connect(lambda _i: self._take_code())
        f.addRow("Spec section", self.code)
        self.spec_label = QLabel("")
        f.addRow("Spec book", self.spec_label)
        self.sub_label = QLabel("none picked")
        f.addRow("Submittal PDF", self.sub_label)
        v.addLayout(f)
        t = self.table = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels(["Check", "The spec says", "The "
                                     "submittal shows", "Result"])
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(t, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b = bb.addButton("Spec Book…", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.pick_spec())
        b = bb.addButton("Submittal PDF…", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.pick_sub())
        b = bb.addButton("Check", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.run())
        b = bb.addButton("Copy", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.copy())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._take_code()
        self._labels()

    def _labels(self):
        name = os.path.basename(getattr(self.spec_doc, "name", "") or "") \
            if self.spec_doc is not None else ""
        self.spec_label.setText(name or "none - open the project manual or "
                                "click Spec Book…")

    def _take_code(self):
        r = self.pick.currentData()
        if r:
            self.code.setText(r.get("spec") or "")
            atts = [a for a in (r.get("attachments") or [])
                    if str(a.get("ext") or "").lower() == ".pdf"]
            if atts and self.store is not None:
                try:
                    p = self.store.attachment_path(atts[-1])
                    if p and os.path.exists(p):
                        self.sub_path = p
                        self.sub_label.setText(atts[-1].get("name") or p)
                except Exception:                         # noqa: BLE001
                    pass

    def pick_spec(self, path=None):
        import fitz
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self, "Spec Book", "",
                                                   "PDF (*.pdf)")
            if not path:
                return None
        self.spec_doc = fitz.open(path)
        self._labels()
        return self.spec_doc

    def pick_sub(self, path=None):
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self, "Submittal PDF", "",
                                                   "PDF (*.pdf)")
            if not path:
                return None
        self.sub_path = path
        self.sub_label.setText(os.path.basename(path))
        return path

    def run(self):
        import fitz
        code = self.code.text().strip()
        if self.spec_doc is None or not code:
            self.status.setText("Pick the spec book and the spec section "
                                "first.")
            return []
        spec, pages = pa.section_text(self.spec_doc, code)
        if not spec:
            self.status.setText(f"Section {code} wasn't found in the spec "
                                "book.")
            return []
        sub = ""
        if self.sub_path:
            with fitz.open(self.sub_path) as d:
                sub = "\n".join(d[p].get_text() or ""
                                for p in range(d.page_count))
        self.rows = pa.check_submittal(spec, sub, code)
        t = self.table
        t.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            for c, val in enumerate((r["check"], r["spec"], r["found"],
                                     "OK" if r["ok"] else "Check")):
                t.setItem(i, c, QTableWidgetItem(val))
        bad = sum(1 for r in self.rows if not r["ok"])
        self.status.setText(
            f"Section {code}, spec pages "
            + ", ".join(str(p + 1) for p in pages[:6])
            + (" ..." if len(pages) > 6 else "")
            + f". {len(self.rows)} checks, {bad} to look at."
            + ("" if sub else " No submittal PDF was picked, so every item "
               "shows as not found."))
        return self.rows

    def copy(self):
        text = "\n".join(f"{r['check']}: spec {r['spec']} - submittal "
                         f"{r['found']} ({'OK' if r['ok'] else 'Check'})"
                         for r in self.rows)
        QGuiApplication.clipboard().setText(text)
        return text


# -------------------------------------------------------------- risk flags
class RiskFlagsDialog(QDialog):
    def __init__(self, parent=None, store=None, today=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Project Risk Flags")
        self.resize(900, 520)
        v = QVBoxLayout(self)
        self.flags = pa.risk_flags(store, today) if store is not None else []
        intro = QLabel(
            f"{len(self.flags)} flag(s) from this job's RFIs, submittals, "
            "schedule, issues, change events and daily logs - each with the "
            "reason, worst first. They are rules, not predictions: check each "
            "one." if store is not None else "Open the job's Project Center "
            "first.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        t = self.table = QTableWidget(len(self.flags), 3)
        t.setHorizontalHeaderLabels(["Level", "Item", "Why"])
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        for i, f in enumerate(self.flags):
            for c, val in enumerate((f["level"], f["item"], f["reason"])):
                it = QTableWidgetItem(val)
                if c == 0 and f["level"] == "High":
                    it.setForeground(QColor("#b00020"))
                t.setItem(i, c, it)
        v.addWidget(t, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b = bb.addButton("Copy", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.copy())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def copy(self):
        text = "\n".join(f"{f['level']}: {f['item']} - {f['reason']}"
                         for f in self.flags)
        QGuiApplication.clipboard().setText(text)
        return text


def _show(dlg):
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    dlg.show()
    return dlg


def today_iso():
    return dt.date.today().isoformat()
