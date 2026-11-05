"""Recovery Schedule dialog (Gantt Chart > More > Recovery Schedule…).

Where the job stands (target vs forecast), why it slipped, the plan's
steps in a table (crash / fast-track / resequence, how, cost, sub agreed),
the result recomputed as you edit, Suggest Steps, the AI helper, the
owner's PDF and Apply to Schedule. Logic is in recovery.py and
recovery_ai.py; the live schedule changes only on Apply."""
import datetime as _dt
import os

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox,
                               QTableWidget, QVBoxLayout, QWidget)

from . import recovery, recovery_ai

COLS = ["Activity", "Technique", "New days", "Predecessor", "Overlap",
        "How (crew, shifts, equipment)", "Added cost", "Sub agreed"]


def _qdate(d):
    return QDate(d.year, d.month, d.day) if d else QDate.currentDate()


def _pydate(q):
    return _dt.date(q.year(), q.month(), q.day())


_RUNNING = []          # workers outliving a closed dialog, until they end


class _AIWorker(QThread):
    done = Signal(object)
    failed = Signal(str)
    step = Signal(str)

    def __init__(self, store, plan, limits, ask=None):
        super().__init__()
        self.store, self.plan, self.limits, self.ask = store, plan, \
            limits, ask
        self._stop = False

    def stop(self):
        """No more rounds (a model call already under way finishes on its
        own; its answer is dropped)."""
        self._stop = True

    def run(self):
        try:
            out = recovery_ai.run(self.store, self.plan, self.limits,
                                  ask=self.ask, progress=self._progress,
                                  cancel=lambda: self._stop)
        except Exception as e:                     # noqa: BLE001
            if not self._stop:
                self.failed.emit(str(e))
            return
        if not self._stop:
            self.done.emit(out)

    def _progress(self, text):
        if not self._stop:
            self.step.emit(text)


