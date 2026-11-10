"""Project Center: the project-management side of QuantiSheet.

One window, one layout for every tool: tools on the left, the list in the
middle (search box and one-click filters), the item on the right, saved as
you type. Home shows what is waiting on you. Ctrl+K jumps to any item.
"""
import html
import logging
import os
import threading
import time
from datetime import date, datetime

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject,
                            QRect, QSize, QSortFilterProxyModel, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter, \
    QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup,
                               QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QStackedWidget,
                               QStyle, QStyledItemDelegate, QTableView,
                               QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from .. import icons, settings, theme
from ..reportname import clean, report_file_name
from . import actions, report, schema
from .store import ProjectStore, StoreError, open_store
from .widgets import Pill, editor_for, show_date

log = logging.getLogger(__name__)
SPECIAL = {"bidcal": ("bidui", "BidCalendarPage"),
           "calendar": ("calendarui", "ProjectCalendarPage"),
           "companydir": (".subdir_ui", "DirectoryPage"),
           "cost_summary": ("costui", "CostSummaryPage"),
           "forecast": ("costui", "ForecastPage"),
           "documents": ("docsui", "DocumentsPage"),
           "gantt": ("scheduleui", "GanttPage"),
           "cashflow": ("costui", "CashFlowPage"),
           "scopesheets": ("scope_sheet_ui", "ScopeSheetsPage")}
SPECIAL_NAV = {"Project": [("gantt", "Gantt Chart", "gantt"),
                           ("calendar", "Calendar", "calendar")],
               "Cost": [("cost_summary", "Cost Summary", "budget"),
                        ("forecast", "Forecast", "forecast"),
                        ("cashflow", "Cash Flow", "trend")],
               "Documents": [("documents", "Project Files", "folder")],
               "Bidding": [("bidcal", "Bid Calendar", "calendar"),
                           ("scopesheets", "Scope Sheets", "scopesheet"),
                           ("companydir", "Company Directory", "people")]}
GROUP_ORDER = ["Project", "Field", "Design", "Cost", "Bidding", "Documents",
               "Team"]


def _ago(ts):
    if not ts:
        return "never"
    s = int(time.time() - ts)
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    return f"{s // 3600} h ago"


def is_me(store, who):
    me = (store.me or "").strip().lower()
    who = (who or "").strip().lower()
    return bool(me) and (who == me or (len(me) > 2 and me in who))


# ================================================================ model
class RecordModel(QAbstractTableModel):
    def __init__(self, store, key):
        super().__init__()
        self.store, self.key = store, key
        self.t = schema.TOOLS[key]
        self.cols = self.t["columns"]
        self.recs = []

    def set_records(self, recs):
        self.beginResetModel()
        self.recs = recs
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.recs)

    def columnCount(self, parent=QModelIndex()):
        return len(self.cols)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if o == Qt.Horizontal and role == Qt.DisplayRole:
            return report.col_label(self.key, self.cols[s])
        return None

    def data(self, idx, role=Qt.DisplayRole):
        r = self.recs[idx.row()]
        c = self.cols[idx.column()]
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return report.cell(self.store, self.key, r, c)
        if role == Qt.UserRole:
            return r["_id"]
        if role == Qt.UserRole + 1:               # sort key
            if c == "_no":
                return r.get("_n") or 0
            v = r.get(c)
            return v if isinstance(v, (int, float)) else str(v or "")
        if role == Qt.ForegroundRole:
            f = schema.field(self.key, c)
            if f and f["type"] == "date" and c in ("due", "submit_by") and \
                    schema.is_overdue(self.key, r):
                return QColor(theme.color("danger"))
            if c == "_late" and r.get("status") != "Delivered":
                return QColor(theme.color("danger"))
            if r.get("_dirty"):
                return None
        if role == Qt.FontRole and c == "_no":
            f = QFont()
            f.setBold(True)
            return f
        return None


class StatusDelegate(QStyledItemDelegate):
    def paint(self, p, opt, idx):
        text = idx.data()
        if not text:
            return super().paint(p, opt, idx)
        self.initStyleOption(opt, idx)
        style = opt.widget.style() if opt.widget else None
        if opt.state & QStyle.State_Selected and style:
            style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, p,
                                opt.widget)
        kind = schema.STATUS_COLORS.get(text, "muted")
        c = QColor(theme.color({"good": "ok", "bad": "danger",
                                "warn": "warn", "accent": "accent",
                                "accent2": "accent2",
                                "muted": "muted"}[kind]))
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        fm = opt.fontMetrics
        w = fm.horizontalAdvance(text) + 18
        h = fm.height() + 4
        r = QRect(opt.rect.x() + 6, opt.rect.center().y() - h // 2,
                  min(w, opt.rect.width() - 10), h)
        bg = QColor(c)
        bg.setAlpha(36)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, h / 2, h / 2)
        p.setPen(c)
        f = QFont(opt.font)
        f.setBold(True)
        p.setFont(f)
        p.drawText(r, Qt.AlignCenter, text)
        p.restore()


class _Proxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.setSortRole(Qt.UserRole + 1)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)


