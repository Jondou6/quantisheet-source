"""Master Schedule window (Qt): review queue, intake, baseline lock,
drafts and settings. All logic lives in the pure-Python modules; this
file only shows it and asks Jon."""
import datetime as _dt
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from . import (apply, baseline, cycle, diff, drafts, extras, intake,
               match, model)
from .values import base_of

POLL_MS = 60_000
NTH = [(1, "1st Thursday"), (2, "2nd Thursday"), (3, "3rd Thursday"),
       (4, "4th Thursday"), ("last", "Last Thursday")]


def _when(iso):
    """'2026-10-29T08:14:05+00:00' -> '2026-10-29 08:14' in local time
    (review r41 F07: the ISO stamp was cut off in the queue)."""
    import datetime as _d
    if not iso:
        return ""
    try:
        t = _d.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is not None:
            t = t.astimezone()
        return t.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(iso).replace("T", " ")[:16]


def _fmt(v):
    return "(blank)" if v in (None, "") else str(v)


def describe(sub):
    """The detail text for one submission."""
    L = [f"{model.label(sub)}  {sub.get('company')}  -  {sub.get('status')}",
         f"Received {sub.get('received')} by {sub.get('channel')}"
         f"{' - ' + sub['file_name'] if sub.get('file_name') else ''}; "
         f"cycle {sub.get('cycle') or '?'}; template rev "
         f"{sub.get('based_on')}"]
    if sub.get("rechecked"):
        L.append(f"Re-checked against the current master "
                 f"{sub['rechecked']}.")
    if sub.get("reasons"):
        L += ["", "REJECTED - nothing was applied. Every reason:"]
        L += [f"  {r.get('where')}: {r.get('text')}" for r in sub["reasons"]]
    if sub.get("why"):
        L += ["", "Needs you because:"] + [f"  - {w}" for w in sub["why"]]
    if sub.get("changes"):
        L += ["", "Changes (before -> after):"]
        L += [f"  {c['_no']} {c['name']}: {c['field']} {_fmt(c['before'])}"
              f" -> {_fmt(c['after'])}" for c in sub["changes"]]
    if sub.get("conflicts"):
        L += ["", "Conflicts (you changed it too since the template went "
              "out; approving takes the sub's value):"]
        L += [f"  {c['_no']} {c['field']}: sent {_fmt(c['base'])}, master "
              f"now {_fmt(c['current'])}, sub says {_fmt(c['sub'])}"
              for c in sub["conflicts"]]
    imp = sub.get("impact") or {}
    if imp:
        L += ["", f"Impact (data date {imp.get('data_date')}): project "
              f"finish {imp.get('finish_before')} -> "
              f"{imp.get('finish_after')} ({imp.get('finish_workdays', 0):+d}"
              " workdays)"]
        ms = imp.get("milestone")
        if ms:
            L.append(f"  {ms['_no']} {ms['name']}: {ms['before']} -> "
                     f"{ms['after']} ({ms['workdays']:+d} workdays)")
        if imp.get("later"):
            L.append(f"  {len(imp['later'])} activities finish later:")
            L += [f"    {x['_no']} {x['name']} ({x['owner']}): {x['before']}"
                  f" -> {x['after']} ({x['workdays']:+d})"
                  for x in imp["later"]]
        else:
            L.append("  No activity finishes later.")
        if imp.get("red_flags"):
            L += ["  Red flags:"] + [f"    {f}" for f in imp["red_flags"]]
    for key, title in (("warnings", "Warnings"),):
        if sub.get(key):
            L += ["", title + ":"] + [f"  {w.get('where')}: {w.get('text')}"
                                      for w in sub[key]]
    if sub.get("ignored"):
        L += ["", "Ignored (outside the sub's activities):"]
        L += [f"  {i['_no']} {i['name']}: {', '.join(i['fields'])} "
              f"({i['why']})" for i in sub["ignored"]]
    if sub.get("new"):
        L += ["", "New internal activities (kept on this submission, rolled "
              "up - not added to the master):"]
        L += [f"  {n['name']}: {n['duration']} workdays inside "
              f"{n['parent_no']}" for n in sub["new"]]
    if sub.get("not_reported"):
        L += ["", "Not reported this cycle (unchanged): " +
              ", ".join(sub["not_reported"])]
    if sub.get("unmatched"):
        L += ["", "Not matched to a master activity (use Map rows…; not "
              "used until mapped):"]
        L += [f"  {u['ref']}  {u['name']}  ({u['where']})"
              for u in sub["unmatched"]]
    if sub.get("logic_requests"):
        L += ["", "Proposed logic changes (links in the sub's file that "
              "differ from the master - never applied by the module):"]
        L += [f"  {x['_no']} {x['name']}: file {', '.join(x['file']) or '-'}"
              f"; master {', '.join(x['master']) or '-'}"
              for x in sub["logic_requests"]]
    if sub.get("gc_overrides"):
        L += ["", "GC overrides (Edit and approve):"]
        L += [f"  {o['_no']} {o['field']}: sub {_fmt(o['sub'])} -> GC "
              f"{_fmt(o['gc'])}" for o in sub["gc_overrides"]]
    if sub.get("error"):
        L += ["", f"Apply failed (nothing kept): {sub['error']}"]
    return "\n".join(L)



