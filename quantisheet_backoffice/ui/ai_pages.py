"""Phase 3 pages (M4): Assistant (P3-01 / P3-06, with the P3-05 bank-line
and reconciliation suggestions and the AI activity log), Sync Center
(P3-02 / P3-03) and the WIP report box used on Books & Reports (P3-04).

Building a page never contacts the model; only the buttons do, and only
the local one. Each model call runs off the UI thread (OffThread) with a
Cancel button; the database work stays on the UI thread. Nothing is
posted, applied or matched without a click on Accept / Apply / Finish."""
import json
import threading

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QTabWidget,
                               QTextEdit, QVBoxLayout, QWidget)

from .. import (actions, aicat, aitrail, assistant, banking, cents, clock,
                connectors, erpsync, ledger, localai, reconcile, wip)
from .common import error, fill, heading, money, table

WARNING = "AI suggestions can be wrong; check before accepting."
PLACEHOLDER = "Ask a question or give a command"


def ai_status_text() -> str:
    cfg = localai.config()
    if not cfg["model"]:
        return ("AI is unavailable: no local model chosen (Settings > AI). "
                "Every report still runs from the menus; the box offers a "
                "plain search.")
    return (f"Local AI: {cfg['model']} at {cfg['url']} (this PC only). "
            "Suggestions only; nothing changes until you click Apply or "
            "Accept.")


class OffThread:
    """Runs one blocking call (an HTTP request to the local model) on a
    worker thread while the UI keeps painting; Cancel abandons it."""

    def __init__(self):
        self.cancel = threading.Event()
        self.busy = False

    def __call__(self, fn):
        box = {}

        def work():
            try:
                box["r"] = fn()
            except BaseException as e:                    # noqa: BLE001
                box["e"] = e
        t = threading.Thread(target=work, daemon=True)
        t.start()
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(
            lambda: loop.quit() if (not t.is_alive() or self.cancel.is_set())
            else None)
        timer.start(25)
        if t.is_alive() and not self.cancel.is_set():
            loop.exec()
        timer.stop()
        if self.cancel.is_set() and t.is_alive():
            raise localai.Cancelled("Cancelled.")
        if "e" in box:
            raise box["e"]
        return box["r"]


def _text(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, (list, tuple)):
        return "; ".join(_text(x) for x in v)
    if isinstance(v, dict):
        if "lines" in v and isinstance(v["lines"], list):
            return _text(v["lines"])
        return ", ".join(f"{k} {_text(x)}" for k, x in v.items())
    return str(v)