# ================================================================ form
class RecordForm(QWidget):
    """One item, edited in place and saved as you go."""
    saved = Signal(dict)
    open_other = Signal(str, str)

    def __init__(self, center, key):
        super().__init__()
        self.center = center
        self.store = center.store
        self.key = key
        self.t = schema.TOOLS[key]
        self.current = {}
        self.editors = {}
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # header
        head = QFrame()
        head.setObjectName("pcFormHead")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(18, 14, 18, 10)
        r1 = QHBoxLayout()
        self.no = QLabel()
        self.no.setObjectName("pcNo")
        r1.addWidget(self.no)
        self.pill = Pill()
        r1.addWidget(self.pill)
        self.ball = QLabel()
        self.ball.setObjectName("muted")
        r1.addWidget(self.ball)
        r1.addStretch()
        self.saved_lbl = QLabel()
        self.saved_lbl.setObjectName("muted")
        r1.addWidget(self.saved_lbl)
        hv.addLayout(r1)
        self.title = QLineEdit()
        self.title.setObjectName("pcTitle")
        self.title.setFrame(False)
        self.title.editingFinished.connect(self._save)
        hv.addWidget(self.title)
        self.bar = QHBoxLayout()
        self.bar.setSpacing(6)
        hv.addLayout(self.bar)
        outer.addWidget(head)
        # body
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self.scroll, 1)
        self.body = None

    # ---------------------------------------------------------- build
    def load(self, rec):
        self._loading = True
        self.current = dict(rec)
        tf = self.t.get("title_field", "title")
        self.no.setText(rec.get("_no", ""))
        tfield = schema.field(self.key, tf)
        if tfield and tfield["type"] == "date":
            self.title.setText(show_date(rec.get(tf)))
            self.title.setReadOnly(True)
        else:
            self.title.setText(rec.get(tf, ""))
            self.title.setReadOnly(False)
        self.title.setPlaceholderText(tfield["label"] if tfield else "")
        self._header()
        self._actions()
        body = QWidget()
        body.setObjectName("pcFormBody")
        v = QVBoxLayout(body)
        v.setContentsMargins(18, 8, 18, 24)
        v.setSpacing(10)
        self.editors = {}
        main, more = [], []
        for f in self.t["fields"]:
            if f["key"] == tf:
                continue
            filled = rec.get(f["key"]) not in (None, "", [], {})
            (main if f["quick"] or filled or f["key"] == "status"
             else more).append(f)
        v.addWidget(self._section(main))
        if more:
            tog = QToolButton()
            tog.setText(f"More details ({len(more)})")
            tog.setCheckable(True)
            tog.setObjectName("pcMore")
            tog.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            tog.setArrowType(Qt.RightArrow)
            sec = self._section(more)
            sec.setVisible(False)
            tog.toggled.connect(lambda on, s=sec, b=tog: (
                s.setVisible(on),
                b.setArrowType(Qt.DownArrow if on else Qt.RightArrow)))
            v.addWidget(tog)
            v.addWidget(sec)
        meta = QLabel(f"Created {show_date((rec.get('_created') or '')[:10])}"
                      f" by {html.escape(rec.get('_by', '') or '')}"
                      + (f"  ·  updated by {rec.get('_upd_by')}"
                         if rec.get("_upd_by") else ""))
        meta.setObjectName("muted")
        v.addWidget(meta)
        v.addStretch()
        self.scroll.setWidget(body)
        self.body = body
        if not self.store.can_edit:          # a viewer login: read only
            for ed in self.editors.values():
                ed.setEnabled(False)
            self.title.setReadOnly(True)
        else:
            from .store import LOCKED
            if self.key == "event":
                from .cost import unmatched_vendors
                miss = unmatched_vendors(self.store, rec)
                if miss:
                    # NW-08: costs that reach no subcontract are pointed out
                    warn = QLabel("No commitment for vendor " +
                                  ", ".join(miss) + ": these costs won't "
                                  "change any subcontract. Type the vendor "
                                  "as on the commitment (person or "
                                  "company).")
                    warn.setStyleSheet(
                        f"color:{theme.color('danger').name()}")
                    warn.setWordWrap(True)
                    v.insertWidget(0, warn)
            rule = LOCKED.get(self.key)
            if rule and rec.get("status") in rule[0]:
                # final (a certified pay app, NW-07): only its status and
                # payment fields stay open
                for k, ed in self.editors.items():
                    if k not in rule[1]:
                        ed.setEnabled(False)
                self.title.setReadOnly(True)
                lock = QLabel(f"{rec.get('status')}: the numbers are final. "
                              "Put corrections on the next application.")
                lock.setObjectName("muted")
                lock.setWordWrap(True)
                v.insertWidget(0, lock)
        self._loading = False

    def _section(self, fields):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(8)
        row, col = 0, 0
        wide = ("long", "lines", "attachments", "thread", "weather",
                "people")
        for f in fields:
            ed = editor_for(f, self.store, self)
            ed.set_value(self.current.get(f["key"]))
            ed.changed.connect(self._save)
            self.editors[f["key"]] = ed
            lab = QLabel(f["label"] + (" *" if f["required"] else ""))
            lab.setObjectName("pcLabel")
            if f.get("help"):
                lab.setToolTip(f["help"])
                ed.setToolTip(f["help"])
            if f["type"] in wide:
                if col:
                    row, col = row + 1, 0
                g.addWidget(lab, row, 0, 1, 4)
                g.addWidget(ed, row + 1, 0, 1, 4)
                row += 2
                continue
            g.addWidget(lab, row, col * 2)
            g.addWidget(ed, row, col * 2 + 1)
            col += 1
            if col == 2:
                row, col = row + 1, 0
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        return w

    def _header(self):
        r = self.current
        self.pill.set_status(r.get("status", ""))
        b = schema.ball_in_court(self.key, r)
        over = schema.is_overdue(self.key, r)
        bits = []
        if b:
            bits.append(f"Ball in court: <b>{html.escape(b)}</b>")
        if over:
            bits.append(f"<span style='color:{theme.color('danger').name()}'>"
                        "Overdue</span>")
        if r.get("_dirty") and self.store.connected:
            bits.append("not synced yet")
        self.ball.setText("  ·  ".join(bits))

    def _actions(self):
        while self.bar.count():
            it = self.bar.takeAt(0)
            w = it.widget()
            if w:
                # no setParent(None): this can run inside the button's own
                # click; deleteLater frees it safely afterwards (#32)
                w.hide()
                w.deleteLater()
        first = True
        for label, icon, _ok, _fn in actions.available(self.key,
                                                        self.current):
            b = QPushButton(label)
            b.setIcon(icons.icon(icon))
            if first:
                b.setObjectName("primary")
                first = False
            b.clicked.connect(lambda _=False, l=label: self._run(l))
            self.bar.addWidget(b)
        self.bar.addStretch()
        for label, icon, fn in (("Email", "mail", self._email),
                                ("PDF", "print", self._pdf)):
            b = QToolButton()
            b.setIcon(icons.icon(icon))
            b.setText(label)
            b.setToolTip(f"{label} this {self.t['one'].lower()}")
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setAutoRaise(True)
            b.clicked.connect(fn)
            self.bar.addWidget(b)
        more = QToolButton()
        more.setText("⋯")
        more.setAutoRaise(True)
        more.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(more)
        m.addAction("Duplicate", self._duplicate)
        m.addAction("Delete", self._delete)
        from .store import MONEY
        if self.key in MONEY:
            m.addAction("History…", self._history)
        more.setMenu(m)
        self.bar.addWidget(more)

    # ---------------------------------------------------------- saving
    def values(self):
        out = dict(self.current)
        tf = self.t.get("title_field", "title")
        if not self.title.isReadOnly():
            out[tf] = self.title.text().strip()
        for k, ed in self.editors.items():
            out[k] = ed.value()
        if self.key == "submittal":
            out["submit_by"] = schema.submit_by(out) or out.get("submit_by",
                                                               "")
        return out

    def _save(self):
        if self._loading or not self.current:
            return
        if not self.store.can_edit:
            self.saved_lbl.setText("View only - not saved")
            return
        vals = self.values()
        if self.key == "inspection" and vals.get("template") and \
                not vals.get("items"):
            from .templates import items_for
            vals["items"] = items_for(vals["template"])
            self.store.save_record(self.key, vals)
            self.load(self.store.get(self.key, vals["_id"]))
            self.saved.emit(self.current)
            return
        try:
            rec = self.store.save_record(self.key, vals)
        except StoreError as e:
            # a certified pay app is final (NW-07): say why, show it as it
            # is stored
            self.saved_lbl.setText("Not saved")
            QMessageBox.information(self, "Not saved", str(e))
            self.load(self.store.get(self.key, self.current["_id"]))
            return
        old_status = self.current.get("status")
        self.current = rec
        self._header()
        if rec.get("status") != old_status:
            self._actions()
        self.saved_lbl.setText("Saved")
        QTimer.singleShot(1500, lambda: self.saved_lbl.setText(""))
        self.saved.emit(rec)

    def _ctx(self):
        def ask_text(title, default=""):
            v, ok = QInputDialog.getText(self, title, title, text=default)
            return v if ok else None

        def open_file(path):
            main = live_main(self.center)
            if main is not None and path.lower().endswith(".pdf"):
                main.open_path(path)        # PDFs open here, in a tab
                return
            if os.environ.get("PYTEST_CURRENT_TEST"):
                return
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        def pick_file(title, filt=""):
            path, _ = QFileDialog.getOpenFileName(self, title, "",
                                                  filt or "All files (*)")
            return path or None

        def takeoff_doc():
            main = live_main(self.center)
            v = getattr(main, "_view", None) if main is not None else None
            return v.doc if v is not None else None

        def level(bids, title="", plugs=None, on_plugs=None):
            from ..leveling_ui import LevelingDialog
            dlg = LevelingDialog(self)
            dlg.setWindowTitle(f"Bid Leveling - {title}".strip(" -"))
            dlg.bids = bids
            dlg.plugs = [dict(p) for p in plugs or []]
            dlg.on_plugs = on_plugs
            dlg.project.addItem(f"{title}: {len(bids)} bidders", "files")
            dlg.project.setCurrentIndex(dlg.project.count() - 1)
            dlg.run()
            dlg.show()
            self._level_dlg = dlg
            return dlg
        return actions.Ctx(self.store, ask=self._ask,
                           notify=self.center.toast, ask_text=ask_text,
                           open_file=open_file, pick_file=pick_file,
                           takeoff_doc=takeoff_doc, level=level)

    def _ask(self, title, options):
        v, ok = QInputDialog.getItem(self, title, title, options, 0, False)
        return v if ok else None

    def _run(self, label):
        self._save()
        missing = [f["label"] for f in self.t["fields"]
                   if f["required"] and not self.current.get(f["key"])]
        if missing and label.startswith(("Send", "Close")):
            QMessageBox.information(self, label, "Fill in first: " +
                                    ", ".join(missing))
            return
        try:
            out = actions.run(self._ctx(), self.key, self.current, label)
        except Exception as e:
            log.exception("action failed")
            QMessageBox.warning(self, label, str(e))
            return
        if out is None:
            return
        if "_open" in out:
            self.open_other.emit(*out["_open"])
            return
        self.load(out)
        self.saved.emit(out)

    def _email(self):
        self._save()
        to, ok = QInputDialog.getText(
            self, "Email", "Send to (names from the Directory, lists or "
            "emails, separated by ;):",
            text=schema.ball_in_court(self.key, self.current) or "")
        if not ok or not to.strip():
            return
        try:
            self._ctx().send(self.key, self.current,
                             [t.strip() for t in to.split(";")])
        except Exception as e:
            QMessageBox.warning(self, "Email", str(e))

    def _pdf(self):
        self._save()
        tf = self.t.get("title_field", "title")
        # company rule, date first (app/reportname.py): record date,
        # project, record kind, number, then the record's title
        no = str(self.current.get("_no", "") or "")
        pre = self.t.get("prefix", "")
        if pre and no.startswith(pre):
            no = no[len(pre):]
        name = report_file_name(self.t.get("one") or self.t["title"],
                                self.store.name, no or None,
                                self.current.get("date"), ext="")
        title = clean(self.current.get(tf, "")) if tf != "date" else ""
        if title:
            name = f"{name} - {title}"[:150].rstrip()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF", os.path.join(self.store.folder,
                                           name + ".pdf"), "PDF (*.pdf)")
        if not path:
            return
        report.record_pdf(self.store, self.key, self.current, path)
        self.center.toast(f"Saved {os.path.basename(path)}")
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _duplicate(self):
        r = {k: v for k, v in self.current.items()
             if not k.startswith("_") and k not in ("thread", "status")}
        r.update({k: v for k, v in schema.defaults(self.key, self.store.me)
                  .items() if k == "status"})
        new = self.store.save_record(self.key, r)
        self.open_other.emit(self.key, new["_id"])

    def history_text(self, rid=None):
        """Who changed this money record, when, before and after (P1)."""
        rid = rid or (self.current or {}).get("_id")
        rows = self.store.audit_log(self.key, rid)
        if not rows:
            return "No changes recorded yet."
        out = []
        for e in rows:
            out.append(f"{e['ts'][:16].replace('T', ' ')}  {e['by']}  "
                       f"{e['action']}")
            for k in sorted(e["after"]):
                if k in ("lines", "thread", "certified_values"):
                    out.append(f"    {k}: changed")
                elif e["action"] == "change":
                    out.append(f"    {k}: {e['before'].get(k)} -> "
                               f"{e['after'][k]}")
                else:
                    out.append(f"    {k}: {e['after'][k]}")
        if not self.store.audit_ok():
            out.insert(0, "WARNING: the history was edited outside "
                          "QuantiSheet.\n")
        return "\n".join(out)

    def _history(self):
        from PySide6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout
        d = QDialog(self)
        d.setWindowTitle(f"History - {(self.current or {}).get('_no', '')}")
        lay = QVBoxLayout(d)
        t = QPlainTextEdit(self.history_text())
        t.setReadOnly(True)
        lay.addWidget(t)
        d.resize(640, 420)
        d.exec()

    def _delete(self):
        if QMessageBox.question(
                self, "Delete", f"Delete {self.current.get('_no')}? Everyone"
                " on the project will stop seeing it.") != QMessageBox.Yes:
            return
        try:
            self.store.delete(self.key, self.current["_id"])
        except StoreError as e:
            QMessageBox.information(self, "Not deleted", str(e))
            return
        self.current = {}
        self.saved.emit({})