def _add_buttons(layout, items):
    """Each callable is a no-argument lambda, so a button's 'checked'
    flag never lands in a defaulted parameter."""
    for text, fn in items:
        b = QPushButton(text)
        b.clicked.connect(fn)
        layout.addWidget(b)

class EntryDialog(QDialog):
    """Q11 (Jon: yes, but not preferred): the GC types a sub's update; it
    goes through the same checks and review queue as a file."""
    COLS = ("No.", "Activity", "Duration (workdays)", "% complete",
            "Actual start", "Actual finish", "Expected finish", "Note")
    FIELD = {"Duration (workdays)": "duration", "% complete": "percent",
             "Actual start": "actual_start", "Actual finish":
             "actual_finish", "Expected finish": "expected_finish",
             "Note": "note"}

    def __init__(self, store, company, cycle_date, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Enter update for {company} - {cycle_date}")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Change only what the sub reported. It goes to "
                           "the review queue like a file would.\n"
                           "Better: have the sub send their own update - "
                           "use this only when they can't (Q11)."))
        ids = set(model.slice_ids(store, company))
        acts = [a for a in store.list("activity") if a["_id"] in ids]
        self.table = QTableWidget(len(acts), len(self.COLS))
        self.table.setHorizontalHeaderLabels(list(self.COLS))
        self._init = {}
        for r, a in enumerate(acts):
            b = base_of(a)
            vals = [a.get("_no"), a.get("name"), _fmt(b["duration"]),
                    "" if b["percent"] is None else str(b["percent"]),
                    b["actual_start"] or "", b["actual_finish"] or "", "",
                    ""]
            vals[2] = "" if b["duration"] is None else str(b["duration"])
            for c, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                if c < 2:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
                self._init[(r, c)] = str(val)
        v.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(900, 400)

    def _row(self, no):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() == no:
                return r
        raise KeyError(no)

    def set_cell(self, no, head, text):
        self.table.item(self._row(no), self.COLS.index(head)).setText(text)

    def entries(self):
        out = []
        for r in range(self.table.rowCount()):
            e = {}
            for c in range(2, len(self.COLS)):
                t = self.table.item(r, c).text().strip()
                if t != self._init[(r, c)]:
                    e[self.FIELD[self.COLS[c]]] = t
            if e:
                out.append({"no": self.table.item(r, 0).text(), **e})
        return out


class MapDialog(QDialog):
    """Map a sub's unmatched MS Project / P6 rows to its own master
    activities (or Ignore), once; the mapping is kept for later cycles."""
    NONE = "(leave unmatched)"
    IGNORE = "Ignore"

    def __init__(self, store, company, unmatched, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Map rows - {company}")
        self._refs = [u["ref"] for u in unmatched]
        mine = set(model.slice_ids(store, company))
        acts = [a for a in store.list("activity") if a["_id"] in mine]
        self._ids = {f"{a.get('_no')} {a.get('name')}": a["_id"]
                     for a in acts}
        v = QVBoxLayout(self)
        self.table = QTableWidget(len(unmatched), 3)
        self.table.setHorizontalHeaderLabels(["Sub's row", "Name",
                                              "Master activity"])
        self._boxes = []
        for r, u in enumerate(unmatched):
            self.table.setItem(r, 0, QTableWidgetItem(u["ref"]))
            self.table.setItem(r, 1, QTableWidgetItem(u.get("name") or ""))
            cb = QComboBox()
            cb.addItems([self.NONE, self.IGNORE] + list(self._ids))
            self.table.setCellWidget(r, 2, cb)
            self._boxes.append(cb)
        v.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(700, 400)

    def choices(self, row):
        cb = self._boxes[row]
        return [cb.itemText(k) for k in range(cb.count())]

    def choose(self, row, text):
        self._boxes[row].setCurrentText(text)

    def pairs(self):
        out = {}
        for ref, cb in zip(self._refs, self._boxes):
            t = cb.currentText()
            if t == self.IGNORE:
                out[ref] = match.IGNORE
            elif t in self._ids:
                out[ref] = self._ids[t]
        return out


class LinesDialog(QDialog):
    """Approve lines: tick the activities whose changes go in."""

    def __init__(self, sub, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Approve lines")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Tick the activities whose changes to take. The "
                           "others keep the master's values (recorded as "
                           "your overrides)."))
        self.list = QListWidget()
        seen = {}
        for c in sub.get("changes") or []:
            seen.setdefault(str(c.get("_no")), []).append(
                f"{c['field']} {_fmt(c['before'])} -> {_fmt(c['after'])}")
        names = {str(c.get("_no")): c.get("name")
                 for c in sub.get("changes") or []}
        from PySide6.QtWidgets import QListWidgetItem
        for no, parts in seen.items():
            it = QListWidgetItem(f"{no} {names.get(no) or ''}: "
                                 + "; ".join(parts))
            it.setData(Qt.UserRole, no)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.list.addItem(it)
        v.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(760, 460)

    def keep(self):
        return [self.list.item(i).data(Qt.UserRole)
                for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]

    def set_checked(self, nos):
        nos = {str(n) for n in nos}
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in nos
                             else Qt.Unchecked)