class AssistantPage(QWidget):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        self.worker = OffThread()
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Assistant"))
        self.status = QLabel(ai_status_text())
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.warning = QLabel(WARNING)
        lay.addWidget(self.warning)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        can = office.can("ai.use")
        bank_ok = office.can("bank.edit") and office.mode == "full"

        # ask
        ask = QWidget()
        al = QVBoxLayout(ask)
        row = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText(PLACEHOLDER)
        self.q.setToolTip(assistant.HELP)
        self.ask_btn = QPushButton("Ask")
        self.ask_btn.setEnabled(can)
        self.ask_btn.clicked.connect(self.ask)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        row.addWidget(self.q, 1)
        row.addWidget(self.ask_btn)
        row.addWidget(self.cancel_btn)
        al.addLayout(row)
        self.answer = QTextEdit()
        self.answer.setReadOnly(True)
        al.addWidget(self.answer, 1)
        al.addWidget(QLabel("Plain search results"))
        self.search_t = table(["Type", "Record"])
        al.addWidget(self.search_t)
        self.tabs.addTab(ask, "Ask the books")

        # findings
        fw = QWidget()
        fl = QVBoxLayout(fw)
        self.find_t = table(["Kind", "What", "Records"])
        fl.addWidget(self.find_t, 1)
        b = QPushButton("Refresh findings")
        b.setEnabled(can)
        b.clicked.connect(self.load_findings)
        r2 = QHBoxLayout()
        r2.addWidget(b)
        self.rem_btn = QPushButton("Draft reminder (you send it)")
        self.rem_btn.setEnabled(can)
        self.rem_btn.clicked.connect(self.draft_reminder)
        r2.addWidget(self.rem_btn)
        fl.addLayout(r2)
        self.tabs.addTab(fw, "Findings")

        # suggestions + undo history
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.addWidget(QLabel("Suggested changes: the before/after list. "
                            "Nothing changes until Apply; each can be "
                            "undone."))
        self.sug_t = table(["#", "Kind", "Before", "After"])
        sl.addWidget(self.sug_t, 1)
        r3 = QHBoxLayout()
        self.apply_btn = QPushButton("Apply")
        self.dismiss_btn = QPushButton("Dismiss")
        for bb, fn in ((self.apply_btn, self.apply),
                       (self.dismiss_btn, self.dismiss)):
            bb.setEnabled(can)
            bb.clicked.connect(fn)
            r3.addWidget(bb)
        sl.addLayout(r3)
        sl.addWidget(QLabel("Undo history"))
        self.hist_t = table(["#", "Kind", "Status", "By", "When"])
        sl.addWidget(self.hist_t, 1)
        self.undo_btn = QPushButton("Undo selected")
        self.undo_btn.setEnabled(can)
        self.undo_btn.clicked.connect(self.undo)
        sl.addWidget(self.undo_btn)
        self.tabs.addTab(sw, "Suggestions")

        # bank lines (P3-05)
        bw = QWidget()
        bl = QVBoxLayout(bw)
        bl.addWidget(QLabel(WARNING))
        self.bank_t = table(["Line", "Date", "Payee", "Amount", "Status",
                             "Suggestion", "Account", "Confidence", "Why"],
                            money_cols=(3,))
        bl.addWidget(self.bank_t, 1)
        r4 = QHBoxLayout()
        self.suggest_btn = QPushButton("Suggest categories")
        self.accept_btn = QPushButton("Accept selected")
        self.bulk_btn = QPushButton("Accept AI at or above threshold")
        self.dismiss_bank_btn = QPushButton("Dismiss selected")
        self.undo_accept_btn = QPushButton("Undo accept")
        self.cancel_bank_btn = QPushButton("Cancel")
        self.cancel_bank_btn.setEnabled(False)
        self.cancel_bank_btn.clicked.connect(self.cancel)
        for bb, fn in ((self.suggest_btn, self.suggest_bank),
                       (self.accept_btn, self.accept_bank),
                       (self.bulk_btn, self.accept_bulk),
                       (self.dismiss_bank_btn, self.dismiss_bank),
                       (self.undo_accept_btn, self.undo_accept)):
            bb.setEnabled(bank_ok)
            bb.clicked.connect(fn)
            r4.addWidget(bb)
        r4.addWidget(self.cancel_bank_btn)
        bl.addLayout(r4)
        self.tabs.addTab(bw, "Bank suggestions")

        # reconciliation suggestions (P3-05)
        rw = QWidget()
        rl = QVBoxLayout(rw)
        rr = QHBoxLayout()
        self.rec_bank = QComboBox()
        if office.mode == "full":
            for b_ in office.db.rows("SELECT id, name FROM bank_accounts "
                                     "WHERE deleted = 0 ORDER BY name"):
                self.rec_bank.addItem(b_["name"], b_["id"])
        self.rec_end = QLineEdit(clock.today().isoformat())
        self.rec_bal = QLineEdit()
        self.rec_bal.setPlaceholderText("Statement ending balance")
        self.rec_start_btn = QPushButton("Start reconciliation")
        self.rec_suggest_btn = QPushButton("Suggest matches")
        self.rec_apply_btn = QPushButton("Apply matches")
        self.rec_finish_btn = QPushButton("Finish")
        for w_ in (self.rec_bank, QLabel("Period end"), self.rec_end,
                   self.rec_bal):
            rr.addWidget(w_)
        rl.addLayout(rr)
        rb = QHBoxLayout()
        for bb, fn in ((self.rec_start_btn, self.rec_start),
                       (self.rec_suggest_btn, self.rec_suggest),
                       (self.rec_apply_btn, self.rec_apply),
                       (self.rec_finish_btn, self.rec_finish)):
            bb.setEnabled(bank_ok)
            bb.clicked.connect(fn)
            rb.addWidget(bb)
        rl.addLayout(rb)
        self.rec_label = QLabel("")
        rl.addWidget(self.rec_label)
        self.rec_t = table(["Item", "Amount", "Confidence", "Why"],
                           money_cols=(1,))
        rl.addWidget(self.rec_t, 1)
        rl.addWidget(QLabel("'Ready to finish' means every line has an "
                            "accepted match and the difference is $0.00; "
                            "you still click Finish."))
        self.tabs.addTab(rw, "Reconciliation")
        self.rid = None
        self._recs = []

        # AI activity log (P3-05)
        lw = QWidget()
        ll = QVBoxLayout(lw)
        self.log_t = table(["#", "When", "Kind", "Layer", "Model", "Version",
                            "Record", "Suggestion", "Confidence", "Why",
                            "Status", "By", "Decided"])
        ll.addWidget(self.log_t, 1)
        self.log_btn = QPushButton("Refresh AI activity log")
        self.log_btn.setEnabled(can)
        self.log_btn.clicked.connect(self.load_log)
        ll.addWidget(self.log_btn)
        self.tabs.addTab(lw, "AI activity log")

        self._findings = []
        self._lines = []
        if can:
            self.load_suggestions()
            self.load_bank()
            self.load_log()

    # ---- model calls off the UI thread ----
    def _client(self):
        c = localai.client()
        if c is not None:
            self.worker.cancel = threading.Event()
            c.cancel = self.worker.cancel
            c.runner = self.worker
        return c

    def _busy(self, on):
        self.worker.busy = on
        self.ask_btn.setEnabled(not on and self.office.can("ai.use"))
        self.suggest_btn.setEnabled(not on and self.office.can("bank.edit")
                                    and self.office.mode == "full")
        self.cancel_btn.setEnabled(on)
        self.cancel_bank_btn.setEnabled(on)

    def cancel(self):
        self.worker.cancel.set()

    # ---- ask ----
    def ask(self):
        if self.worker.busy:
            return
        self._busy(True)
        try:
            a = assistant.ask(self.office, self.q.text(), client=self._client())
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return
        finally:
            self._busy(False)
        cites = ", ".join(a["records"][:20]) + (" ..." if len(a["records"]) >
                                                20 else "")
        rep = a.get("report")
        head = (f"Report: {rep['name']} ({rep['basis']}), {rep['from']} to "
                f"{rep['to']}\n\n" if rep else "")
        self.answer.setPlainText(f"{head}{a['text']}\n\nRecords used: "
                                 f"{cites or '(none)'}\nRouted by: "
                                 f"{a['routed_by']}")
        fill(self.search_t, [(x["type"], x["label"])
                             for x in a.get("search") or []])
        if a.get("action_id"):
            self.tabs.setCurrentIndex(2)
        self.load_suggestions()

    # ---- findings ----
    def load_findings(self):
        try:
            self._findings = assistant.findings(self.office)
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return
        fill(self.find_t, [(f["kind"], f["text"], ", ".join(f["records"]))
                           for f in self._findings])

    def draft_reminder(self):
        i = self.find_t.currentRow()
        if 0 <= i < len(self._findings):
            assistant.draft_reminder(self.office, self._findings[i])
            self.load_suggestions()

    # ---- suggestions ----
    def load_suggestions(self):
        self._pending = actions.pending(self.office)
        fill(self.sug_t, [(a["id"], a["kind"], _text(a["before"]),
                           _text(a["after"])) for a in self._pending])
        self._hist = actions.history(self.office)
        fill(self.hist_t, [(a["id"], a["kind"], a["status"],
                            a["undone_by"] or a["applied_by"] or "",
                            a["undone_at"] or a["applied_at"] or "")
                           for a in self._hist])

    def _pick(self, t, rows):
        i = t.currentRow()
        return rows[i]["id"] if 0 <= i < len(rows) else None

    def apply(self):
        aid = self._pick(self.sug_t, self._pending)
        if aid:
            try:
                actions.apply(self.office, aid)
            except Exception as e:                        # noqa: BLE001
                error(self, e)
            self.load_suggestions()

    def dismiss(self):
        aid = self._pick(self.sug_t, self._pending)
        if aid:
            actions.dismiss(self.office, aid)
            self.load_suggestions()

    def undo(self):
        aid = self._pick(self.hist_t, self._hist)
        if aid:
            try:
                actions.undo(self.office, aid)
            except Exception as e:                        # noqa: BLE001
                error(self, e)
            self.load_suggestions()

    # ---- bank lines ----
    def load_bank(self):
        if self.office.mode != "full":
            self._lines = []
            return
        # the review queue, plus accepted AI lines not yet reconciled so
        # 'Undo accept' can reach them
        self._lines = banking.review_queue(self.office) + [
            banking.line(self.office, r["id"]) for r in self.office.db.rows(
                "SELECT id, suggestion FROM statement_lines WHERE deleted = 0 "
                "AND status = 'Accepted' AND reconciliation_id IS NULL "
                "AND suggestion LIKE '%\"kind\": \"ai\"%' ORDER BY date, id")]
        rows = []
        for ln in self._lines:
            s = ln["suggestion"] or {}
            kind = s.get("kind", "")
            badge = "AI suggested" if kind == "ai" else kind
            if kind == "ai" and s.get("low"):
                badge += " (below threshold)"
            acct = ""
            if s.get("account_id"):
                a = ledger.account(self.office, s["account_id"])
                acct = f"{a['number']} {a['name']}"
            rows.append((ln["id"], ln["date"], ln["payee"], ln["amount"],
                         ln["status"], badge, acct, s.get("confidence", ""),
                         s.get("reason", "")))
        fill(self.bank_t, rows, money_cols=(3,))

    def suggest_bank(self):
        if self.worker.busy:
            return
        self._busy(True)
        try:
            n = aicat.suggest_queue(self.office, client=self._client(),
                                    cancelled=self.worker.cancel.is_set)
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return
        finally:
            self._busy(False)
        msg = ai_status_text()
        if not n["model_available"]:
            msg += ("  AI is unavailable: rules and similar lines only.")
        if n.get("cancelled"):
            msg += "  Cancelled; lines done so far keep their suggestions."
        self.status.setText(msg)
        self.load_bank()
        self.load_log()

    def _line(self):
        i = self.bank_t.currentRow()
        return self._lines[i]["id"] if 0 <= i < len(self._lines) else None

    def _bank_do(self, fn):
        lid = self._line()
        if lid:
            try:
                fn(self.office, lid)
            except Exception as e:                        # noqa: BLE001
                error(self, e)
            self.load_bank()
            self.load_log()

    def accept_bank(self):
        self._bank_do(banking.accept)

    def dismiss_bank(self):
        self._bank_do(aicat.dismiss)

    def undo_accept(self):
        self._bank_do(aicat.undo_accept)

    def accept_bulk(self):
        try:
            r = aicat.accept_bulk(self.office)
            self.status.setText(f"Accepted {len(r['accepted'])} AI "
                                f"suggestion(s) at or above "
                                f"{r['threshold']}; {r['below_threshold']} "
                                f"left for review. Each can be undone.")
        except Exception as e:                            # noqa: BLE001
            error(self, e)
        self.load_bank()
        self.load_log()

    # ---- reconciliation ----
    def _rec_show(self, st=None):
        st = st or reconcile.status(self.office, self.rid)
        self.rec_label.setText(f"Difference {st['difference_text']} - "
                               f"{st['label']}")

    def rec_start(self):
        cur = self.office.db.one(
            "SELECT id FROM reconciliations WHERE bank_account_id = ? AND "
            "status = 'Open' AND deleted = 0", (self.rec_bank.currentData(),))
        if cur:
            self.rid = cur["id"]
            self._rec_show()
            return
        try:
            self.rid = reconcile.start(self.office, self.rec_bank.currentData(),
                                       self.rec_end.text().strip(),
                                       self.rec_bal.text().strip())
            self._rec_show()
        except Exception as e:                            # noqa: BLE001
            error(self, e)

    def rec_suggest(self):
        if not self.rid:
            return
        try:
            r = aicat.run_recon_suggestions(self.office, self.rid)
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return
        self._recs = r["suggestions"]
        fill(self.rec_t, [(s["line_id"], s["amount"], s["confidence"],
                           s["reason"]) for s in self._recs],
             money_cols=(1,))
        self.rec_label.setText(r["label"] + " (if applied)")
        self.load_log()

    def rec_apply(self):
        if not self.rid or not self._recs:
            return
        try:
            st = aicat.apply_recon(self.office, self.rid,
                                   [s["ai_log_id"] for s in self._recs])
            self._rec_show(st)
        except Exception as e:                            # noqa: BLE001
            error(self, e)
        self.load_log()

    def rec_finish(self):
        if not self.rid:
            return
        try:
            reconcile.finish(self.office, self.rid)
            self._rec_show()
        except Exception as e:                            # noqa: BLE001
            error(self, e)

    # ---- AI activity log ----
    def load_log(self):
        rows = []
        for r in self.office.db.rows("SELECT * FROM ai_log ORDER BY id DESC "
                                     "LIMIT 500"):
            prop = json.loads(r["proposal"] or "null")
            rows.append((r["id"], (r["created_at"] or "")[:16], r["kind"],
                         r["layer"], r["model"] or "", r["model_version"] or
                         "", f"{r['record_type']} {r['record_id']}",
                         _text(prop), r["confidence"], r["reason"],
                         r["status"], r["decided_by"] or "",
                         (r["decided_at"] or "")[:16]))
        fill(self.log_t, rows)