# ================================================================ create
def _words_of(v, out):
    """Every piece of text in a record value: lists and tables (manpower,
    delays, visitors), weather, attachments (their file names)."""
    if isinstance(v, dict):
        for k, x in v.items():
            if k in ("data", "sha256", "hash", "blob", "path") and \
                    isinstance(x, str) and len(x) > 80:
                continue                # file contents / hashes
            if k == "path" and isinstance(x, str):
                out.append(os.path.basename(x))
                continue
            _words_of(x, out)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _words_of(x, out)
    elif v not in (None, ""):
        out.append(str(v))


def search_records(recs, q):
    """Records matching every word of `q`, best first (PM review NW-12:
    search skipped manpower, weather, delays, visitors and photo names,
    and 'Rain' found 'drainage'). A word must start a word in the record
    ('rain' finds 'Rain' and 'rainy', not 'drainage'); a record where a
    word only appears inside another word still matches, ranked last."""
    import re
    words = [w for w in q.lower().split() if w]
    if not words:
        return list(recs)
    starts = [re.compile(r"(?<![a-z0-9])" + re.escape(w)) for w in words]
    scored = []
    for i, r in enumerate(recs):
        out = [r.get("_no", "")]
        for k, v in r.items():
            if not k.startswith("_"):
                _words_of(v, out)
        hay = " ".join(out).lower()
        if not all(w in hay for w in words):
            continue
        whole = sum(1 for rx in starts if rx.search(hay))
        scored.append((-whole, i, r))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [r for _s, _i, r in scored]


class CreateDialog(QDialog):
    """New item: just the fields that matter, sensible defaults."""

    def __init__(self, center, key, preset=None):
        super().__init__(center)
        self.center = center
        self.store = center.store
        self.key = key
        self.t = schema.TOOLS[key]
        self.setWindowTitle(f"New {self.t['one']}")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        head = QLabel(f"New {self.t['one']}")
        head.setObjectName("pcDialogTitle")
        v.addWidget(head)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        v.addLayout(self.form)
        self.rec = schema.defaults(key, self.store.me)
        self.rec.update(preset or {})
        self.current = self.rec
        self.editors = {}
        for f in self.t["fields"]:
            if not f["quick"]:
                continue
            ed = editor_for(f, self.store, self)
            ed.set_value(self.rec.get(f["key"]))
            self.editors[f["key"]] = ed
            self.form.addRow(f["label"] + (" *" if f["required"] else ""),
                             ed)
        hint = QLabel("Everything else can be added after it's created.")
        hint.setObjectName("muted")
        v.addWidget(hint)
        bb = QDialogButtonBox()
        self.send_label = None
        acts = actions.ACTIONS.get(key, [])
        if acts and acts[0][0].startswith("Send"):
            self.send_label = acts[0][0]
            b = bb.addButton(f"Create and {acts[0][0].split()[0]}",
                             QDialogButtonBox.AcceptRole)
            b.clicked.connect(lambda: self._done(True))
        create = bb.addButton("Create", QDialogButtonBox.AcceptRole)
        create.setObjectName("primary")
        create.setDefault(True)
        create.clicked.connect(lambda: self._done(False))
        bb.addButton(QDialogButtonBox.Cancel).clicked.connect(self.reject)
        v.addWidget(bb)
        self.result_rec = None

    def _done(self, send):
        vals = dict(self.rec)
        for k, ed in self.editors.items():
            vals[k] = ed.value()
        missing = [f["label"] for f in self.t["fields"]
                   if f["required"] and f["quick"] and not vals.get(f["key"])]
        if missing:
            QMessageBox.information(self, "Almost there",
                                    "Please fill in: " + ", ".join(missing))
            return
        if self.key == "submittal":
            vals["submit_by"] = schema.submit_by(vals)
        if self.key == "inspection" and vals.get("template"):
            from .templates import items_for
            vals["items"] = items_for(vals["template"])
        if send and self.key == "rfi":
            vals["status"] = "Draft"
        rec = self.store.save_record(self.key, vals)
        if send and self.send_label:
            try:
                rec = actions.run(actions.Ctx(self.store,
                                              notify=self.center.toast),
                                  self.key, rec, self.send_label) or rec
            except Exception as e:
                QMessageBox.warning(self, "Send", str(e))
        self.result_rec = rec
        self.accept()