class _Bars(QWidget):
    """Before (grey) and after (blue / red when critical) bars."""

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.rows = rows
        ds = [_dt.date.fromisoformat(d) for r in rows
              for d in r["before"] + r["after"]]
        self.d0 = min(ds) if ds else _dt.date.today()
        self.d1 = max(ds) if ds else self.d0
        self.setMinimumHeight(40 + 30 * max(1, len(rows)))

    def paintEvent(self, _ev):
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self)
        lab = 330
        span = max(1, (self.d1 - self.d0).days + 1)
        w = max(50, self.width() - lab - 20)

        def x(d):
            return lab + w * ((_dt.date.fromisoformat(d) - self.d0).days
                              / span)
        p.drawText(lab, 14, f"{self.d0:%b %d, %Y}")
        p.drawText(lab + w - 90, 14, f"{self.d1:%b %d, %Y}")
        y = 26
        for r in self.rows:
            p.setPen(QColor("#222222"))
            p.drawText(6, y + 16, f"{r['_no']} {str(r['name'])[:42]}")
            b0, b1 = r["before"]
            a0, a1 = r["after"]
            p.fillRect(int(x(b0)), y + 3, max(2, int(x(b1) - x(b0)) + 3), 8,
                       QColor("#b8bcc4"))
            p.fillRect(int(x(a0)), y + 13, max(2, int(x(a1) - x(a0)) + 3),
                       10, QColor("#d64545" if r["critical"]
                                  else "#2f6fd6"))
            y += 30
        p.end()