class SyncPage(QWidget):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Sync Center"))
        lay.addWidget(QLabel("File-based sync with your accounting system: "
                             "import its exports, review the differences, "
                             "apply after review. Nothing is renamed or "
                             "overwritten automatically."))
        last = erpsync.last_runs(office)
        self.sys_t = table(["System", "Last import", "Last export",
                            "Connection"])
        fill(self.sys_t, [(s, (d["import"] or {}).get("created_at", "")[:16],
                           (d["export"] or {}).get("created_at", "")[:16],
                           connectors.status(office, s))
                          for s, d in last.items()])
        lay.addWidget(self.sys_t)
        row = QHBoxLayout()
        self.system = QComboBox()
        self.system.addItems(erpsync.SYSTEMS)
        self.kind = QComboBox()
        self.kind.addItems(erpsync.RECORD_TYPES)
        self.imp = QPushButton("Import export file…")
        self.imp.setEnabled(office.can("sync.run"))
        self.imp.clicked.connect(self.import_file)
        for w in (self.system, self.kind, self.imp):
            row.addWidget(w)
        lay.addLayout(row)
        self.items_t = table(["Kind", "Key", "In the file", "Here", "Why"])
        lay.addWidget(self.items_t, 1)
        r2 = QHBoxLayout()
        self.confirm_btn = QPushButton("Confirm match")
        self.confirm_btn.clicked.connect(self.confirm)
        self.apply_btn = QPushButton("Apply (add selected new vendors)")
        self.apply_btn.clicked.connect(self.apply)
        for b in (self.confirm_btn, self.apply_btn):
            b.setEnabled(office.can("sync.run"))
            r2.addWidget(b)
        lay.addLayout(r2)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        lay.addWidget(self.report, 1)
        self.run = None
        self._items = []
        runs = erpsync.runs(office)
        if runs:
            self.show_run(runs[0]["id"])
        lay.addWidget(QLabel("QuickBooks is a trademark of Intuit Inc. "
                             "QuantiSheet is not affiliated with or endorsed "
                             "by Intuit."))

    def show_run(self, rid):
        self.run = erpsync.run(self.office, rid)
        d = self.run["differences"] or {}
        self._items = []
        for kind in ("likely", "new", "changed", "rejected"):
            for x in d.get(kind, []):
                self._items.append((kind, x))
        fill(self.items_t, [(k, x.get("erp_key") or x.get("key", ""),
                             x.get("erp_name", ""), x.get("local_name", ""),
                             x.get("reason") or x.get("score", ""))
                            for k, x in self._items])
        self.report.setPlainText("\n".join(erpsync.report(self.office, rid)))

    def _sel(self):
        rows = sorted({i.row() for i in self.items_t.selectedIndexes()})
        return [self._items[r] for r in rows if 0 <= r < len(self._items)]

    def confirm(self):
        for kind, x in self._sel():
            if kind != "likely":
                continue
            try:
                erpsync.confirm_match(self.office, self.run["id"],
                                      x["erp_key"], x["local_id"])
            except Exception as e:                        # noqa: BLE001
                error(self, e)
        if self.run:
            self.show_run(self.run["id"])

    def apply(self):
        if not self.run:
            return
        keys = [x["erp_key"] for k, x in self._sel() if k == "new"]
        try:
            erpsync.apply(self.office, self.run["id"], keys)
        except Exception as e:                            # noqa: BLE001
            error(self, e)
        self.show_run(self.run["id"])

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Accounting system export", "",
            "Export files (*.csv *.txt *.xlsx)")
        if not path:
            return
        try:
            r = erpsync.import_file(self.office, self.system.currentText(),
                                    self.kind.currentText(), path=path)
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return
        self.show_run(r["id"])