# ================================================================ pages
class ToolPage(QWidget):
    def packages_from_trades(self, picks=None):
        """Bid packages for several trades at once (one per trade)."""
        from .bidui import TradesDialog, make_packages
        if picks is None:
            dlg = TradesDialog(self)
            if not dlg.exec():
                return []
            picks = dlg.chosen()
        made = make_packages(self.store, picks)
        self.refresh()
        self.center.toast(f"Made {len(made)} bid package(s).")
        return made

    def from_spec_book(self, path=None, accept=None):
        """The submittal register from the spec book: pick the project
        manual, tick the ones to add. accept(proposals) -> chosen (tests)."""
        from . import submittals
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Spec Book (Project Manual)", self.store.folder,
                "PDF (*.pdf)")
        if not path:
            return []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            props = submittals.from_spec_book(path)
        except Exception as e:                            # noqa: BLE001
            err = e
            props = None
        else:
            err = None
        finally:
            QApplication.restoreOverrideCursor()
        if err is not None:
            QMessageBox.warning(self, "From Spec Book", f"Couldn't read "
                                f"{os.path.basename(path)}: {err}")
            return []
        if not props:
            QMessageBox.information(
                self, "From Spec Book", "No submittal articles found. The "
                "book needs text (not scanned pages), with sections headed "
                "\"SECTION 08 71 00\" and a PART 1 article named like "
                "\"1.4 ACTION SUBMITTALS\".")
            return []
        chosen = accept(props) if accept else self._pick_proposals(props)
        if not chosen:
            return []
        try:                          # Nov 3: link the open drawing set
            main = live_main(self.center)
            v = getattr(main, "_view", None) if main is not None else None
            submittals.link_sheets(chosen, v.doc if v is not None else None)
        except Exception:                                 # noqa: BLE001
            log.warning("drawing sheets not linked", exc_info=True)
        made = submittals.import_register(self.store, chosen)
        self.refresh()
        self.center.toast(f"Added {len(made)} submittal(s) from "
                          f"{len({p['spec'] for p in chosen})} section(s).")
        return made

    def look_ahead(self, weeks=None, path=None):
        """The submittal look-ahead as a PDF (or Excel by extension)."""
        from . import lookahead
        if weeks is None:
            w, ok = QInputDialog.getItem(
                self, "Submittal Look-Ahead", "Weeks ahead:",
                ["2 weeks", "3 weeks", "4 weeks"], 2, False)
            if not ok:
                return None
            weeks = int(w.split()[0])
        if path is None:
            name = report_file_name("Submittal Look-Ahead",
                                    self.store.name)
            path, _ = QFileDialog.getSaveFileName(
                self, "Submittal Look-Ahead",
                os.path.join(self.store.folder, name),
                "PDF (*.pdf);;Excel (*.xlsx)")
        if not path:
            return None
        lookahead.export(self.store, path, weeks)
        self.center.toast(f"Saved {os.path.basename(path)}.")
        return path

    def _pick_proposals(self, props):
        d = QDialog(self)
        d.setWindowTitle("Submittals from the Spec Book")
        d.resize(820, 600)
        v = QVBoxLayout(d)
        v.addWidget(QLabel(f"{len(props)} submittals found in "
                           f"{len({p['spec'] for p in props})} sections. "
                           "Untick any you don't want."))
        lw = QListWidget()
        for p in props:
            it = QListWidgetItem(f"{p['spec']}   {p['title']}   "
                                 f"[{p['type']}]   p.{p['page']}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setToolTip(p.get("description", ""))
            lw.addItem(it)
        v.addWidget(lw, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add to the Log")
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        if not d.exec():
            return []
        return [p for i, p in enumerate(props)
                if lw.item(i).checkState() == Qt.Checked]

    def bidding_reports(self, path=None):
        from . import bidreports
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Bidding Reports", os.path.join(
                    self.store.folder,
                    report_file_name("Bidding Reports", self.store.name,
                                     ext=".xlsx")),
                "Excel (*.xlsx)")
        if not path:
            return None
        bidreports.export_xlsx(self.store, path)
        self.center.toast(f"Saved {os.path.basename(path)}.")
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception:
            pass
        return path

    def __init__(self, center, key):
        super().__init__()
        self.center = center
        self.store = center.store
        self.key = key
        self.t = schema.TOOLS[key]
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top = QFrame()
        top.setObjectName("pcPageHead")
        tv = QVBoxLayout(top)
        tv.setContentsMargins(18, 14, 18, 8)
        r1 = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.icon(self.t.get("icon", "list")).pixmap(22, 22))
        r1.addWidget(ic)
        self.h = QLabel(self.t["title"])
        self.h.setObjectName("pcH1")
        r1.addWidget(self.h)
        self.count = QLabel()
        self.count.setObjectName("muted")
        r1.addWidget(self.count)
        r1.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Search {self.t['title'].lower()}")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self.refresh)
        r1.addWidget(self.search)
        exp = QToolButton()
        exp.setIcon(icons.icon("export"))
        exp.setToolTip("Export the list")
        exp.setAutoRaise(True)
        exp.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(exp)
        m.addAction("Log as PDF…", lambda: self._export("pdf"))
        m.addAction("Log as Excel…", lambda: self._export("xlsx"))
        exp.setMenu(m)
        r1.addWidget(exp)
        if key == "submittal":
            fs = QPushButton("From Spec Book…")
            fs.setIcon(icons.icon("book"))
            fs.setToolTip("Read the project manual's SUBMITTALS articles "
                          "and add the submittals it asks for")
            fs.clicked.connect(lambda: self.from_spec_book())
            r1.addWidget(fs)
            la = QPushButton("Look-Ahead…")
            la.setIcon(icons.icon("calendar"))
            la.setToolTip("Open submittals due in the next few weeks, and "
                          "the late ones - PDF or Excel")
            la.clicked.connect(lambda: self.look_ahead())
            r1.addWidget(la)
        if key == "bidpkg":
            many = QPushButton("Packages from Trades…")
            many.setIcon(icons.icon("bidtabs"))
            many.setToolTip("Make one bid package per trade in one go")
            many.clicked.connect(lambda _c=False: self.packages_from_trades())
            r1.addWidget(many)
            rep = QPushButton("Bidding Reports…")
            rep.setIcon(icons.icon("print"))
            rep.setToolTip("Package status, bidder coverage, buyout against "
                           "the budget and bidder history - in Excel")
            rep.clicked.connect(lambda: self.bidding_reports())
            r1.addWidget(rep)
        new = QPushButton(f"New {self.t['one']}")
        new.setObjectName("primary")
        new.setIcon(icons.icon("new"))
        new.clicked.connect(lambda _c=False: self.new())
        r1.addWidget(new)
        tv.addLayout(r1)
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        self.chips = QButtonGroup(self)
        self.chips.setExclusive(True)
        names = ["Open", "Mine", "Overdue", "Closed", "All"] if \
            self.t.get("statuses") else ["All"]
        first = schema.default_chip(self.key)
        for i, name in enumerate(names):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setObjectName("chip")
            b.setChecked(name == first)
            self.chips.addButton(b, i)
            r2.addWidget(b)
        self.chips.buttonClicked.connect(lambda _b: self.refresh())
        if self.t.get("statuses"):
            self.status = QComboBox()
            self.status.addItems(["Any status"] + self.t["statuses"])
            self.status.currentIndexChanged.connect(lambda _i:
                                                    self.refresh())
            r2.addWidget(self.status)
        else:
            self.status = None
        r2.addStretch()
        tv.addLayout(r2)
        v.addWidget(top)
        self.split = QSplitter(Qt.Horizontal)
        left = QStackedWidget()
        self.table = QTableView()
        self.table.setObjectName("pcList")
        self.model = RecordModel(self.store, key)
        self.proxy = _Proxy()
        self.proxy.setSourceModel(self.model)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder if self.t.get("sort")
                                else Qt.DescendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setStretchLastSection(True)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        if "status" in self.model.cols:
            self.table.setItemDelegateForColumn(
                self.model.cols.index("status"), StatusDelegate(self.table))
        self.table.selectionModel().currentRowChanged.connect(self._pick)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        left.addWidget(self.table)
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.addStretch()
        ei = QLabel()
        ei.setPixmap(icons.icon(self.t.get("icon", "list")).pixmap(48, 48))
        ei.setAlignment(Qt.AlignCenter)
        ev.addWidget(ei)
        self.empty_text = QLabel()
        self.empty_text.setAlignment(Qt.AlignCenter)
        self.empty_text.setObjectName("muted")
        self.empty_text.setWordWrap(True)
        ev.addWidget(self.empty_text)
        eb = QPushButton(f"New {self.t['one']}")
        eb.setObjectName("primary")
        eb.clicked.connect(lambda _c=False: self.new())
        eh = QHBoxLayout()
        eh.addStretch()
        eh.addWidget(eb)
        eh.addStretch()
        ev.addLayout(eh)
        ev.addStretch()
        left.addWidget(self.empty)
        self.left = left
        self.split.addWidget(left)
        self.right = QStackedWidget()
        hint = QLabel("Select an item to see it here.")
        hint.setAlignment(Qt.AlignCenter)
        hint.setObjectName("muted")
        self.right.addWidget(hint)
        self.form = RecordForm(center, key)
        self.form.saved.connect(self._saved)
        self.form.open_other.connect(center.open_record)
        self.right.addWidget(self.form)
        self.split.addWidget(self.right)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        self.split.setSizes([620, 520])
        v.addWidget(self.split, 1)
        self._sized = False
        self.refresh()

    def _filtered(self):
        recs = self.store.list(self.key)
        chip = self.chips.checkedButton().text() if \
            self.chips.checkedButton() else "All"
        if chip == "Open":
            recs = [r for r in recs if not schema.is_closed(self.key, r)]
        elif chip == "Closed":
            recs = [r for r in recs if schema.is_closed(self.key, r)]
        elif chip == "Mine":
            recs = [r for r in recs if not schema.is_closed(self.key, r)
                    and (is_me(self.store,
                               schema.ball_in_court(self.key, r)) or
                         is_me(self.store, r.get("_by")))]
        elif chip == "Overdue":
            recs = [r for r in recs if schema.is_overdue(self.key, r)]
        if self.status is not None and self.status.currentIndex() > 0:
            recs = [r for r in recs
                    if r.get("status") == self.status.currentText()]
        q = self.search.text().strip()
        if q:
            recs = search_records(recs, q)
        return recs

    def refresh(self, *_):
        cur = self.form.current.get("_id") if self.form.current else None
        recs = self._filtered()
        self.model.set_records(recs)
        total = len(self.store.list(self.key))
        self.count.setText(f"{len(recs)} of {total}" if len(recs) != total
                           else f"{total}")
        if not recs:
            self.empty_text.setText(
                f"No {self.t['title'].lower()} yet." if not total else
                "Nothing matches these filters.")
            self.left.setCurrentWidget(self.empty)
        else:
            self.left.setCurrentWidget(self.table)
            if not self._sized:
                self.table.resizeColumnsToContents()
                for c in range(self.model.columnCount()):
                    w = self.table.columnWidth(c)
                    self.table.setColumnWidth(c, max(70, min(w + 16, 320)))
                self._sized = True
        if cur:
            self.select(cur, quiet=True)

    def select(self, rid, quiet=False):
        for row in range(self.proxy.rowCount()):
            idx = self.proxy.index(row, 0)
            if idx.data(Qt.UserRole) == rid:
                self.table.selectionModel().blockSignals(quiet)
                self.table.selectRow(row)
                self.table.selectionModel().blockSignals(False)
                self.table.scrollTo(idx)
                if not quiet:
                    self._pick(idx)
                return True
        rec = self.store.get(self.key, rid)
        if rec and not quiet:              # filtered out: show it anyway
            self.form.load(rec)
            self.right.setCurrentWidget(self.form)
        return False

    def _pick(self, idx, _prev=None):
        if not idx.isValid():
            return
        rid = self.proxy.index(idx.row(), 0).data(Qt.UserRole)
        rec = self.store.get(self.key, rid)
        if rec:
            self.form.load(rec)
            self.right.setCurrentWidget(self.form)

    def _saved(self, rec):
        if not rec:
            self.right.setCurrentIndex(0)
        self.refresh()
        self.center.home_dirty = True

    def new(self, preset=None):
        d = CreateDialog(self.center, self.key, preset)
        if d.exec() and d.result_rec:
            self.chips.button(len(self.chips.buttons()) - 1).setChecked(
                True)
            self.search.clear()
            self.refresh()
            self.select(d.result_rec["_id"])

    def _menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        self._pick(idx)
        m = QMenu(self)
        m.addAction("Email…", self.form._email)
        m.addAction("Save as PDF…", self.form._pdf)
        m.addAction("Duplicate", self.form._duplicate)
        m.addSeparator()
        m.addAction("Delete", self.form._delete)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _export(self, kind):
        recs = [self.model.recs[self.proxy.mapToSource(
            self.proxy.index(r, 0)).row()] for r in
            range(self.proxy.rowCount())]
        name = report_file_name(self.t["title"], self.store.name,
                                ext=f".{kind}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", os.path.join(self.store.folder, name),
            "PDF (*.pdf)" if kind == "pdf" else "Excel (*.xlsx)")
        if not path:
            return
        if kind == "pdf":
            report.list_pdf(self.store, self.key, recs, path)
        else:
            report.list_xlsx(self.store, self.key, recs, path)
        self.center.toast(f"Exported {len(recs)} item(s) to "
                          f"{os.path.basename(path)}")