class AIDialog(QDialog):
    """The AI's proposals: tick the ones to add to the plan."""

    def __init__(self, parent, store, out):
        super().__init__(parent)
        self.setWindowTitle("AI Recovery Suggestions")
        self.resize(720, 520)
        v = QVBoxLayout(self)
        res = out["result"]
        head = (f"{out['summary']}\n\n" if out["summary"] else "") + \
            ("With these steps the job meets the target "
             f"({res['forecast']:%b %d, %Y})." if res["on_time"] else
             f"With these steps the job is still {res['behind']} "
             f"workday(s) late ({res['forecast']:%b %d, %Y})."
             if res["forecast"] and res["behind"] is not None else "")
        lab = QLabel(head)
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.list = QListWidget()
        acts = {a["_id"]: a for a in store.list("activity")}
        for s in out["steps"]:
            a = acts.get(s["id"], {})
            t = (f"{a.get('_no', '')} {a.get('name', '')} - "
                 f"{recovery.TECHNIQUES.get(s['technique'])}: "
                 f"{recovery.describe(store, s)}")
            extra = "  ".join(x for x in (
                f"How: {s.get('how')}" if s.get("how") else "",
                f"Why: {s.get('why')}" if s.get("why") else "",
                f"Risk: {s.get('risk')}" if s.get("risk") else "") if x)
            if s.get("needs_ok"):
                t = "[needs PM OK - drops a logic link] " + t
            it = QListWidgetItem(t + ("\n   " + extra if extra else ""))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            # a resequence changes the logic: off until the PM ticks it
            it.setCheckState(Qt.Unchecked if s.get("needs_ok")
                             else Qt.Checked)
            it.setData(Qt.UserRole, s)
            self.list.addItem(it)
        v.addWidget(self.list, 1)
        if out.get("error"):
            er = QLabel(f"The AI stopped at round {out.get('failed_round')}"
                        f": {out['error']} - the steps above are from the "
                        "rounds before.")
            er.setWordWrap(True)
            er.setObjectName("muted")
            v.addWidget(er)
        if out["rejected"]:
            rj = QLabel("Not usable (checked against the schedule): " +
                        "; ".join(out["rejected"][:8]))
            rj.setWordWrap(True)
            rj.setObjectName("muted")
            v.addWidget(rj)
        note = QLabel("AI suggestions are a starting point: confirm every "
                      "step with the sub before it goes to the owner.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        v.addWidget(note)
        h = QHBoxLayout()
        h.addStretch(1)
        add = QPushButton("Add Checked to Plan")
        add.setObjectName("primary")
        add.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        h.addWidget(add)
        h.addWidget(cancel)
        v.addLayout(h)

    def chosen(self):
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                s = dict(it.data(Qt.UserRole))
                s.pop("needs_ok", None)          # ticked = the PM's OK
                out.append(s)
        return out


class RecoveryDialog(QDialog):
    def __init__(self, store, parent=None, center=None, ask=None):
        super().__init__(parent)
        self.store, self.center, self.ask = store, center, ask
        self.setWindowTitle("Recovery Schedule")
        self.resize(1100, 700)
        self.plan = recovery.load(store)
        self._loading = False
        self._closed = False
        self._worker = None
        v = QVBoxLayout(self)
        # -- where the job stands
        top = QHBoxLayout()
        f = QFormLayout()
        self.target = QDateEdit()
        self.target.setCalendarPopup(True)
        self.target.setDisplayFormat("MMM d, yyyy")
        t = recovery._d(self.plan.get("target"))
        self.target.setDate(_qdate(t))
        self.target.dateChanged.connect(self._target_changed)
        f.addRow("Contract / target completion", self.target)
        self.cause = QComboBox()
        self.cause.addItem("(pick the cause)", "")
        for k, label, _side in recovery.CAUSES:
            self.cause.addItem(label, k)
        i = self.cause.findData(self.plan.get("cause") or "")
        self.cause.setCurrentIndex(max(0, i))
        self.cause.currentIndexChanged.connect(self._meta_changed)
        f.addRow("Cause of the delay", self.cause)
        self.note = QLineEdit(self.plan.get("cause_note") or "")
        self.note.setPlaceholderText("What happened, when, and the "
                                     "records that show it (RFIs, daily "
                                     "logs, weather)")
        self.note.textChanged.connect(self._meta_changed)
        f.addRow("Details", self.note)
        top.addLayout(f, 3)
        self.stand = QLabel()
        self.stand.setWordWrap(True)
        self.stand.setObjectName("calcResult")
        top.addWidget(self.stand, 2)
        v.addLayout(top)
        # -- the critical path still to do
        mid = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Critical path still to do</b> "
                              "(double-click to add a step)"))
        self.crit = QListWidget()
        self.crit.itemDoubleClicked.connect(
            lambda it: self.add_step(it.data(Qt.UserRole)))
        left.addWidget(self.crit, 1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setMaximumWidth(320)
        mid.addWidget(lw)
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Recovery plan</b>"))
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        right.addWidget(self.table, 1)
        row = QHBoxLayout()
        b = QPushButton("+ Step")
        b.clicked.connect(lambda: self.add_step())
        row.addWidget(b)
        b = QPushButton("Remove Step")
        b.clicked.connect(self.remove_step)
        row.addWidget(b)
        b = QPushButton("Suggest Steps")
        b.setToolTip("Crash the longest critical activities and overlap "
                     "critical links until the target is met")
        b.clicked.connect(self.suggest)
        row.addWidget(b)
        self.ai_btn = QPushButton("AI Helper…")
        self.ai_btn.setToolTip("The local AI proposes steps; each is "
                               "checked against the schedule before you "
                               "see it")
        self.ai_btn.clicked.connect(lambda: self.ai_help())
        row.addWidget(self.ai_btn)
        row.addStretch(1)
        right.addLayout(row)
        self.limits = QPlainTextEdit()
        self.limits.setPlaceholderText(
            "Limits for the AI helper, e.g. \"No second crew on footings. "
            "Saturdays OK. Owner won't allow night work.\"")
        self.limits.setMaximumHeight(54)
        right.addWidget(self.limits)
        rw = QWidget()
        rw.setLayout(right)
        mid.addWidget(rw, 1)
        v.addLayout(mid, 1)
        # -- the result
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setObjectName("calcResult")
        v.addWidget(self.result)
        bot = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("muted")
        bot.addWidget(self.status, 1)
        b = QPushButton("Save Draft")
        b.clicked.connect(self.save)
        bot.addWidget(b)
        b = QPushButton("Recovery Report (PDF)…")
        b.clicked.connect(lambda: self.report())
        bot.addWidget(b)
        self.apply_btn = QPushButton("Apply to Schedule…")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(lambda: self.apply())
        bot.addWidget(self.apply_btn)
        self.revert_btn = QPushButton("Revert Applied Plan…")
        self.revert_btn.setToolTip("Put back the durations, links and "
                                   "notes the last applied plan changed")
        self.revert_btn.clicked.connect(lambda: self.revert())
        bot.addWidget(self.revert_btn)
        b = QPushButton("Close")
        b.clicked.connect(self.close_dialog)
        bot.addWidget(b)
        v.addLayout(bot)
        self._fill_critical()
        self._fill_table()
        self.recalc()

    # ---------------------------------------------------------- model
    def _acts(self):
        return self.store.list("activity")

    def _fill_critical(self):
        st = recovery.standing(self.store, self.plan.get("target"))
        self.crit.clear()
        for r in st["critical"]:
            it = QListWidgetItem(f"{r.get('_no', '')}  {r.get('name', '')}"
                                 f"  ({int(r.get('dur') or 0)}d, "
                                 f"{r['es']:%b %d}-{r['ef']:%b %d})")
            it.setData(Qt.UserRole, r["_id"])
            self.crit.addItem(it)

    def _fill_table(self):
        self._loading = True
        self.table.setRowCount(0)
        for s in self.plan.get("steps") or []:
            self._add_row(s)
        self._loading = False

    def _add_row(self, s):
        acts = self._acts()
        by = {a["_id"]: a for a in acts}
        r = self.table.rowCount()
        self.table.insertRow(r)
        act = QComboBox()
        for a in acts:
            if a.get("status") != "Complete":
                act.addItem(f"{a.get('_no', '')} {a.get('name', '')}",
                            a["_id"])
        act.setCurrentIndex(max(0, act.findData(s.get("id"))))
        tech = QComboBox()
        for k, label in recovery.TECHNIQUES.items():
            tech.addItem(label, k)
        tech.setCurrentIndex(max(0, tech.findData(s.get("technique"))))
        days = QSpinBox()
        days.setRange(0, 9999)
        a = by.get(s.get("id")) or {}
        days.setValue(int(s.get("duration") if s.get("duration")
                          is not None else int(float(a.get("duration")
                                                     or 0))))
        pred = QComboBox()
        over = QSpinBox()
        over.setRange(0, 999)
        over.setValue(int(s.get("overlap") or 0))
        how = QLineEdit(s.get("how") or "")
        cost = QDoubleSpinBox()
        cost.setRange(0, 1e9)
        cost.setDecimals(0)
        cost.setPrefix("$")
        cost.setValue(float(s.get("cost") or 0))
        agreed = QCheckBox()
        agreed.setChecked(bool(s.get("agreed")))
        for c, w in enumerate((act, tech, days, pred, over, how, cost,
                               agreed)):
            self.table.setCellWidget(r, c, w)
        self._fill_preds(r, s.get("pred"))
        act.currentIndexChanged.connect(lambda *_: self._row_changed(r,
                                                                    True))
        tech.currentIndexChanged.connect(lambda *_: self._row_changed(r))
        for w in (days, over, cost):
            w.valueChanged.connect(lambda *_: self._row_changed(r))
        pred.currentIndexChanged.connect(lambda *_: self._row_changed(r))
        how.textChanged.connect(lambda *_: self._row_changed(r))
        agreed.toggled.connect(lambda *_: self._row_changed(r))
        self._enable(r)

    def _w(self, r, c):
        return self.table.cellWidget(r, c)

    def _fill_preds(self, r, want=None):
        acts = self._acts()
        by = {a["_id"]: a for a in acts}
        a = by.get(self._w(r, 0).currentData())
        box = self._w(r, 3)
        box.blockSignals(True)
        box.clear()
        for _i, pid, name, typ, _lag in (recovery.preds_of(acts, a)
                                         if a else []):
            box.addItem(f"{by[pid].get('_no', '')} {name} ({typ})", pid)
        if want:
            box.setCurrentIndex(max(0, box.findData(want)))
        box.blockSignals(False)

    def _enable(self, r):
        t = self._w(r, 1).currentData()
        self._w(r, 2).setEnabled(t == "crash")
        self._w(r, 3).setEnabled(t in ("fast_track", "resequence"))
        self._w(r, 4).setEnabled(t == "fast_track")

    def _row_changed(self, r, act_changed=False):
        if self._loading:
            return
        if act_changed:
            a = self.store.get("activity", self._w(r, 0).currentData()) or {}
            self._w(r, 2).blockSignals(True)
            self._w(r, 2).setValue(int(float(a.get("duration") or 0)))
            self._w(r, 2).blockSignals(False)
            self._fill_preds(r)
        self._enable(r)
        self._read_table()
        self.recalc()

    def _read_table(self):
        steps = []
        old = self.plan.get("steps") or []
        acts = {a["_id"]: a for a in self._acts()}
        for r in range(self.table.rowCount()):
            t = self._w(r, 1).currentData()
            rid = self._w(r, 0).currentData()
            s = dict(old[r]) if r < len(old) else {}
            s.update({"id": rid, "technique": t,
                      "how": self._w(r, 5).text(),
                      "cost": self._w(r, 6).value(),
                      "agreed": self._w(r, 7).isChecked()})
            for k in ("duration", "was", "pred", "overlap"):
                s.pop(k, None)
            if t == "crash":
                s["duration"] = self._w(r, 2).value()
                s["was"] = int(float((acts.get(rid) or {}).get("duration")
                                     or 0))
            if t in ("fast_track", "resequence"):
                s["pred"] = self._w(r, 3).currentData()
            if t == "fast_track":
                s["overlap"] = self._w(r, 4).value()
            steps.append(s)
        self.plan["steps"] = steps

    def _target_changed(self, *_):
        self.plan["target"] = _pydate(self.target.date()).isoformat()
        self._fill_critical()
        self.recalc()

    def _meta_changed(self, *_):
        self.plan["cause"] = self.cause.currentData() or ""
        self.plan["cause_note"] = self.note.text()

    # ---------------------------------------------------------- actions
    def recalc(self):
        ev = recovery.evaluate(self.store, self.plan)
        before = ev["before"]
        if ev["was"] and ev["target"]:
            self.stand.setText(
                f"Forecast completion: <b>{ev['was']:%b %d, %Y}</b><br>" +
                (f"<span style='color:#c0392b'><b>{before} workday(s) "
                 "behind</b></span>" if before and before > 0 else
                 "<b>On time</b> - no recovery needed"))
        else:
            self.stand.setText("Set the contract / target completion date.")
        if not (self.plan.get("steps")):
            self.result.setText("Add steps, Suggest Steps, or ask the AI "
                                "Helper.")
        elif ev["forecast"]:
            self.result.setText(
                f"With this plan: completion <b>{ev['forecast']:%b %d, %Y}"
                f"</b> - {ev['recovered']} workday(s) recovered - " +
                ("<b style='color:#1e8449'>meets the target</b>"
                 if ev["on_time"] else
                 f"<b style='color:#c0392b'>still {ev['behind']} "
                 "workday(s) late</b>") +
                f"<br>Added cost ${ev['cost']:,.0f}" +
                (f" - {ev['not_agreed']} step(s) not yet agreed with the "
                 "sub" if ev["not_agreed"] else ""))
        self.status.setText(
            ("Applied " + str(self.plan.get("applied")) if
             self.plan.get("status") == "Applied" else
             "Draft - the schedule hasn't changed") +
            ("" if not ev.get("notes") else " - " + "; ".join(ev["notes"])))
        self.revert_btn.setEnabled(
            recovery.last_applied(self.store) is not None)
        return ev

    def add_step(self, rid=None, step=None):
        s = step or {"id": rid, "technique": "crash", "cost": 0,
                     "agreed": False}
        if rid is None and step is None:
            first = self.crit.item(0)
            s["id"] = first.data(Qt.UserRole) if first else None
        if s.get("id") is None:
            return None
        if s["technique"] == "crash" and s.get("duration") is None:
            a = self.store.get("activity", s["id"]) or {}
            n = int(float(a.get("duration") or 0))
            s["duration"], s["was"] = max(1, n - 1), n
        self.plan.setdefault("steps", []).append(s)
        self._loading = True
        self._add_row(s)
        self._loading = False
        self._read_table()
        return self.recalc()

    def remove_step(self):
        r = self.table.currentRow()
        if r < 0:
            r = self.table.rowCount() - 1
        if r < 0:
            return
        self.table.removeRow(r)
        self.plan["steps"].pop(r)
        self._fill_table()
        self.recalc()

    def suggest(self):
        target = recovery._d(self.plan.get("target"))
        draft = recovery.suggest(self.store, target)
        have = {(s.get("id"), s.get("technique"), s.get("pred"))
                for s in self.plan.get("steps") or []}
        for s in draft["steps"]:
            if (s.get("id"), s.get("technique"), s.get("pred")) not in have:
                self.plan["steps"].append(s)
        self._fill_table()
        return self.recalc()

    def ai_help(self, wait=False, accept=None):
        """Run the AI helper in the background; `accept(out)` (tests)
        picks the proposals instead of the dialog."""
        self._meta_changed()
        if self._closed:
            return None
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("AI working…")
        self._accept = accept
        w = _AIWorker(self.store, self.plan, self.limits.toPlainText(),
                      self.ask)
        self._worker = w
        # bound methods of this dialog: Qt queues them to the GUI thread
        w.done.connect(self._ai_done)
        w.failed.connect(self._ai_failed)
        w.step.connect(self.ai_btn.setText)
        w.start()
        if wait:
            from PySide6.QtWidgets import QApplication
            w.wait()
            for _ in range(5):
                QApplication.processEvents()
        return w

    def _ai_reset(self):
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("AI Helper…")

    def _ai_done(self, out):
        if self._closed:
            return
        self._worker = None
        self._ai_reset()
        if not out["steps"] and out.get("error"):
            self._offer_suggest(out["error"])
            return
        if not out["steps"]:
            QMessageBox.information(
                self, "AI Helper", "The AI had no usable steps." +
                (" Not usable: " + "; ".join(out["rejected"][:5])
                 if out["rejected"] else ""))
            return
        if self._accept is not None:
            picked = [dict(s) for s in self._accept(out)]
            for s in picked:
                s.pop("needs_ok", None)
        else:
            d = AIDialog(self, self.store, out)
            picked = d.chosen() if d.exec() else []
        if self._closed:
            return
        for s in picked:
            self.plan["steps"].append(s)
        self._fill_table()
        self.recalc()

    def _ai_failed(self, msg):
        if self._closed:
            return
        self._worker = None
        self._ai_reset()
        self._offer_suggest(msg)

    def _offer_suggest(self, msg):
        """The AI couldn't answer (Ollama down, model error): offer the
        built-in Suggest Steps instead. Returns True when it ran."""
        box = QMessageBox(QMessageBox.Warning, "AI Helper",
                          f"The AI helper couldn't answer:\n{msg}",
                          QMessageBox.NoButton, self)
        use = box.addButton("Use Suggest Steps instead",
                            QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Close)
        if self._ask_box(box) == use:
            self.suggest()
            return True
        return False

    def _ask_box(self, box):
        """Shows a message box; returns the button clicked (tests patch
        this)."""
        box.exec()
        return box.clickedButton()

    def _stop_worker(self):
        w, self._worker = self._worker, None
        if w is None:
            return
        for sig in (w.done, w.failed, w.step):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass
        w.stop()
        if w.isRunning():
            # keep it alive until the model call returns, so Qt doesn't
            # destroy a running thread with the dialog
            _RUNNING.append(w)
            w.finished.connect(lambda: _RUNNING.remove(w)
                               if w in _RUNNING else None)

    def done(self, r):
        """Closing the dialog (Close, Esc, the window's X) stops the AI
        helper: no proposals window after the dialog is gone."""
        self._closed = True
        self._stop_worker()
        super().done(r)

    def _checkpoint(self):
        """Edit > Undo in any open Scheduler window on this job gets a
        step to go back to before the schedule changes."""
        try:
            from . import scheduler
        except Exception:                           # noqa: BLE001
            return
        for w in list(getattr(scheduler, "_WINDOWS", ())):
            if getattr(w, "store", None) is self.store:
                try:
                    w.checkpoint()
                except Exception:                   # noqa: BLE001
                    pass

    def save(self):
        self._meta_changed()
        recovery.save(self.store, self.plan)
        if self.center is not None:
            self.center.toast("Recovery plan saved (draft)")

    def report(self, path=None):
        self._meta_changed()
        if path is None:
            from ..reportname import report_file_name
            name = report_file_name("Recovery Schedule", self.store.name)
            path, _ = QFileDialog.getSaveFileName(
                self, "Recovery Report",
                os.path.join(self.store.folder, name),
                "PDF (*.pdf)")
        if not path:
            return None
        recovery.export_pdf(self.store, path, self.plan)
        main = getattr(self.center, "main", None) if self.center else None
        if main is not None and not os.environ.get("QUANTISHEET_NO_OPEN"):
            main.open_path(path)
        return path

    def apply(self, confirm=True):
        self._meta_changed()
        ev = recovery.evaluate(self.store, self.plan)
        if not self.plan.get("steps"):
            return 0
        if confirm:
            msg = (f"Change {len(self.plan['steps'])} step(s) in the live "
                   "schedule? The baseline stays as it is, so the recovery "
                   "shows as variance, and each changed activity gets a "
                   "note.")
            if ev["not_agreed"]:
                msg += (f"\n\n{ev['not_agreed']} step(s) aren't agreed "
                        "with the sub yet.")
            if QMessageBox.question(self, "Apply Recovery Plan", msg) != \
                    QMessageBox.Yes:
                return 0
        self._checkpoint()
        n = recovery.apply(self.store, self.plan)
        try:                       # the applied plan joins the record
            from . import schedule_record
            schedule_record.snapshot(self.store, "recovery",
                                     f"Recovery plan applied ({n} changed)")
        except Exception:                           # noqa: BLE001
            pass
        self.plan = recovery.load(self.store)
        self._fill_critical()
        self.recalc()
        if self.center is not None:
            self.center.toast(f"Recovery plan applied: {n} activities "
                              "changed")
        return n

    def revert(self, confirm=True):
        """Undo the last applied plan (recovery.revert_last). Returns the
        number of activities restored, or None."""
        if recovery.last_applied(self.store) is None:
            return None
        if confirm:
            msg = ("Put back the durations, links and notes the last "
                   "applied recovery plan changed? The plan stays as a "
                   "draft.")
            hand = recovery.edited_since(self.store)
            if hand:
                msg += ("\n\nChanged by hand since it was applied (those "
                        "edits are undone too): " + ", ".join(hand[:8]))
            if QMessageBox.question(self, "Revert Recovery Plan", msg) != \
                    QMessageBox.Yes:
                return None
        self._checkpoint()
        n = recovery.revert_last(self.store)
        self.plan = recovery.load(self.store)
        self._fill_critical()
        self._fill_table()
        self.recalc()
        if self.center is not None:
            self.center.toast(f"Recovery plan reverted: {n} activities "
                              "restored")
        return n

    def close_dialog(self):
        self._meta_changed()
        if self.plan.get("status") != "Applied":
            recovery.save(self.store, self.plan)
        self.accept()


def open_recovery(store, parent=None, center=None):
    d = RecoveryDialog(store, parent, center)
    d.show()
    return d