class WipBox(QWidget):
    """Reports > WIP: as-of table with Excel and PDF, and the estimate
    override for the selected job."""

    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Work in progress (over/under billing)"))
        row = QHBoxLayout()
        self.as_of = QLineEdit(clock.today().isoformat())
        row.addWidget(QLabel("As of"))
        row.addWidget(self.as_of)
        for text, fn in (("Refresh", self.load), ("Excel…", self.xlsx),
                         ("PDF…", self.pdf)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.t = table(wip.HEADERS, money_cols=(2, 3, 4, 6, 7, 8))
        lay.addWidget(self.t)
        er = QHBoxLayout()
        self.est = QLineEdit()
        self.est.setPlaceholderText("Estimated cost for the selected job "
                                    "(empty = use the forecast)")
        self.est_btn = QPushButton("Set estimate")
        self.est_btn.setEnabled(office.can("settings.edit"))
        self.est_btn.clicked.connect(self.set_estimate)
        er.addWidget(self.est, 1)
        er.addWidget(self.est_btn)
        lay.addLayout(er)
        self.rows = []
        self.load()

    def load(self):
        self.rows = wip.wip(self.office, self.as_of.text().strip())
        fill(self.t, [(r["number"], r["name"], r["contract"],
                       r["estimated_cost"], r["cost_to_date"],
                       ("n/a - estimate needed" if r.get("estimate_needed")
                        else r["pct_complete"] + "%"), r["earned"],
                       r["billed"], r["over_under"], r["estimate_source"])
                      for r in self.rows],
             money_cols=(2, 3, 4, 6, 7, 8))

    def set_estimate(self):
        i = self.t.currentRow()
        if not 0 <= i < len(self.rows):
            return
        try:
            wip.set_estimate(self.office, self.rows[i]["job_id"],
                             self.est.text().strip(), "set on the WIP report")
        except Exception as e:                            # noqa: BLE001
            error(self, e)
        self.load()

    def xlsx(self):
        try:
            p = wip.to_xlsx(self.office, self.as_of.text().strip())
            error(self, f"Saved {p}")
        except Exception as e:                            # noqa: BLE001
            error(self, e)

    def pdf(self):
        try:
            p = wip.to_pdf(self.office, self.as_of.text().strip())
            error(self, f"Saved {p}")
        except Exception as e:                            # noqa: BLE001
            error(self, e)


__all__ = ["AssistantPage", "SyncPage", "WipBox", "ai_status_text", "money",
           "OffThread", "WARNING", "PLACEHOLDER", "cents"]