class HomePage(QWidget):
    """What's waiting on me, what's overdue, what changed."""

    def __init__(self, center):
        super().__init__()
        self.center = center
        self.store = center.store
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        outer.addWidget(sc)
        self.inner = QWidget()
        sc.setWidget(self.inner)
        self.v = QVBoxLayout(self.inner)
        self.v.setContentsMargins(26, 22, 26, 22)
        self.v.setSpacing(14)

    def refresh(self):
        while self.v.count():
            it = self.v.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
            elif it.layout():
                _clear(it.layout())
        hour = datetime.now().hour
        hi = "Good morning" if hour < 12 else "Good afternoon" \
            if hour < 18 else "Good evening"
        h = QLabel(f"{hi}, {html.escape(self.store.me.split()[0] if self.store.me else '')}")
        h.setObjectName("pcHello")
        self.v.addWidget(h)
        sub = QLabel(f"{self.store.name}  ·  "
                     f"{datetime.now():%A, %B} {datetime.now().day}")
        sub.setObjectName("muted")
        self.v.addWidget(sub)
        mine, overdue, recent = [], [], []
        for key, t in schema.TOOLS.items():
            if not t.get("statuses"):
                continue
            for r in self.store.list(key):
                if schema.is_closed(key, r):
                    continue
                if is_me(self.store, schema.ball_in_court(key, r)):
                    mine.append((key, r))
                if schema.is_overdue(key, r):
                    overdue.append((key, r))
        for key in schema.TOOLS:
            for r in self.store.list(key):
                recent.append((key, r))
        recent.sort(key=lambda kr: kr[1].get("_updated") or "",
                    reverse=True)
        cards = QHBoxLayout()
        cards.setSpacing(12)

        def card(n, label, key=None, chip=None, warn=False):
            f = _Card(lambda: self.center.show_tool(key, chip)
                      if key else None)
            col = (theme.color("danger") if warn and n else
                   theme.color("text")).name()
            lay = QVBoxLayout(f)
            lay.setContentsMargins(14, 10, 14, 10)
            a = QLabel(str(n))
            fnt = a.font()
            fnt.setPointSizeF(fnt.pointSizeF() * 2.1)
            fnt.setBold(True)
            a.setFont(fnt)
            a.setStyleSheet(f"color:{col}")
            b = QLabel(label)
            b.setObjectName("muted")
            lay.addWidget(a)
            lay.addWidget(b)
            cards.addWidget(f)
        card(len(mine), "Waiting on you")
        card(len(overdue), "Overdue", warn=True)
        # delay notices the owner contract requires (P1 deadline tracker)
        try:
            from . import contract_terms as _ct
            urgent = [x for x in _ct.notice_list(self.store)
                      if x["status"] == "OVERDUE" or
                      (x["status"].startswith("Due in") and
                       int(x["status"].split()[2]) <= 3)]
        except Exception:                                 # noqa: BLE001
            urgent = []
        card(len(urgent), "Delay notices due", "delay", warn=True)
        card(sum(1 for r in self.store.list("rfi")
                 if r.get("status") == "Open"), "Open RFIs", "rfi", "Open")
        card(sum(1 for r in self.store.list("submittal")
                 if r.get("status") == "In Review"), "Submittals in review",
             "submittal", "Open")
        card(sum(1 for r in self.store.list("punch")
                 if not schema.is_closed("punch", r)), "Open punch items",
             "punch", "Open")
        self.v.addLayout(cards)
        self._list("Waiting on you", mine,
                   "Nothing is waiting on you. Nice.")
        self._list("Overdue", overdue, "Nothing overdue.")
        self._list("Recent changes", recent[:12], "No activity yet.",
                   show_who=True)
        if not any(self.store.list(k) for k in schema.TOOLS):
            tip = QLabel("Start by adding your team in <b>Directory</b>, "
                         "then create RFIs, submittals and punch items. "
                         "Use <b>Share</b> at the top to work on this "
                         "project with others and from phones.")
            tip.setWordWrap(True)
            self.v.addWidget(tip)
        self.v.addStretch()

    def _list(self, title, items, empty, show_who=False):
        h = QLabel(title)
        h.setObjectName("pcH2")
        self.v.addWidget(h)
        if not items:
            e = QLabel(empty)
            e.setObjectName("muted")
            self.v.addWidget(e)
            return
        lw = QListWidget()
        lw.setObjectName("pcHomeList")
        items = sorted(items, key=lambda kr: kr[1].get("due") or "9999") \
            if not show_who else items
        for key, r in items[:25]:
            t = schema.TOOLS[key]
            tf = t.get("title_field", "title")
            due = r.get("due") or r.get("submit_by") or ""
            extra = (f"  ·  {r.get('_upd_by', '')} "
                     f"{(r.get('_updated') or '')[:10]}") if show_who else \
                (f"  ·  due {show_date(due)}" if due else "")
            title_txt = report.fmt(schema.field(key, tf), r.get(tf),
                                   self.store)
            st = f"   [{r['status']}]" if r.get("status") else ""
            it = QListWidgetItem(icons.icon(t.get("icon", "list")),
                                 f"{r.get('_no', '')}   {title_txt}{st}"
                                 f"{extra}")
            it.setData(Qt.UserRole, (key, r["_id"]))
            lw.addItem(it)
        lw.setFixedHeight(min(10, len(items)) * 30 + 6)
        lw.itemClicked.connect(
            lambda it: self.center.open_record(*it.data(Qt.UserRole)))
        self.v.addWidget(lw)


class _Card(QFrame):
    def __init__(self, on_click=None):
        super().__init__()
        self.setObjectName("pcCard")
        self.on_click = on_click
        if on_click:
            self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if self.on_click and e.button() == Qt.LeftButton:
            self.on_click()


def _clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear(it.layout())


# ================================================================ jump
class JumpDialog(QDialog):
    """Ctrl+K: type 'rfi 12', a title word or a person."""

    def __init__(self, center):
        super().__init__(center, Qt.Popup)
        self.center = center
        self.setMinimumWidth(620)
        v = QVBoxLayout(self)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Go to an item, e.g. RFI 12, P-0031, "
                                  "door hardware")
        self.q.textChanged.connect(self._fill)
        self.q.returnPressed.connect(self._go)
        v.addWidget(self.q)
        self.list = QListWidget()
        self.list.itemActivated.connect(self._go)
        v.addWidget(self.list)
        self.items = []
        for key, t in schema.TOOLS.items():
            tf = t.get("title_field", "title")
            for r in center.store.list(key):
                label = report.fmt(schema.field(key, tf), r.get(tf),
                                   center.store)
                self.items.append((key, r, f"{t['one']} {r.get('_no', '')} "
                                           f"{label}"))
        self._fill("")

    def _fill(self, text):
        import re
        q = text.lower().strip()
        nums = re.findall(r"\d+", q)
        out = []
        for key, r, label in self.items:
            hay = (label + " " + r.get("_no", "") + " " +
                   str(r.get("status", "")) + " " + key).lower()
            if q and not all(w in hay or (w.isdigit() and
                                          str(r.get("_n")) == w)
                             for w in q.split()):
                continue
            score = 0 if nums and str(r.get("_n")) in nums else 1
            out.append((score, label, key, r))
        out.sort(key=lambda x: (x[0], x[1]))
        self.list.clear()
        for _s, label, key, r in out[:40]:
            it = QListWidgetItem(icons.icon(schema.TOOLS[key].get("icon",
                                                                  "list")),
                                 f"{label}   [{r.get('status', '')}]")
            it.setData(Qt.UserRole, (key, r["_id"]))
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up):
            self.list.keyPressEvent(e)
            return
        super().keyPressEvent(e)

    def _go(self, *_):
        it = self.list.currentItem()
        if it:
            self.accept()
            self.center.open_record(*it.data(Qt.UserRole))


# ================================================================ sync
class _Syncer(QObject):
    done = Signal(object)