class PreviewDialog(QDialog):
    def __init__(self, rows, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Grey: the master now. Blue: after this update "
                           "(red = on the critical path). Only activities "
                           "the update changes or moves are shown."))
        from PySide6.QtWidgets import QScrollArea
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        self.bars = _Bars(rows)
        sa.setWidget(self.bars)
        v.addWidget(sa, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(1000, 560)


class MasterScheduleWindow(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(f"Master Schedule - {store.name}")
        self._state = intake.state_for(store)   # shared with the hook
        self._ids = []
        self._drafts = []
        v = QVBoxLayout(self)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        v.addWidget(self.banner)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs)
        self._queue_tab()
        self._intake_tab()
        self._baseline_tab()
        self._drafts_tab()
        self._settings_tab()
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self._poll)
        self.resize(1100, 700)
        self.refresh()
        if model.config(store).get("inbox"):
            self._poll()
        self.timer.start()

    # ------------------------------------------------------------ build
    def _queue_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        sp = QSplitter(Qt.Vertical)
        self.queue = QTableWidget(0, 8)
        self.queue.setHorizontalHeaderLabels(
            ["No.", "Sub", "Received", "Channel", "Status", "Finish impact",
             "Later", "Flags"])
        self.queue.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue.setSelectionMode(QAbstractItemView.SingleSelection)
        self.queue.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue.itemSelectionChanged.connect(self._show)
        sp.addWidget(self.queue)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        sp.addWidget(self.detail)
        v.addWidget(sp)
        self.combined_label = QLabel()
        self.combined_label.setWordWrap(True)
        v.addWidget(self.combined_label)
        h = QHBoxLayout()
        self.btn_approve = QPushButton("Approve (whole submission)")
        self.btn_approve.clicked.connect(lambda: self.approve_selected())
        self.btn_decline = QPushButton("Decline…")
        self.btn_decline.clicked.connect(lambda: self.decline_selected())
        self.btn_revert = QPushButton("Revert")
        self.btn_revert.clicked.connect(lambda: self.revert_selected())
        self.btn_edit = QPushButton("Edit and approve…")
        self.btn_edit.clicked.connect(lambda: self.edit_and_approve())
        self.btn_map = QPushButton("Map rows…")
        self.btn_map.clicked.connect(lambda: self.map_rows())
        self.btn_lines = QPushButton("Approve lines…")
        self.btn_lines.clicked.connect(lambda: self.approve_lines())
        self.btn_preview = QPushButton("Before / after…")
        self.btn_preview.clicked.connect(lambda: self.show_preview())
        self.btn_delay = QPushButton("To Delay Log")
        self.btn_delay.clicked.connect(lambda: self.to_delay_log())
        self.btn_help = QPushButton("Help")
        self.btn_help.clicked.connect(lambda: self.open_help())
        for b in (self.btn_approve, self.btn_lines, self.btn_edit,
                  self.btn_decline, self.btn_revert, self.btn_map,
                  self.btn_preview, self.btn_delay, self.btn_help):
            h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        self.tabs.addTab(w, "Review queue")

    def _intake_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        _add_buttons(h, (
            ("Add submission…", lambda: self.add_submission()),
            ("Enter update for sub…", lambda: self.enter_update()),
            ("Check inbox now", lambda: self.check_inbox()),
            ("Prepare update packets…", lambda: self.prepare_packets())))
        h.addStretch(1)
        v.addLayout(h)
        self.cycle_label = QLabel()
        self.cycle_label.setWordWrap(True)
        v.addWidget(self.cycle_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        v.addWidget(self.log)
        self.tabs.addTab(w, "Intake")

    def _baseline_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.base_label = QLabel()
        self.base_label.setWordWrap(True)
        v.addWidget(self.base_label)
        self.drift = QPlainTextEdit()
        self.drift.setReadOnly(True)
        v.addWidget(self.drift)
        h = QHBoxLayout()
        _add_buttons(h, (
            ("Lock baseline…", lambda: self.lock_baseline()),
            ("Re-baseline…", lambda: self.rebaseline()),
            ("Restore locked dates", lambda: self.restore_baseline())))
        h.addStretch(1)
        v.addLayout(h)
        self.tabs.addTab(w, "Baseline")

    def _drafts_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Nothing is sent to subs by QuantiSheet. Open a "
                           "draft: Outlook shows it and you send it "
                           "yourself."))
        self.drafts_list = QListWidget()
        v.addWidget(self.drafts_list)
        b = QPushButton("Open selected draft in Outlook…")
        b.clicked.connect(lambda: self.open_draft(
            self.drafts_list.currentRow()))
        v.addWidget(b)
        self.tabs.addTab(w, "Drafts")

    def _settings_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        c = model.config(self.store)
        h = QHBoxLayout()
        self.inbox_edit = QLineEdit(c.get("inbox") or "")
        h.addWidget(self.inbox_edit)
        b = QPushButton("Folder…")
        b.clicked.connect(self._browse)
        h.addWidget(b)
        b = QPushButton("Dropbox…")
        b.setToolTip("Use a Dropbox folder: subs upload through a Dropbox "
                     "link, QuantiSheet reads it with your Dropbox sign-in")
        b.clicked.connect(lambda _c=False: self.browse_dropbox())
        h.addWidget(b)
        f.addRow("Inbox (one subfolder per sub)", h)
        from . import dropbox_inbox
        ok, who = dropbox_inbox.signed_in()
        self.dbx_status = QLabel(
            f"Signed in{' as ' + who if who else ''}" if ok else
            "Not signed in - File > Dropbox > Sign in")
        f.addRow("Dropbox", self.dbx_status)
        mf = QPushButton("Make a Dropbox folder for each sub")
        mf.setToolTip("One folder per sub under the Dropbox inbox, for "
                      "their file request")
        mf.clicked.connect(lambda _c=False: self.make_sub_folders())
        f.addRow("", mf)
        lb = QPushButton("Sub upload links…")
        lb.clicked.connect(lambda _c=False: self.edit_upload_links())
        f.addRow("Dropbox link for each sub", lb)
        self.nth = QComboBox()
        for _k, t in NTH:
            self.nth.addItem(t)
        self.nth.setCurrentIndex([k for k, _t in NTH].index(
            c["cycle"].get("nth", "last")))
        f.addRow("Monthly update on the", self.nth)
        self.auto_box = QCheckBox("Accept progress-only updates that move "
                                  "no finish later (zero slip) on their "
                                  "own; they can be reverted")
        self.auto_box.setChecked(bool(c["auto_accept"].get("progress_only")))
        f.addRow("Auto-accept", self.auto_box)
        for t, text in (
                ("Sub detail", "One roll-up line per sub (their detail "
                 "shows in review)"),
                ("Who approves", "Project manager (or Admin login)"),
                ("Subs change logic", "No - link changes are only listed"),
                ("Uploads", "Dropbox link (no web page)"),
                ("Who owns an activity", "By CSI code (Cost code)")):
            f.addRow(t, QLabel(text))
        sb = QPushButton("Save settings")
        sb.clicked.connect(lambda: self.save_settings())
        f.addRow(sb)
        cb = QPushButton("CSI codes for each sub…")
        cb.clicked.connect(lambda _c=False: self.edit_csi_owners())
        f.addRow(cb)
        ab = QPushButton("Assign subs to activities…")
        ab.clicked.connect(lambda: self.assign_subs())
        f.addRow(ab)
        self.tabs.addTab(w, "Settings")

    # ------------------------------------------------------------ show
    def refresh(self, keep=None):
        keep = keep or self.selected_id()
        subs = sorted(model.submissions(self.store),
                      key=lambda s: s.get("received") or "", reverse=True)
        self._ids = [s["_id"] for s in subs]
        self.queue.setRowCount(len(subs))
        for r, s in enumerate(subs):
            imp = s.get("impact") or {}
            vals = [model.label(s), s.get("company"),
                    _when(s.get("received")),
                    s.get("channel"), s.get("status"),
                    f"{imp.get('finish_workdays', 0):+d} wd" if imp else "",
                    str(len(imp.get("later") or [])) if imp else "",
                    str(len(imp.get("red_flags") or []) +
                        len(s.get("warnings") or []) +
                        len(s.get("conflicts") or []))]
            for c, val in enumerate(vals):
                self.queue.setItem(r, c, QTableWidgetItem(str(val or "")))
        self.queue.resizeColumnsToContents()
        if keep in self._ids:
            self.select(keep)
        else:
            self._show()
        pend = sum(1 for s in subs if s.get("status") == "Pending review")
        st = baseline.status(self.store)
        self.banner.setText(
            f"{pend} waiting for review. Baseline "
            f"{'locked' if st else 'not locked'}. Master rev "
            f"{model.config(self.store)['rev']}. Next update: "
            f"{cycle.next_date(model.config(self.store)['cycle'])}.")
        self._refresh_cycle(subs)
        self._refresh_baseline()
        self._refresh_drafts()

    def _refresh_cycle(self, subs):
        try:
            st = cycle.status(self.store)
            self.cycle_label.setText(
                f"Next data date {st['next']} (previous {st['previous']}). "
                f"Reminder drafts {'are due now' if st['remind_due'] else 'due ' + st['remind_on']}"
                " - Prepare update packets makes them; nothing is sent."
                + "".join("\n" + w for w in st["warnings"]))
        except ValueError as ex:
            self.cycle_label.setText(f"Cycle: {ex}")
        pend = [s for s in subs if s.get("status") == "Pending review"]
        cyc = {}
        for s in pend:
            cyc[s.get("cycle")] = cyc.get(s.get("cycle"), 0) + 1
        if len(pend) < 2:
            self.combined_label.setText("")
            return
        top = max(cyc, key=lambda c: (cyc[c], str(c)))
        try:
            c = diff.combined(self.store, top)
        except Exception as ex:                       # noqa: BLE001
            self.combined_label.setText(f"Combined impact: {ex}")
            return
        self.combined_label.setText(
            f"{len(c['submissions'])} pending for the {top} cycle, taken "
            f"together: project finish {c.get('finish_workdays', 0):+d} "
            f"workdays, {len(c.get('later') or [])} activities finish "
            "later. Each is still approved on its own.")

    def _refresh_baseline(self):
        st = baseline.status(self.store)
        if not st:
            self.base_label.setText("Baseline not locked. Lock it to keep "
                                    "the original baseline from ever being "
                                    "overwritten.")
            self.drift.setPlainText("")
            return
        probs = baseline.problems(self.store)
        self.base_label.setText(
            f"Locked: update {st['snapshot_n']} ({st['reason']}), "
            f"{st['at']} by {st['by']}. Set Baseline is refused while "
            "locked; use Re-baseline." +
            ("\nPROBLEM: " + "; ".join(probs) if probs else ""))
        try:
            d = baseline.drift(self.store)
        except ValueError:
            d = []
        self.drift.setPlainText(
            "\n".join(f"{x['_no']} {x['name']}: {x['field']} shows "
                      f"{x['shown'] or '(blank)'}, locked {x['locked']}"
                      for x in d) or "Displayed baseline dates match the "
            "locked baseline.")

    def _refresh_drafts(self):
        self._drafts = []
        self.drafts_list.clear()
        for s in model.submissions(self.store):
            for k, d in enumerate(s.get("drafts") or []):
                self._drafts.append((s["_id"], k))
                self.drafts_list.addItem(
                    f"{model.label(s)} {d['kind']} to {d['company']}: "
                    f"{d['subject']}"
                    f"{'  (opened ' + d['opened'] + ')' if d.get('opened') else ''}")
        for k, d in enumerate(model.config(self.store).get("outbox") or []):
            self._drafts.append((None, k))
            self.drafts_list.addItem(
                f"{d['kind']} to {d['company']}: {d['subject']}"
                f"{'  (opened ' + d['opened'] + ')' if d.get('opened') else ''}")

    def selected_id(self):
        rows = self.queue.selectionModel().selectedRows() \
            if self.queue.selectionModel() else []
        if rows and rows[0].row() < len(self._ids):
            return self._ids[rows[0].row()]
        return None

    def select(self, sid):
        if sid in self._ids:
            self.queue.selectRow(self._ids.index(sid))
        self._show()

    def _show(self):
        sid = self.selected_id()
        sub = self.store.get(model.SUBS, sid) if sid else None
        self.detail.setPlainText(describe(sub) if sub else "")
        st = sub.get("status") if sub else None
        self.btn_approve.setEnabled(st == "Pending review")
        self.btn_decline.setEnabled(st == "Pending review")
        self.btn_revert.setEnabled(st in ("Auto-accepted", "Approved"))
        self.btn_edit.setEnabled(st == "Pending review")
        self.btn_map.setEnabled(st == "Pending review" and
                                bool(sub.get("unmatched")))
        self.btn_lines.setEnabled(st == "Pending review" and
                                  bool(sub.get("changes")))
        self.btn_preview.setEnabled(bool(sub and sub.get("changes")))
        self.btn_delay.setEnabled(
            st in ("Approved", "Auto-accepted") and
            bool((sub.get("impact") or {}).get("later")) and
            not sub.get("delay_id"))

    def _say(self, text, warn=False):
        self.log.appendPlainText(
            f"{_dt.datetime.now():%H:%M:%S} {text}")
        (QMessageBox.warning if warn else QMessageBox.information)(
            self, "Master Schedule", text)

    # ------------------------------------------------------------ actions
    def approve_selected(self):
        sid = self.selected_id()
        if not sid:
            return None
        try:
            out = apply.approve(self.store, sid)
        except (PermissionError, apply.ApplyRefused) as ex:
            self._say(str(ex), warn=True)
            return None
        if out["status"] == "Pending review":
            self._say("The master changed since this was checked; its "
                      "impact was worked out again - look it over and "
                      "approve again.")
        elif out["status"] == "Apply failed":
            self._say(f"Apply failed; nothing was kept: {out.get('error')}",
                      warn=True)
        self.refresh(keep=sid)
        return out

    def decline_selected(self, reason=None):
        sid = self.selected_id()
        if not sid:
            return None
        if reason is None:
            reason, ok = QInputDialog.getText(self, "Decline",
                                              "Reason (goes in the draft "
                                              "reply):")
            if not ok or not reason.strip():
                return None
        try:
            out = apply.decline(self.store, sid, reason)
        except (ValueError, PermissionError, apply.ApplyRefused) as ex:
            self._say(str(ex), warn=True)
            return None
        self.refresh(keep=sid)
        return out

    def revert_selected(self):
        sid = self.selected_id()
        if not sid:
            return None
        try:
            out = apply.revert(self.store, sid)
        except (ValueError, PermissionError, apply.ApplyRefused) as ex:
            self._say(str(ex), warn=True)
            return None
        self.refresh(keep=sid)
        return out

    def _company(self, company):
        if company:
            return company
        cos = model.companies(self.store)
        company, ok = QInputDialog.getItem(self, "Master Schedule",
                                           "Which sub is this from?", cos,
                                           0, False)
        return company if ok and company else None

    def add_submission(self, path=None, company=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Add schedule update", "",
                "Schedule updates (*.xlsx *.xml *.xer *.pdf);;QuantiSheet "
                "template (*.xlsx);;MS Project XML (*.xml);;P6 XER (*.xer);;"
                "Schedule printout (*.pdf)")
            if not path:
                return None
        company = self._company(company)
        if not company:
            return None
        sub = apply.receive(self.store, path, company, channel="manual")
        self.log.appendPlainText(f"{os.path.basename(path)}: "
                                 f"{sub['status']}")
        self.refresh(keep=sub.get("duplicate_of") or sub["_id"])
        return sub

    def enter_update(self, company=None, cycle_date=None, entries=None):
        company = self._company(company)
        if not company:
            return None
        if cycle_date is None:
            cycle_date = cycle.previous_date(
                model.config(self.store)["cycle"]).isoformat()
        if entries is None:
            d = EntryDialog(self.store, company, cycle_date, self)
            if not d.exec():
                return None
            entries = d.entries()
        sub = apply.receive_manual(self.store, company, cycle_date, entries)
        self.refresh(keep=sub["_id"])
        return sub

    def map_rows(self, pairs=None):
        sid = self.selected_id()
        sub = self.store.get(model.SUBS, sid) if sid else None
        if not sub or not sub.get("unmatched"):
            return None
        if pairs is None:
            d = MapDialog(self.store, sub["company"], sub["unmatched"], self)
            if not d.exec():
                return None
            pairs = d.pairs()
        if not pairs:
            return None
        try:
            new = apply.remap(self.store, sid, pairs)
        except (ValueError, PermissionError, apply.ApplyRefused) as ex:
            self._say(str(ex), warn=True)
            return None
        self.refresh(keep=new["_id"])
        return new

    def approve_lines(self, keep=None):
        sid = self.selected_id()
        sub = self.store.get(model.SUBS, sid) if sid else None
        if not sub or sub.get("status") != "Pending review":
            return None
        if keep is None:
            d = LinesDialog(sub, self)
            if not d.exec():
                return None
            keep = d.keep()
        try:
            out = extras.approve_lines(self.store, sid, keep)
        except (ValueError, PermissionError, apply.ApplyRefused) as ex:
            self._say(str(ex), warn=True)
            return None
        self.refresh(keep=sid)
        return out

    def show_preview(self, show=True):
        sid = self.selected_id()
        sub = self.store.get(model.SUBS, sid) if sid else None
        if not sub:
            return None
        rows = extras.preview(self.store, sub)
        if not show:
            return rows
        d = PreviewDialog(rows, f"Before / after - {model.label(sub)} "
                          f"{sub.get('company')}", self)
        d.exec()
        return rows

    def to_delay_log(self):
        sid = self.selected_id()
        if not sid:
            return None
        try:
            rec = extras.to_delay_log(self.store, sid)
        except (PermissionError, apply.ApplyRefused) as ex:
            self._say(str(ex), warn=True)
            return None
        if rec:
            self._say(f"Delay Log entry {rec.get('_no')} made (Open). Check "
                      "its cause and responsibility in Project Center > "
                      "Delay Log.")
        self.refresh(keep=sid)
        return rec

    def open_help(self):
        w = self.parent()
        if w is not None and hasattr(w, "help_center"):
            return w.help_center("master")
        from ...helpcenter import HelpCenter
        d = HelpCenter(self, "master")
        d.show()
        return d

    def edit_and_approve(self, edits=None):
        sid = self.selected_id()
        sub = self.store.get(model.SUBS, sid) if sid else None
        if not sub or sub.get("status") != "Pending review":
            return None
        if edits is None:
            d = EntryDialog(self.store, sub["company"], sub["cycle"], self)
            if not d.exec():
                return None
            edits = {}
            for e in d.entries():
                no = e.pop("no")
                edits[no] = {k: v for k, v in e.items()
                             if k in diff.SUB_FIELDS}
        try:
            out = apply.approve(self.store, sid, edits=edits)
        except (ValueError, PermissionError, apply.ApplyRefused) as ex:
            self._say(str(ex), warn=True)
            return None
        self.refresh(keep=sid)
        return out

    def _poll(self):
        try:
            r = intake.scan(self.store, self._state)
        except Exception as ex:                       # noqa: BLE001
            self.log.appendPlainText(f"Inbox check failed: {ex}")
            return None
        for s in r["picked"]:
            self.log.appendPlainText(f"{s.get('file_name')} from "
                                     f"{s.get('company')}: {s['status']}")
        for e in r["errors"]:
            self.log.appendPlainText(e)
        if r["picked"]:
            self.refresh()
        return r

    def check_inbox(self):
        r = self._poll()
        self.refresh()
        return r

    def prepare_packets(self):
        try:
            out = intake.prepare_packets(self.store)
        except ValueError as ex:
            self._say(str(ex), warn=True)
            return []
        self.log.appendPlainText(f"{len(out)} update packet(s) written; "
                                 "reminder drafts are on the Drafts tab.")
        self.refresh()
        return out

    def lock_baseline(self, reason=None):
        if reason is None:
            reason, ok = QInputDialog.getText(self, "Lock baseline",
                                              "Reason (e.g. Contract "
                                              "baseline):")
            if not ok:
                return None
        try:
            e = baseline.lock(self.store, reason)
        except ValueError as ex:
            self._say(str(ex), warn=True)
            return None
        self.refresh()
        return e

    def rebaseline(self, reason=None, confirm=None):
        if reason is None:
            reason, ok = QInputDialog.getText(self, "Re-baseline",
                                              "Reason for the new baseline:")
            if not ok:
                return None
        if confirm is None:
            confirm = QMessageBox.question(
                self, "Re-baseline", "Record a NEW baseline and move the "
                "lock to it? The old baseline stays in the history.") == \
                QMessageBox.Yes
        try:
            e = baseline.rebaseline(self.store, reason, confirm=confirm)
        except (ValueError, PermissionError) as ex:
            self._say(str(ex), warn=True)
            return None
        self.refresh()
        return e

    def restore_baseline(self):
        try:
            n = baseline.restore(self.store)
        except ValueError as ex:
            self._say(str(ex), warn=True)
            return 0
        self.refresh()
        return n

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Schedule inbox folder")
        if d:
            self.inbox_edit.setText(d)

    def browse_dropbox(self):
        from ... import dropbox_ui
        from . import dropbox_inbox
        c = dropbox_ui.ensure_client(self)
        if c is None:
            return None
        cur = self.inbox_edit.text().strip()
        start = dropbox_inbox.remote_root(cur) if \
            dropbox_inbox.is_remote(cur) else ""
        b = dropbox_ui.DropboxBrowser(self, c, mode="folder", start=start,
                                      name="(this folder)")
        if not b.exec():
            return None
        folder = b.target.rsplit("/", 1)[0] if b.target else b.folder
        val = dropbox_inbox.as_setting(folder or "")
        self.inbox_edit.setText(val)
        return val

    def _table_dialog(self, title, heads, rows, note):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout
        d = QDialog(self)
        d.setWindowTitle(title)
        d.resize(640, 420)
        v = QVBoxLayout(d)
        lab = QLabel(note)
        lab.setWordWrap(True)
        v.addWidget(lab)
        t = QTableWidget(len(rows) + 10, len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.horizontalHeader().setStretchLastSection(True)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                t.setItem(r, c, QTableWidgetItem(str(val or "")))
        v.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        if not d.exec():
            return None
        out = []
        for r in range(t.rowCount()):
            vals = [(t.item(r, c).text().strip() if t.item(r, c) else "")
                    for c in range(len(heads))]
            if vals[0]:
                out.append(vals)
        return out

    def make_sub_folders(self):
        from . import dropbox_inbox
        self.save_settings()
        try:
            r = dropbox_inbox.make_sub_folders(self.store)
        except Exception as ex:                       # noqa: BLE001
            self._say(str(ex), warn=True)
            return None
        lines = [f"Made: {p}" for p in r["made"]] + \
            [f"Already there: {p}" for p in r["had"]] + r["errors"]
        if not lines:
            lines = ["No subs own activities yet - use Assign subs first."]
        lines.append("\nNext, in Dropbox: make a file request for each "
                     "folder and paste its link in Sub upload links.")
        self._say("\n".join(lines), warn=bool(r["errors"]))
        return r

    def edit_upload_links(self, rows=None):
        cur = model.config(self.store).get("upload_links") or {}
        if rows is None:
            rows = self._table_dialog(
                "Sub upload links", ["Sub (Directory company)",
                                     "Dropbox link"],
                [(c, cur.get(c, "")) for c in model.companies(self.store)],
                "In Dropbox, make a file request (or share the folder) for "
                "each sub's folder in the inbox and paste its link here. "
                "The link goes in that sub's reminder draft.")
            if rows is None:
                return None
        links = {k: "" for k in cur}
        links.update({r[0]: r[1] for r in rows})
        model.set_config(self.store, upload_links=links)
        return links

    def edit_csi_owners(self, rows=None):
        from ..store import spec_number
        cur = model.config(self.store).get("csi_owners") or {}
        if rows is None:
            found = model.csi_owners(self.store)
            seen = dict(cur)
            for code, lst in found.items():
                if code not in seen and len(lst) == 1:
                    seen[code] = lst[0][0]
            rows = self._table_dialog(
                "CSI codes for each sub", ["CSI section", "Sub (company)"],
                sorted(seen.items()),
                "Who owns which CSI section, e.g. 03 30 00 -> your concrete "
                "sub. Commitments and awarded bid packages fill this in on "
                "their own; anything typed here wins. An activity's Cost "
                "code (or a section number at the start of its name) picks "
                "its sub.")
            if rows is None:
                return None
        table = {k: "" for k in cur}
        for code, company in rows:
            n = spec_number(code)
            if n:
                table[n.split(".")[0]] = company
        model.set_config(self.store, csi_owners=table)
        return table

    def save_settings(self):
        model.set_config(
            self.store, inbox=self.inbox_edit.text().strip(),
            cycle={"nth": NTH[self.nth.currentIndex()][0]},
            auto_accept={"progress_only": self.auto_box.isChecked(),
                         "max_slip_workdays": 0})
        self.refresh()

    def assign_subs(self, confirm=None):
        props = model.propose_owners(self.store)
        if not props:
            self._say("Every activity with a Responsible person in the "
                      "Directory already has an owner.")
            return 0
        if confirm is None:
            text = "\n".join(f"{p['_no']} {p['name']} -> {p['company']}"
                             f"  [{p.get('why') or ''}]"
                             for p in props[:40])
            confirm = QMessageBox.question(
                self, "Assign subs", "Set 'Owning subcontractor' from "
                f"Responsible -> Directory company?\n\n{text}") == \
                QMessageBox.Yes
        if not confirm:
            return 0
        n = model.apply_owners(self.store, props, confirm=True)
        self.refresh()
        return n

    def open_draft(self, index, confirm=None):
        if index is None or not 0 <= index < len(self._drafts):
            return None
        sid, k = self._drafts[index]
        if sid is None:
            ob = model.config(self.store).get("outbox") or []
            d = ob[k]
        else:
            sub = self.store.get(model.SUBS, sid)
            d = sub["drafts"][k]
        if confirm is None:
            confirm = QMessageBox.question(
                self, "Open draft", f"Open this in Outlook for you to "
                f"review and send?\n\nTo: {d.get('to') or '(no email)'}\n"
                f"{d['subject']}") == QMessageBox.Yes
        if not confirm:
            return None
        try:
            how = drafts.open_draft(d)
        except Exception as ex:                       # noqa: BLE001
            self._say(f"Couldn't open it: {ex}", warn=True)
            return None
        if sid is None:
            ob[k] = d
            model.set_config(self.store, outbox=ob)
        else:
            sub["drafts"][k] = d
            self.store.save_record(model.SUBS, sub)
        self.refresh()
        return how

    def closeEvent(self, ev):
        self.timer.stop()
        super().closeEvent(ev)

    def done(self, r):
        self.timer.stop()
        super().done(r)