class ShareDialog(QDialog):
    def __init__(self, center):
        super().__init__(center)
        self.setWindowTitle("Share this project")
        self.store = center.store
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "Share the project through your QuantiSheet relay. Everyone "
            "who opens it with the same name and password sees the same "
            "RFIs, submittals, punch items and logs, and phones can join "
            "at the relay's /project.html page."))
        f = QFormLayout()
        from ..collab.hubclient import default_token, default_url
        self.url = QLineEdit(default_url())
        self.token = QLineEdit(default_token())
        self.token.setEchoMode(QLineEdit.Password)
        self.name = QLineEdit(self.store.name)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("the first person to share sets it")
        self.email = QLineEdit(settings.get("hub_email") or "")
        self.email.setPlaceholderText("only if the project uses logins")
        f.addRow("Relay address", self.url)
        f.addRow("Relay token", self.token)
        f.addRow("Project name", self.name)
        f.addRow("Your email", self.email)
        f.addRow("Password", self.pw)
        v.addLayout(f)
        self.msg = QLabel()
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        bb = QDialogButtonBox()
        go = bb.addButton("Share", QDialogButtonBox.AcceptRole)
        go.setObjectName("primary")
        go.clicked.connect(self._go)
        bb.addButton(QDialogButtonBox.Cancel).clicked.connect(self.reject)
        v.addWidget(bb)

    def _go(self):
        try:
            r = self.store.connect(self.url.text().strip(),
                                   self.name.text().strip(), self.pw.text(),
                                   token=self.token.text().strip(),
                                   email=self.email.text().strip() or None)
        except Exception as e:
            self.msg.setText(f"<span style='color:{theme.color('danger').name()}'>"
                             f"{html.escape(str(e))}</span>")
            return
        settings.set("hub_url", self.url.text().strip())
        settings.set("hub_token", self.token.text().strip())
        settings.set("hub_email", self.email.text().strip())
        QMessageBox.information(
            self, "Shared", f"Project shared. Sent {r.get('sent', 0)}, "
            f"received {r.get('received', 0)} item(s).")
        self.accept()


# ================================================================ window
class ProjectCenter(QMainWindow):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.main = None
        self.setWindowTitle(f"Project Center - {store.name}")
        self.setWindowIcon(icons.icon("home"))
        self.resize(1400, 860)
        self.home_dirty = True
        root = QWidget()
        root.setObjectName("pcRoot")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._topbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("pcNav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setFixedWidth(214)
        self.nav.currentItemChanged.connect(self._nav)
        body.addWidget(self.nav)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        v.addLayout(body, 1)
        self.toast_lbl = QLabel(self)
        self.toast_lbl.setObjectName("pcToast")
        self.toast_lbl.hide()
        self.pages = {}
        self.home = HomePage(self)
        self.stack.addWidget(self.home)
        self._fill_nav()
        self.nav.setCurrentRow(0)
        QShortcut(QKeySequence("Ctrl+K"), self, self.jump)
        QShortcut(QKeySequence("Ctrl+N"), self, self.new_item)
        QShortcut(QKeySequence("F5"), self, self.sync_now)
        self._syncer = _Syncer()
        self._syncer.done.connect(self._synced)
        self._busy = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.sync_now)
        self.timer.start(60_000)
        self.store.listeners.append(self._store_changed)
        self._restyle()
        theme.hub.changed.connect(self._restyle)
        self._update_sync()
        if self.store.connected:
            QTimer.singleShot(300, self.sync_now)
        if getattr(self.store, "damaged", ""):
            # the project file couldn't be read: say so (review 3 #35)
            QTimer.singleShot(0, lambda: self.toast(
                "This project's database was damaged and was set aside as "
                f"{os.path.basename(self.store.damaged)}; "
                "the project has started empty. "
                + ("Syncing will bring the shared records back."
                   if self.store.connected else
                   "Restore it from a backup if you have one.")))

    def closeEvent(self, e):
        try:
            self.store.listeners.remove(self._store_changed)
            theme.hub.changed.disconnect(self._restyle)
        except (ValueError, RuntimeError):
            pass
        self.timer.stop()
        # let a sync that is under way finish writing, then save (3b C13)
        t = getattr(self, "_sync_thread", None)
        if t is not None and t.is_alive():
            t.join(timeout=10)
        try:
            self.store.flush()
        except Exception:
            log.warning("saving the project failed", exc_info=True)
        super().closeEvent(e)

    # ---------------------------------------------------------- chrome
    def _topbar(self):
        bar = QFrame()
        bar.setObjectName("pcTop")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 8, 12, 8)
        logo = QLabel()
        logo.setPixmap(icons.icon("home").pixmap(20, 20))
        h.addWidget(logo)
        self.proj_btn = QToolButton()
        self.proj_btn.setObjectName("pcProject")
        self.proj_btn.setText(self.store.name)
        self.proj_btn.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(self.proj_btn)
        m.addAction("Open another project…", self.switch_project)
        m.addAction("New project…", self.new_project)
        m.addSeparator()
        m.addAction("Project settings…", self.project_settings)
        m.addAction("Owner contract terms…", self.prime_terms)
        m.addAction("Check subcontract terms…", self.check_terms)
        m.addAction("Photos…", self.photo_library)
        m.addAction("Allowances…", self.allowances)
        m.addSeparator()
        m.addAction("Back Up This Job…", self.backup_job)
        m.addAction("Restore a Job Backup…", self.restore_job)
        m.addAction("Users and roles…", self.manage_users)
        self.proj_btn.setMenu(m)
        h.addWidget(self.proj_btn)
        h.addSpacing(10)
        jump = QPushButton("  Go to item…        Ctrl+K")
        jump.setObjectName("pcJump")
        jump.setIcon(icons.icon("find"))
        jump.clicked.connect(self.jump)
        h.addWidget(jump, 1)
        h.addSpacing(10)
        self.sync_btn = QPushButton()
        self.sync_btn.setObjectName("pcSync")
        self.sync_btn.setIcon(icons.icon("sync"))
        self.sync_btn.clicked.connect(self._sync_clicked)
        h.addWidget(self.sync_btn)
        self.share_btn = QPushButton("Share")
        self.share_btn.setIcon(icons.icon("people"))
        self.share_btn.clicked.connect(self.share)
        h.addWidget(self.share_btn)
        # it opens full screen: a Close button, not only the title bar's X
        # (Chief's estimator test, Nov 7)
        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("pcClose")
        self.close_btn.setToolTip("Close Project Center (Ctrl+W)")
        self.close_btn.clicked.connect(self.close)
        h.addWidget(self.close_btn)
        QShortcut(QKeySequence("Ctrl+W"), self, self.close)
        return bar

    def _fill_nav(self):
        self.nav.clear()
        it = QListWidgetItem(icons.icon("home"), "Home")
        it.setData(Qt.UserRole, "home")
        self.nav.addItem(it)
        by_group = dict(schema.groups())
        for group in GROUP_ORDER:
            tools = by_group.get(group, [])
            specials = SPECIAL_NAV.get(group, [])
            if not tools and not specials:
                continue
            hdr = QListWidgetItem(group.upper())
            hdr.setFlags(Qt.NoItemFlags)
            hdr.setSizeHint(QSize(180, 34))
            hdr.setTextAlignment(Qt.AlignLeft | Qt.AlignBottom)
            hdr.setData(Qt.UserRole, None)
            f = hdr.font()
            f.setPointSizeF(f.pointSizeF() * 0.78)
            f.setBold(True)
            hdr.setFont(f)
            hdr.setForeground(QColor(theme.color("faint")))
            self.nav.addItem(hdr)
            for key, title, icon in specials:
                it = QListWidgetItem(icons.icon(icon), title)
                it.setData(Qt.UserRole, key)
                self.nav.addItem(it)
            for t in tools:
                n = schema.nav_count(t["key"], self.store.list(t["key"]))
                it = QListWidgetItem(icons.icon(t.get("icon", "list")),
                                     t["title"] + (f"   {n}" if n else ""))
                it.setData(Qt.UserRole, t["key"])
                self.nav.addItem(it)

    def _nav_counts(self):
        for i in range(self.nav.count()):
            it = self.nav.item(i)
            key = it.data(Qt.UserRole)
            if key in schema.TOOLS:
                t = schema.TOOLS[key]
                n = schema.nav_count(key, self.store.list(key))
                it.setText(t["title"] + (f"   {n}" if n else ""))

    def _nav(self, cur, _prev=None):
        if cur is None:
            return
        key = cur.data(Qt.UserRole)
        if key == "home":
            if self.home_dirty:
                self.home.refresh()
                self.home_dirty = False
            self.stack.setCurrentWidget(self.home)
        elif key in schema.TOOLS or key in SPECIAL:
            p = self.page(key)
            if key in SPECIAL:
                p.refresh()
            self.stack.setCurrentWidget(p)

    def page(self, key):
        if key not in self.pages:
            if key in SPECIAL:
                import importlib
                mod, cls = SPECIAL[key]
                p = getattr(importlib.import_module(f".{mod}",
                                                    __package__), cls)(self)
                self.pages[key] = p
                self.stack.addWidget(p)
                return p
            p = ToolPage(self, key)
            self.pages[key] = p
            self.stack.addWidget(p)
        return self.pages[key]

    def show_tool(self, key, chip=None):
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) == key:
                self.nav.setCurrentRow(i)
                break
        p = self.page(key)
        if key in SPECIAL:
            p.refresh()
            return p
        if chip:
            for b in p.chips.buttons():
                if b.text() == chip:
                    b.setChecked(True)
            p.refresh()
        return p

    def open_record(self, key, rid):
        p = self.show_tool(key)
        p.select(rid)

    def new_item(self):
        w = self.stack.currentWidget()
        if isinstance(w, ToolPage):
            w.new()
        else:
            self.show_tool("rfi").new()

    def jump(self):
        d = JumpDialog(self)
        g = self.geometry()
        d.move(g.x() + (g.width() - 620) // 2, g.y() + 80)
        d.q.setFocus()
        d.exec()

    def toast(self, text):
        self.toast_lbl.setText(text)
        self.toast_lbl.adjustSize()
        self.toast_lbl.setFixedWidth(min(self.toast_lbl.sizeHint().width()
                                         + 24, 640))
        self.toast_lbl.move((self.width() - self.toast_lbl.width()) // 2,
                            self.height() - 70)
        self.toast_lbl.show()
        self.toast_lbl.raise_()
        QTimer.singleShot(4500, self.toast_lbl.hide)

    def _store_changed(self, coll):
        self.home_dirty = True
        cur = self.stack.currentWidget()
        if cur is not None and cur in [self.pages.get(k) for k in SPECIAL] \
                and coll != "budget":
            cur.refresh()
        self._nav_counts()
        self._update_sync()

    # ---------------------------------------------------------- sync
    def _update_sync(self):
        s = self.store
        if not s.connected:
            self.sync_btn.setText("On this PC only")
            self.sync_btn.setToolTip("Click Share to work on this project "
                                     "with others")
            self.share_btn.setVisible(True)
            return
        self.share_btn.setVisible(False)
        n = s.pending_count()
        if self._busy:
            txt = "Syncing…"
        elif s.last_error:
            txt = "Offline" + (f" · {n} to send" if n else "")
        elif n:
            txt = f"{n} change(s) to send"
        else:
            txt = f"Synced {_ago(s.last_sync)}"
        h = s.data.get("hub") or {}
        if h.get("logins"):
            from ..collab.hub import ROLE_NAMES
            txt += f" · {h.get('user') or h.get('email')} " \
                   f"({ROLE_NAMES.get(s.role, s.role)})"
        self.sync_btn.setText(txt)
        self.sync_btn.setToolTip(s.last_error or s.last_denied or
                                 "Click to sync now (F5)")

    def _sync_clicked(self):
        if not self.store.connected:
            self.share()
        else:
            self.sync_now()

    def sync_now(self):
        if not self.store.connected or self._busy:
            self._update_sync()
            return
        self._busy = True
        self._update_sync()

        def work():
            try:
                res = self.store.sync()
                self.store.push_attachments()
            except Exception as e:
                res = e
            try:
                self._syncer.done.emit(res)
            except RuntimeError:          # Project Center closed meanwhile
                log.info("sync result dropped", exc_info=True)
        self._sync_thread = threading.Thread(target=work, daemon=True)
        self._sync_thread.start()

    def _synced(self, res):
        self._busy = False
        if isinstance(res, Exception):
            log.info("sync failed: %s", res)
        elif res.get("denied"):
            self.toast(f"{res['denied']} change(s) not saved: "
                       f"{self.store.last_denied}")
            for p in self.pages.values():
                p.refresh()
        elif res.get("received"):
            for p in self.pages.values():
                p.refresh()
            self.home_dirty = True
            if self.stack.currentWidget() is self.home:
                self.home.refresh()
        self._update_sync()

    def share(self):
        if ShareDialog(self).exec():
            self.setWindowTitle(f"Project Center - {self.store.name}")
            self.proj_btn.setText(self.store.name)
            for p in self.pages.values():
                p.refresh()
            self._update_sync()

    def manage_users(self):
        from .usersui import UsersDialog
        if not self.store.connected:
            QMessageBox.information(
                self, "Users and roles", "Share the project first - logins "
                "and roles live on your relay with the shared project.")
            return None
        dlg = UsersDialog(self)
        dlg.exec()
        self._update_sync()
        return dlg

    # ---------------------------------------------------------- projects
    def switch_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Project folder",
                                                  self.store.folder)
        if folder:
            open_center(folder, self.parent())
            self.close()

    def new_project(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose or make a folder for the new project")
        if folder:
            open_center(folder, self.parent(), create=True)

    def prime_terms(self):
        """The owner contract's terms (NW-13)."""
        from . import contract_terms as ct
        d = QDialog(self)
        d.setWindowTitle("Owner contract terms")
        f = QFormLayout(d)
        cur = ct.prime(self.store)
        eds = {}
        for key, label, kind in ct.TERMS:
            if kind == "yesno":
                e = QComboBox()
                e.addItems(["", "Yes", "No"])
                e.setCurrentText(cur.get(key) or "")
            else:
                e = QLineEdit(cur.get(key) or "")
            f.addRow(label, e)
            eds[key] = e
        bb = QDialogButtonBox(QDialogButtonBox.Save |
                              QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        f.addRow(bb)
        if not d.exec():
            return None
        vals = {k: (e.currentText() if isinstance(e, QComboBox) else
                    e.text()) for k, e in eds.items()}
        return ct.set_prime(self.store, vals)

    def photo_library(self, show=True):
        """Project > Photos: albums by date, area or tag; pins (P1)."""
        from .photo_library_ui import PhotoLibraryDialog
        d = PhotoLibraryDialog(self.store, self)
        if show:
            d.exec()
        return d

    def allowances(self, show=True):
        """Project > Allowances: the contract's allowances, for the owner
        report pack (amount, spent, left)."""
        from .allowances_ui import AllowancesDialog
        d = AllowancesDialog(self.store, self)
        if show:
            d.exec()
        return d

    def backup_job(self, path=None):
        """Project > Back Up This Job: a zip with a SHA-256 manifest."""
        from PySide6.QtWidgets import QFileDialog
        from . import project_backup as pb
        self.store.flush(force=True)
        if path is None:
            import datetime as _d
            name = f"{self.store.name or 'job'} " \
                f"{_d.date.today().isoformat()}.qsjob.zip"
            path, _ = QFileDialog.getSaveFileName(
                self, "Back Up This Job", name, "Job backup (*.qsjob.zip)")
            if not path:
                return None
        man = pb.backup(self.store.folder, path)
        QMessageBox.information(self, "Back Up This Job",
                                f"Saved {len(man['files'])} file(s) with "
                                f"their checksums:\n{path}")
        return path

    def restore_job(self, path=None, target=None):
        """Project > Restore a Job Backup: every file is checked against
        the backup's manifest before anything is replaced."""
        from PySide6.QtWidgets import QFileDialog
        from . import project_backup as pb
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Restore a Job Backup", "",
                "Job backup (*.qsjob.zip *.zip)")
            if not path:
                return None
        target = target or self.store.folder
        if QMessageBox.question(
                self, "Restore a Job Backup", "Replace this job with the "
                "backup? The job as it is now is kept beside it.") != \
                QMessageBox.Yes:
            return None
        try:
            n = pb.restore(path, target, overwrite=True)
        except pb.BackupError as e:
            QMessageBox.warning(self, "Restore a Job Backup", str(e))
            return None
        QMessageBox.information(self, "Restore a Job Backup",
                                f"Restored {n} file(s), each checked. "
                                "Close and reopen the job to see it.")
        return n

    def check_terms(self):
        """Every subcontract against the owner contract (NW-14)."""
        from . import contract_terms as ct
        rows = ct.conflicts(self.store)
        d = QDialog(self)
        d.setWindowTitle("Subcontract terms vs the owner contract")
        d.resize(900, 480)
        v = QVBoxLayout(d)
        v.addWidget(QLabel(f"{len(rows)} item(s). Enter the owner's terms "
                           "in Project > Owner contract terms, and each "
                           "sub's on its Commitment." if rows else
                           "No conflicts found (terms not entered aren't "
                           "checked)."))
        t = QTableWidget(len(rows), 4)
        t.setHorizontalHeaderLabels(["Severity", "Subcontract", "Sub",
                                     "Issue"])
        for r, x in enumerate(rows):
            for c, val in enumerate((x["severity"], x["no"], x["sub"],
                                     x["text"])):
                t.setItem(r, c, QTableWidgetItem(str(val or "")))
        t.horizontalHeader().setStretchLastSection(True)
        t.resizeColumnsToContents()
        v.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        d.exec()
        return rows

    def project_settings(self):
        d = QDialog(self)
        d.setWindowTitle("Project settings")
        f = QFormLayout(d)
        name = QLineEdit(self.store.name)
        loc = QLineEdit(self.store.setting("location") or "")
        loc.setPlaceholderText("Town, ST (for daily-log weather)")
        rev = QLineEdit(self.store.setting("default_reviewer") or "")
        rev.setPlaceholderText("Architect who reviews submittals")
        number = QLineEdit(self.store.setting("number") or "")
        f.addRow("Project name", name)
        f.addRow("Job number", number)
        f.addRow("Job site", loc)
        f.addRow("Default submittal reviewer", rev)
        extra = {}
        for key, label, hint in (
                ("owner", "Owner", "Aiken County"),
                ("owner_contact", "Owner contact (for change orders, pay "
                 "apps)", "a Directory name or email"),
                ("architect", "Architect", ""),
                ("architect_contact", "Architect contact", ""),
                ("contractor", "Contractor", "your company"),
                ("contract_date", "Contract date", "yyyy-mm-dd"),
                ("contract_for", "Contract for", "General construction"),
                # the Estimating Dashboard compares projects by these
                ("building_type", "Building type", "Office, Retail, "
                 "Warehouse..."),
                ("building_sf", "Building SF", "gross square feet"),
                ("bid_date", "Bid date", "yyyy-mm-dd"),
                ("estimator", "Estimator", ""),
                ("bid_amount", "Our bid amount", "$")):
            e = QLineEdit(self.store.setting(key) or "")
            e.setPlaceholderText(hint)
            f.addRow(label, e)
            extra[key] = e
        from .. import dashboard
        result = QComboBox()
        result.addItems([""] + list(dashboard.RESULTS))
        result.setCurrentText(dashboard._result(
            self.store.setting(dashboard.RESULT_SETTING)))
        result.setToolTip("Our bid's result, for the Estimating Dashboard's "
                          "hit rate (blank = not recorded yet)")
        f.addRow("Bid result", result)
        # the Claim Package, the DCMA check and Recovery measure against
        # the contract completion date; notice is checked against the
        # notice period (recovery.CONTRACT_SETTING / NOTICE_SETTING)
        from . import recovery
        terms = recovery.contract_terms(self.store)
        cc = QLineEdit(terms["completion"].isoformat()
                       if terms["completion"] else "")
        cc.setPlaceholderText("yyyy-mm-dd (blank = the baseline finish)")
        notice = QLineEdit(str(terms["notice_days"]))
        notice.setPlaceholderText(str(recovery.NOTICE_DEFAULT))
        f.addRow("Contract completion date", cc)
        f.addRow("Notice period (days)", notice)
        bb = QDialogButtonBox(QDialogButtonBox.Save |
                              QDialogButtonBox.Cancel)

        def save():
            try:
                recovery.parse_terms(cc.text(), notice.text())
            except ValueError as e:
                QMessageBox.warning(d, "Project settings", str(e))
                return
            from ..dmoney import bad
            for key, what in (("building_sf", "Building SF"),
                              ("bid_amount", "Our bid amount")):
                if bad(extra[key].text()):
                    QMessageBox.warning(d, "Project settings",
                                        f"{what}: can't read "
                                        f"{extra[key].text()!r} as a number.")
                    return
            if extra["bid_date"].text().strip() and \
                    dashboard.parse_date(extra["bid_date"].text()) is None:
                QMessageBox.warning(d, "Project settings",
                                    "Bid date: use yyyy-mm-dd.")
                return
            d.accept()
        bb.accepted.connect(save)
        bb.rejected.connect(d.reject)
        f.addRow(bb)
        if d.exec():
            recovery.set_terms(self.store, cc.text(), notice.text())
            if not self.store.connected:
                self.store.data["name"] = name.text().strip() or \
                    self.store.name
            self.store.set_setting("location", loc.text().strip())
            self.store.set_setting("default_reviewer", rev.text().strip())
            self.store.set_setting("number", number.text().strip())
            for key, e in extra.items():
                self.store.set_setting(key, e.text().strip())
            self.store.set_setting(dashboard.RESULT_SETTING,
                                   result.currentText())
            self.proj_btn.setText(self.store.name)

    # ---------------------------------------------------------- style
    def _restyle(self, *_):
        t = theme.tokens()
        self.setStyleSheet(f"""
#pcTop {{ background:{t['surface']}; border-bottom:1px solid {t['border']}; }}
#pcProject {{ font-size:12pt; font-weight:700; border:none;
  padding:4px 18px 4px 8px; }}
#pcJump {{ text-align:left; color:{t['muted']}; background:{t['surface2']};
  border:1px solid {t['border']}; border-radius:8px; padding:6px 10px;
  max-width:460px; }}
#pcSync {{ border:1px solid {t['border']}; border-radius:14px;
  padding:4px 12px; color:{t['muted']}; background:{t['surface']}; }}
#pcNav {{ background:{t['surface2']}; border:none;
  border-right:1px solid {t['border']}; padding:8px 6px; outline:0; }}
#pcNav::item {{ padding:6px 8px; border-radius:6px; margin:1px 0; }}
#pcNav::item:selected {{ background:{t['accent_soft']}; color:{t['text']};
  font-weight:600; }}
#pcNav::item:hover:!selected {{ background:{t['raised']}; }}
#pcPageHead, #pcFormHead {{ background:{t['surface']};
  border-bottom:1px solid {t['border']}; }}
#pcH1 {{ font-size:15pt; font-weight:700; }}
#pcH2 {{ font-size:11pt; font-weight:700; margin-top:8px; }}
#pcHello {{ font-size:19pt; font-weight:700; }}
#pcNo {{ color:{t['muted']}; font-weight:700; }}
QLineEdit#pcTitle {{ font-size:14pt; font-weight:700;
  background:transparent; border:none; border-bottom:1px solid transparent;
  border-radius:0; padding:2px 0; }}
QLineEdit#pcTitle:focus {{ border-bottom:1px solid {t['accent']}; }}
#pcLabel {{ color:{t['muted']}; }}
#pcDialogTitle {{ font-size:13pt; font-weight:700; }}
#pcList {{ border:none; background:{t['surface']};
  selection-background-color:{t['accent_soft']};
  selection-color:{t['text']}; }}
#pcList::item {{ border-bottom:1px solid {t['border']}; padding:0 6px; }}
#pcFormBody {{ background:{t['surface']}; }}
QLabel#muted {{ color:{t['muted']}; }}
QPushButton#chip {{ border:1px solid {t['border']}; border-radius:13px;
  padding:3px 12px; background:{t['surface']}; }}
QPushButton#chip:checked {{ background:{t['accent_soft']};
  border-color:{t['accent']}; color:{t['text']}; font-weight:600; }}
QPushButton#primary {{ background:{t['accent']}; color:{t['on_accent']};
  border:1px solid {t['accent']}; border-radius:6px; padding:5px 14px;
  font-weight:600; }}
QPushButton#primary:hover {{ background:{t['accent2']}; }}
QFrame#pcCard {{ background:{t['surface']};
  border:1px solid {t['border']}; border-radius:10px; }}
QFrame#pcCard:hover {{ border-color:{t['accent']}; }}
#pcHomeList {{ border:1px solid {t['border']}; border-radius:8px;
  background:{t['surface']}; }}
#pcHomeList::item {{ padding:5px 8px; }}
#pcMore {{ border:none; color:{t['accent']}; font-weight:600; }}
#pcToast {{ background:{t['tip']}; color:white; border-radius:8px;
  padding:9px 14px; }}
""")


def live_main(center):
    """The main PDF window, or None once it has been closed and deleted
    (calling into a deleted Qt window crashes; review 3 #33)."""
    main = getattr(center, "main", None)
    if main is None:
        return None
    try:
        import shiboken6
        return main if shiboken6.isValid(main) else None
    except Exception:
        return main


def open_center(folder, parent=None, create=False):
    """Open Project Center for a project folder (making the project the
    first time). Keeps a reference so the window isn't collected."""
    store = open_store(folder)
    if not ProjectStore.exists(folder):
        store.save()
    recent = [f for f in settings.get("pm_recent", []) if f != folder]
    settings.set("pm_recent", ([folder] + recent)[:8])
    w = ProjectCenter(store, None)
    w.main = parent
    _WINDOWS.append(w)
    def gone(*_):
        try:
            _WINDOWS.remove(w)
        except ValueError:                  # already gone (#34)
            pass
    w.destroyed.connect(gone)
    w.setAttribute(Qt.WA_DeleteOnClose)
    from .. import modern_ui            # opens full screen (Jon, 0.13.11)
    modern_ui.ensure_maximized(w)
    return w


_WINDOWS = []


def pick_and_open(parent=None):
    """Recent projects, or choose a folder."""
    recent = [f for f in settings.get("pm_recent", []) if os.path.isdir(f)]
    d = QDialog(parent)
    d.setWindowTitle("Project Center")
    d.setMinimumWidth(520)
    v = QVBoxLayout(d)
    h = QLabel("Open a project")
    h.setObjectName("pcDialogTitle")
    h.setStyleSheet("font-size:13pt;font-weight:700")
    v.addWidget(h)
    lw = QListWidget()
    for f in recent:
        name = os.path.basename(f)
        try:
            name = ProjectStore(f).name
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
        it = QListWidgetItem(icons.icon("folder"), f"{name}\n{f}")
        it.setData(Qt.UserRole, f)
        lw.addItem(it)
    if recent:
        v.addWidget(lw)
    else:
        e = QLabel("A project is a folder: its drawings, specs and the "
                   "Project Center data live together. Pick the job's "
                   "folder to start.")
        e.setWordWrap(True)
        v.addWidget(e)
    chosen = {}

    def open_sel(it=None):
        it = it or lw.currentItem()
        if it:
            chosen["f"] = it.data(Qt.UserRole)
            d.accept()

    def browse():
        f = QFileDialog.getExistingDirectory(d, "Project folder")
        if f:
            chosen["f"] = f
            d.accept()
    lw.itemDoubleClicked.connect(open_sel)
    bb = QHBoxLayout()
    b1 = QPushButton("Choose folder…")
    b1.clicked.connect(browse)
    bb.addWidget(b1)
    bb.addStretch()
    if recent:
        b2 = QPushButton("Open")
        b2.setDefault(True)
        b2.clicked.connect(lambda: open_sel())
        bb.addWidget(b2)
    cancel = QPushButton("Cancel")      # not only Esc (Chief, Nov 6)
    cancel.setAutoDefault(False)
    cancel.clicked.connect(d.reject)
    bb.addWidget(cancel)
    d._cancel = cancel
    v.addLayout(bb)
    if d.exec() and chosen.get("f"):
        return open_center(chosen["f"], parent)
    return None
