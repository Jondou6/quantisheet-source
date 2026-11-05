"""The claim estimate window (brief 3.4). A QMainWindow with a list of
open claims on the left and eight tabs. Every money field shows
fmt(cents) and parses with parse_money: bad text is an error, never 0.

Errors go to the status bar and self.last_error (no modal boxes), so the
window also runs headless under QT_QPA_PLATFORM=offscreen.
"""
from __future__ import annotations

import dataclasses
import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPlainTextEdit,
    QPushButton, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import __version__, categories, checklist, diary, kits, practice
from .. import rooms as roomcalc
from .. import settings, store
from . import extras
from .. import model as m
from ..cents import (MoneyError, bp_text, fmt, money_text, parse_money,
                     parse_qty, qty_text, to_bp)
from ..diff import set_reason, supplement_totals, unexplained, render_text
from ..export import build_model, default_export_path, to_csv, to_pdf, to_xlsx
from ..interface import TakeoffSnapshot
from ..recipes import lines_for
from ..revision import approve, create_revision
from ..settle import settle_claim
from ..wbs import WbsError, auto_group, rollup

TAB_NAMES = ("Claim", "Coverage && deductibles", "Rooms && line items",
             "Groups (WBS)", "O&&P", "Settlement summary",
             "Revisions && supplements", "Diary && payments", "Contents",
             "Export")
UNDO_LIMIT = 100
AUTOSAVE_MS = 60_000


def new_claim(claim_type: str = "residential", number: str = "") -> m.Claim:
    d = (settings.get("default_op") or {}).get(claim_type, {})
    op = m.OpPolicy(overhead_bp=int(d.get("overhead_bp", 0)),
                    profit_bp=int(d.get("profit_bp", 0)),
                    compound=bool(d.get("compound", claim_type == "commercial")),
                    application=d.get("application", "aggregate"))
    kind = "dwelling" if claim_type == "residential" else "building"
    name = "Dwelling" if claim_type == "residential" else "Building 1"
    return m.Claim(id=m.new_id(), claim_number=number or "NEW-CLAIM",
                   claim_type=claim_type, op=op,
                   deductible_mode="per_occurrence" if claim_type == "residential"
                   else "per_building",
                   structures=(m.Structure(id=m.new_id(), name=name, kind=kind),))


def settlement_text(claim: m.Claim) -> str:
    """Every step of 3.7, per structure and in total, warnings in words."""
    s = settle_claim(claim)
    out = [f"{claim.claim_type.title()} claim {claim.claim_number}", ""]
    for r in s.structures:
        out.append(f"== {r.name} ==")
        rows = [("Replacement cost (RC)", r.rc), ("Overhead", r.overhead),
                ("Profit", r.profit), ("Ordinance or law", r.ol), ("RCV", r.rcv),
                ("Depreciation", r.dep), ("ACV", r.acv)]
        if claim.claim_type == "commercial":
            rows.append(("After coinsurance", r.after_coinsurance))
        rows += [("Deductible", r.deductible), ("Paid now", r.paid_now)]
        out += [f"  {k:<34}{fmt(v):>16}" for k, v in rows]
        if r.limit_cents is not None:
            out.append(f"  {'Limit':<34}{fmt(r.limit_cents):>16}")
        out.append("")
    out.append("== Total ==")
    rows = [("RCV", s.rcv), ("Depreciation", s.dep), ("ACV", s.acv),
            ("Deductible", s.deductible), ("Paid now", s.net),
            ("Recoverable depreciation (later)", s.recoverable_holdback)]
    if claim.claim_type == "residential":
        rows.append(("ALE", s.ale))
    else:
        rows += [(f"Business income ({s.bi_days} days)", s.bi),
                 ("Extra expense", s.ee), ("BI + EE paid", s.bi_ee)]
    if claim.contents:                       # 0.2.2
        from .. import contents as ct
        lab = ct.label(claim)
        rows += [(f"{lab} RCV", s.contents_rcv),
                 (f"{lab} ACV", s.contents_acv),
                 (f"{lab} paid now", s.contents_now),
                 (f"{lab} paid later", s.contents_holdback)]
    rows.append(("Total indemnity now", s.total_indemnity))
    out += [f"  {k:<34}{fmt(v):>16}" for k, v in rows]
    if claim.claim_type == "commercial":
        out += ["", "Not modeled in v1: BI coinsurance, monthly limits of "
                "indemnity, extended period of indemnity, margin clauses."]
    if s.warnings:
        out += ["", "Warnings:"] + [f"  • {w.plain()}" for w in s.warnings]
    return "\n".join(out)


def _opt_money(text: str) -> Optional[int]:
    t = (text or "").strip()
    return None if t == "" else parse_money(t)


def _opt_int(text: str) -> Optional[int]:
    t = (text or "").strip()
    if t == "":
        return None
    if not t.isdigit():
        raise MoneyError(f"{text!r} is not a whole number")
    return int(t)


def _opt_bp(text: str) -> Optional[int]:
    t = (text or "").strip().rstrip("%")
    return None if t == "" else to_bp(t)


def _money_or_blank(c: Optional[int]) -> str:
    return "" if c is None else money_text(c)


class LibraryDialog(QDialog):
    """File > My line items: the user's own codes (none shipped). Add,
    remove, import the user's CSV, export; with pick=True, choose codes to
    add to the claim."""
    COLS = ("Code", "Description", "Category", "Unit", "Unit cost")

    def __init__(self, parent=None, pick=False):
        super().__init__(parent)
        from .. import library
        self.lib = library
        self.setWindowTitle("Pick from my line items" if pick
                            else "My line items")
        self.resize(720, 460)
        lay = QVBoxLayout(self)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a code or description")
        self.find.textChanged.connect(lambda _t: self.fill())
        lay.addWidget(self.find)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(list(self.COLS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.table, 1)
        self.msg = QLabel("Your own codes only - nothing is shipped in this "
                          "library.")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        if not pick:
            form = QHBoxLayout()
            self.code, self.desc = QLineEdit(), QLineEdit()
            self.cat, self.unit = QComboBox(), QComboBox()
            self.cost = QLineEdit()
            self.code.setPlaceholderText("Code")
            self.desc.setPlaceholderText("Description")
            self.cost.setPlaceholderText("Unit cost $")
            self.cat.addItems(sorted(categories.categories()))
            self.unit.addItems(list(m.UNITS))
            for wdg in (self.code, self.desc, self.cat, self.unit,
                        self.cost):
                form.addWidget(wdg)
            lay.addLayout(form)
            row = QHBoxLayout()
            for text, fn in (("Add / replace", self.add),
                             ("Remove", self.remove),
                             ("New category…", self.new_category),
                             ("Import my CSV…", self.import_csv),
                             ("Export CSV…", self.export_csv)):
                b = QPushButton(text)
                b.clicked.connect(lambda _c=False, f=fn: f())
                row.addWidget(b)
            lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                              if pick else QDialogButtonBox.Close)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill()

    def fill(self) -> int:
        rows = self.lib.search(self.find.text())
        self.table.setRowCount(len(rows))
        for r, it in enumerate(rows):
            total = sum(int(v) for v in it["unit_cost"].values())
            for col, v in enumerate((it["code"], it["description"],
                                     categories.label(it["category"]),
                                     it["unit"], fmt(total))):
                self.table.setItem(r, col, QTableWidgetItem(v))
        return len(rows)

    def chosen(self) -> list:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.table.item(r, 0).text() for r in rows]

    def add(self, code=None, desc=None, cat=None, unit=None, cost=None):
        try:
            it = self.lib.add_item(
                code if code is not None else self.code.text(),
                desc if desc is not None else self.desc.text(),
                cat or self.cat.currentText(),
                unit or self.unit.currentText(),
                other=cost if cost is not None else self.cost.text())
        except self.lib.LibraryError as e:
            self.msg.setText(str(e))
            return None
        self.msg.setText(f"Saved {it['code']}.")
        self.fill()
        return it

    def remove(self):
        for k in self.chosen():
            self.lib.remove_item(k)
        self.fill()

    def new_category(self, code=None, label=None, group=None):
        from PySide6.QtWidgets import QInputDialog
        if code is None:
            label, ok = QInputDialog.getText(self, "New category", "Name:")
            if not ok or not label.strip():
                return None
            group, ok = QInputDialog.getItem(
                self, "New category", "Trade group:",
                categories.trade_groups(), 0, True)
            if not ok:
                return None
            code = "".join(ch for ch in label.upper() if ch.isalnum()
                           or ch == " ").replace(" ", "_")[:24]
        try:
            c = self.lib.add_category(code, label, group)
        except self.lib.LibraryError as e:
            self.msg.setText(str(e))
            return None
        if hasattr(self, "cat"):
            self.cat.clear()
            self.cat.addItems(sorted(categories.categories()))
            self.cat.setCurrentText(c)
        return c

    def import_csv(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Import my line items",
                                                  "", "CSV (*.csv)")
            if not path:
                return None
        try:
            rep = self.lib.import_csv(path)
        except (OSError, UnicodeDecodeError, self.lib.LibraryError) as e:
            self.msg.setText(f"Couldn't import: {e}")
            return None
        txt = f"{rep['added']} added, {rep['replaced']} replaced"
        if rep["errors"]:
            txt += f"; {len(rep['errors'])} rows skipped: " + "; ".join(
                rep["errors"][:3])
        self.msg.setText(txt)
        self.fill()
        return rep

    def export_csv(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export my line items",
                                                  "My line items.csv",
                                                  "CSV (*.csv)")
            if not path:
                return None
        return self.lib.export_csv(path)


class TakeoffDialog(QDialog):
    """Lists snapshot items (name, qty, unit, page label, color swatch)."""

    def __init__(self, snap: TakeoffSnapshot, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Add from takeoff – {snap.source_file}")
        lay = QVBoxLayout(self)
        self.table = QTableWidget(len(snap.items), 5)
        self.table.setHorizontalHeaderLabels(["Name", "Qty", "Unit", "Page", "Color"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for r, it in enumerate(snap.items):
            for c, v in enumerate((it.name, it.qty, it.unit, it.page_label, "")):
                cell = QTableWidgetItem(v)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, cell)
            if it.color:
                self.table.item(r, 4).setBackground(QColor(it.color))
        lay.addWidget(self.table)
        if snap.rejected:
            lay.addWidget(QLabel(f"{len(snap.rejected)} item(s) were rejected "
                                 "(bad qty, unit or color) and are not listed."))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.items = snap.items

    def chosen(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.items[r] for r in rows] if rows else list(self.items)


class ClaimsWindow(QMainWindow):
    def __init__(self, snapshot: Optional[TakeoffSnapshot] = None):
        super().__init__()
        self.snapshot = snapshot
        self.open_claims: list[dict] = []     # {"claim", "revisions", "path"}
        self.current = -1
        self.last_error = ""
        self.resize(1200, 800)

        self._filling = False
        self.claim_list = QListWidget()
        self.claim_list.currentRowChanged.connect(self._select)
        self.tabs = QTabWidget()
        self._build_claim_tab()
        self._build_coverage_tab()
        self._build_lines_tab()
        self._build_groups_tab()
        self._build_op_tab()
        self._build_settlement_tab()
        self._build_revisions_tab()
        self._build_diary_tab()
        self._build_contents_tab()
        self._build_export_tab()
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.tabs, 1)
        rl.addWidget(self._build_totals_bar())
        split = QSplitter()
        split.addWidget(self.claim_list)
        split.addWidget(right)
        split.setStretchFactor(1, 4)
        # ClaimIT 0.2: a start page when no claim is open
        self.start = extras.StartPage()
        self.start.new_residential.connect(lambda: self.new_claim_dialog("residential"))
        self.start.new_commercial.connect(lambda: self.new_claim_dialog("commercial"))
        self.start.open_file.connect(self.open_dialog)
        self.start.open_recent.connect(self.open_path)
        self.start.practice.connect(self.open_practice)
        self.start.from_takeoff.connect(self._start_from_takeoff)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start)
        self.stack.addWidget(split)
        self.setCentralWidget(self.stack)
        self._build_menu()
        self.statusBar().showMessage(f"ClaimIT {__version__}")
        self.start.refresh(takeoff_waiting=snapshot is not None)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(AUTOSAVE_MS)
        self.autosave_timer.timeout.connect(self.autosave)
        self._photo_cache = {}

    # ---------------------------------------------------------------- state
    @property
    def claim(self) -> Optional[m.Claim]:
        return self.open_claims[self.current]["claim"] if self.current >= 0 else None

    def _set_claim(self, claim: m.Claim, action: str = "") -> None:
        oc = self.open_claims[self.current]
        if oc["claim"] is not claim:
            if oc["claim"].status != claim.status:
                # a status change (submit, approve...) is not undone: undo
                # would bypass the freeze and drop its audit event
                oc["undo"].clear()
            else:
                oc["undo"].append(oc["claim"])
                del oc["undo"][:-UNDO_LIMIT]
            oc["redo"].clear()
            oc["dirty"] = True
        oc["claim"] = claim
        self.refresh()

    # ---------------------------------------------------- undo / redo (0.2)
    def undo(self) -> bool:
        if self.current < 0 or not self.open_claims[self.current]["undo"]:
            return self.error("Nothing to undo")
        oc = self.open_claims[self.current]
        cur = oc["claim"]
        oc["redo"].append(cur)
        oc["claim"] = self._with_audit(oc["undo"].pop(), cur, "undo")
        oc["dirty"] = True
        self.refresh()
        self.statusBar().showMessage("Undone")
        return True

    @staticmethod
    def _with_audit(target, current, action):
        """Undo/redo go back to an earlier claim, but the audit trail only
        grows: the current trail plus an undo/redo event (r47 #11)."""
        from datetime import datetime
        ev = m.AuditEvent(at=datetime.now().isoformat(timespec="seconds"),
                          actor=settings.author(), action=action,
                          target=target.id, before="", after="")
        return dataclasses.replace(target, audit=current.audit + (ev,))

    def redo(self) -> bool:
        if self.current < 0 or not self.open_claims[self.current]["redo"]:
            return self.error("Nothing to redo")
        oc = self.open_claims[self.current]
        cur = oc["claim"]
        oc["undo"].append(cur)
        oc["claim"] = self._with_audit(oc["redo"].pop(), cur, "redo")
        oc["dirty"] = True
        self.refresh()
        self.statusBar().showMessage("Redone")
        return True

    # ------------------------------------------------- autosave (0.2)
    def autosave(self) -> int:
        """Save every changed claim that has its real number. Called every
        minute and when the window closes - no 'save changes?' prompts."""
        n = 0
        keep = self.current
        for i, oc in enumerate(self.open_claims):
            if not self._savable(oc):
                continue
            self.current = i
            if self.save(quiet=True):
                n += 1
        self.current = keep
        return n

    @staticmethod
    def _savable(oc) -> bool:
        """Changed, and has a real claim number (a practice claim only once
        the user has saved it themselves)."""
        num = oc["claim"].claim_number
        if not oc.get("dirty") or num in ("", "NEW-CLAIM"):
            return False
        return num != practice.NUMBER or bool(oc.get("path"))

    def unsaved_unnamed(self) -> list:
        """Changed claims autosave can't save (no claim number yet)."""
        return [oc["claim"] for oc in self.open_claims
                if oc.get("dirty") and oc["claim"].claim_number in ("", "NEW-CLAIM")
                and oc["claim"].lines]

    def showEvent(self, e):
        self.autosave_timer.start()
        super().showEvent(e)

    def closeEvent(self, e):
        self.autosave()
        left = self.unsaved_unnamed()
        if left and self.isVisible():
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(
                    self, "ClaimIT",
                    f"{len(left)} claim(s) have no claim number yet, so they "
                    "weren't saved. Close anyway and lose them?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                e.ignore()
                return
        self.autosave_timer.stop()
        super().closeEvent(e)

    def _change(self, action: str, reopen: bool = False, **changes) -> bool:
        try:
            c = m.edit(self.claim, settings.author(), action, reopen=reopen,
                       **changes)
        except (m.FrozenClaimError, ValueError) as e:
            return self.error(str(e))
        self._set_claim(c)
        return True

    def error(self, msg: str) -> bool:
        self.last_error = msg
        self.statusBar().showMessage("⚠ " + msg)
        return False

    def add_claim(self, claim: m.Claim, revisions=(), path: str = "") -> None:
        self.open_claims.append({"claim": claim, "revisions": list(revisions),
                                 "path": path, "undo": [], "redo": [],
                                 "dirty": not path})
        self.claim_list.addItem(claim.claim_number)
        self.stack.setCurrentIndex(1)
        self.claim_list.setCurrentRow(len(self.open_claims) - 1)

    def close_claim(self) -> bool:
        """File > Close claim: saved first when it has its number."""
        if self.current < 0:
            return False
        oc = self.open_claims[self.current]
        if self._savable(oc) and not self.save(quiet=True):
            return False                       # kept open: the save failed
        i = self.current
        self.open_claims.pop(i)
        self.claim_list.blockSignals(True)
        self.claim_list.takeItem(i)
        self.claim_list.blockSignals(False)
        if self.open_claims:
            self.current = min(i, len(self.open_claims) - 1)
            self.claim_list.setCurrentRow(self.current)
            self.refresh()
        else:
            self.current = -1
            self.setWindowTitle("ClaimIT")
            self.start.refresh(takeoff_waiting=self.snapshot is not None)
            self.stack.setCurrentIndex(0)
        return True

    def new_claim_dialog(self, claim_type="residential", values=None):
        """File > New claim: the basics in one step (0.2)."""
        dlg = extras.NewClaimDialog(claim_type, self)
        if values is not None:
            dlg.fill(**values)
        elif dlg.exec() != QDialog.Accepted:
            return None
        try:
            v = dlg.values()
        except ValueError as e:
            self.error(str(e))
            return None
        c = new_claim(claim_type, v["claim_number"])
        if os.path.exists(store.path_for(c)):
            self.error(f"Claim {v['claim_number']} already exists - open it "
                       "from the start page or File > Open")
            return None
        structs = list(c.structures)
        if v["limit_cents"] is not None:
            structs[0] = dataclasses.replace(structs[0],
                                             limit_cents=v["limit_cents"])
        c = dataclasses.replace(
            c, insured=v["insured"], carrier=v["carrier"],
            loss_address=v["loss_address"], loss_date=v["loss_date"],
            peril=v["peril"], structures=tuple(structs),
            deductible=dataclasses.replace(
                c.deductible, amount_cents=v["deductible_cents"]))
        self.add_claim(c)
        self.save(quiet=True)
        self.tabs.setCurrentIndex(2)          # rooms & lines next
        return c

    def open_practice(self) -> m.Claim:
        c = practice.claim()
        self.add_claim(c)
        self.statusBar().showMessage("Practice claim: made-up names and "
                                     "practice prices - try anything.")
        return c

    def _start_from_takeoff(self):
        c = self.new_claim_dialog("residential")
        if c is not None and self.snapshot is not None:
            self.add_from_takeoff()

    def _select(self, row: int) -> None:
        # an open cell editor and a queued table edit belong to the claim
        # being left: apply them before switching
        if 0 <= self.current < len(self.open_claims) and row != self.current:
            self.lines_table.setCurrentItem(None)
            if getattr(self, "_apply_queued", False):
                self._apply_queued_edit()
        self.current = row
        self.refresh()

    def refresh(self) -> None:
        c = self.claim
        if c is None:
            return
        self.setWindowTitle(f"ClaimIT – {c.claim_number}")
        it = self.claim_list.item(self.current)
        if it is not None:
            it.setText(c.claim_number)
        self._filling = True
        try:
            self._fill_claim_tab(c)
            self._fill_coverage_tab(c)
            self._fill_rooms(c)
            self._fill_lines(c)
            self._fill_groups(c)
            self._fill_op(c)
            self.settlement_view.setPlainText(settlement_text(c))
            self._fill_revisions()
            s = settle_claim(c)
            self._fill_diary(c, s)
            self._fill_contents(c, s)
            self._fill_totals(c, s)
        finally:
            self._filling = False

    # ---------------------------------------------------------------- menu
    def _act(self, menu, text, fn, key=None):
        a = QAction(text, self)
        a.triggered.connect(lambda _c=False: fn())
        if key:
            a.setShortcut(QKeySequence(key))
        menu.addAction(a)
        return a

    def _build_menu(self) -> None:
        f = self.menuBar().addMenu("&File")
        self._act(f, "New residential claim…",
                  lambda: self.new_claim_dialog("residential"), "Ctrl+N")
        self._act(f, "New commercial claim…",
                  lambda: self.new_claim_dialog("commercial"))
        self._act(f, "Open claim…", self.open_dialog, "Ctrl+O")
        self._act(f, "Practice claim", self.open_practice)
        f.addSeparator()
        self._act(f, "Save", self.save, "Ctrl+S")
        self._act(f, "Close claim", self.close_claim, "Ctrl+W")
        f.addSeparator()
        self._act(f, "My line items…", lambda: self.library_dialog())
        self._act(f, "My line kits…", lambda: self.kits_dialog())
        e = self.menuBar().addMenu("&Edit")
        self._act(e, "Undo", self.undo, "Ctrl+Z")
        self._act(e, "Redo", self.redo, "Ctrl+Y")
        e.addSeparator()
        self._act(e, "Find a line", lambda: (self.tabs.setCurrentIndex(2),
                                             self.line_find.setFocus()),
                  "Ctrl+F")
        h = self.menuBar().addMenu("&Help")
        self._act(h, "Getting started", lambda: self.getting_started(), "F1")
        self._act(h, "Before you send (checklist)…",
                  lambda: self.checklist_dialog())

    def open_dialog(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Open claim", settings.claims_folder(),
                                           "Claims (*.claim.json)")
        if p:
            self.open_path(p)

    def open_path(self, path: str) -> None:
        norm = os.path.normcase(os.path.abspath(path))
        for i, oc in enumerate(self.open_claims):
            if oc.get("path") and os.path.normcase(
                    os.path.abspath(oc["path"])) == norm:
                self.stack.setCurrentIndex(1)
                self.claim_list.setCurrentRow(i)      # already open
                return
        try:
            claim, revs = store.load(path)
        except (OSError, ValueError, KeyError, TypeError, AttributeError,
                settings.UnsafePathError) as e:
            self.error(f"Can't open {os.path.basename(path)}: {e}")
            return
        self.add_claim(claim, revs, path)

    def save(self, quiet=False) -> Optional[str]:
        if self.claim is None:
            return None
        oc = self.open_claims[self.current]
        folder = os.path.dirname(oc["path"]) if oc.get("path") else None
        target = store.path_for(oc["claim"], folder)
        owner = store.claim_id_in(target)
        if owner is not None and owner != oc["claim"].id:
            self.error(f"Not saved: {os.path.basename(target)} is a different "
                       "claim with the same claim number. Change this "
                       "claim's number on the Claim tab.")
            return None
        try:
            p = store.save(oc["claim"], oc["revisions"], folder)
        except (OSError, settings.UnsafePathError) as e:
            self.error(str(e))
            return None
        old = oc.get("path")
        if old and os.path.normcase(os.path.abspath(old)) != \
                os.path.normcase(os.path.abspath(p)) and \
                store.claim_id_in(old) == oc["claim"].id:
            # the claim number changed: its old file goes to .backup
            # (moved, not deleted) so one claim is one file
            try:
                import datetime as _dt
                bdir = os.path.join(os.path.dirname(old), ".backup")
                os.makedirs(bdir, exist_ok=True)
                os.replace(old, os.path.join(bdir, os.path.basename(old) + "." +
                           _dt.datetime.now().strftime("%Y%m%d-%H%M%S")))
            except OSError:
                pass
        oc["path"] = p
        oc["dirty"] = False
        recent = [p] + [x for x in (settings.get("recent") or []) if x != p]
        settings.set("recent", recent[:10])
        self.statusBar().showMessage(("Saved " if not quiet else
                                      "Saved automatically: ") + p)
        return p

    # ---------------------------------------------------------------- tab 1
    def _build_claim_tab(self) -> None:
        w = QWidget()
        form = QFormLayout(w)
        self.f = {}
        for key, label in (("claim_number", "Claim number"), ("insured", "Insured"),
                           ("carrier", "Carrier"), ("loss_address", "Loss address"),
                           ("loss_date", "Loss date"), ("peril", "Peril")):
            self.f[key] = QLineEdit()
            form.addRow(label, self.f[key])
        self.claim_type = QComboBox()
        self.claim_type.addItems(["Residential", "Commercial"])
        form.addRow("Claim type", self.claim_type)
        self.status_box = QComboBox()
        self.status_box.addItems(list(m.STATUSES))
        form.addRow("Status", self.status_box)
        b = QPushButton("Apply")
        b.clicked.connect(self.apply_claim_tab)
        form.addRow(b)
        self.tabs.addTab(w, TAB_NAMES[0])

    def _fill_claim_tab(self, c) -> None:
        for k, e in self.f.items():
            e.setText(getattr(c, k))
        self.claim_type.setCurrentIndex(0 if c.claim_type == "residential" else 1)
        self.status_box.setCurrentText(c.status)

    def apply_claim_tab(self) -> bool:
        vals = {k: e.text().strip() for k, e in self.f.items()}
        if not vals["claim_number"]:
            return self.error("Claim number is required")
        ctype = "residential" if self.claim_type.currentIndex() == 0 else "commercial"
        status = self.status_box.currentText()
        c = self.claim
        changes = {k: v for k, v in vals.items() if getattr(c, k) != v}
        if ctype != c.claim_type:
            changes["claim_type"] = ctype
        if status != c.status:
            changes["status"] = status
        return self._change("edit claim info", **changes) if changes else True

    # ---------------------------------------------------------------- tab 2
    def _build_coverage_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        # shared: deductible + O&L
        g = QGroupBox("Deductible")
        fl = QFormLayout(g)
        self.ded_kind = QComboBox()
        self.ded_kind.addItems(["flat", "percent"])
        self.ded_amount = QLineEdit()
        self.ded_pct = QLineEdit()
        self.ded_basis = QComboBox()
        self.ded_basis.addItems(["coverage_a", "rcv"])
        self.ded_mode = QComboBox()
        self.ded_mode.addItems(["per_occurrence", "per_building"])
        fl.addRow("Kind", self.ded_kind)
        fl.addRow("Amount ($)", self.ded_amount)
        fl.addRow("Percent", self.ded_pct)
        fl.addRow("Percent of", self.ded_basis)
        fl.addRow("Mode (commercial)", self.ded_mode)
        lay.addWidget(g)
        g = QGroupBox("Ordinance or law")
        fl = QFormLayout(g)
        self.ol_pct = QLineEdit()
        self.ol_cap = QLineEdit()
        self.ol_cats = QLineEdit()
        self.ol_op = QCheckBox("Add O&P to O&L")
        fl.addRow("Percent of qualifying RC", self.ol_pct)
        fl.addRow("Cap ($, blank = none)", self.ol_cap)
        fl.addRow("Qualifying categories", self.ol_cats)
        fl.addRow(self.ol_op)
        lay.addWidget(g)
        # residential
        self.res_box = QGroupBox("Residential: coverage limits and ALE")
        fl = QFormLayout(self.res_box)
        self.cov_a = QLineEdit()
        self.cov_b = QLineEdit()
        self.ale = {k: QLineEdit() for k in ("daily", "days", "days_limit", "cap", "pct")}
        fl.addRow("Coverage A limit ($)", self.cov_a)
        fl.addRow("Coverage B limit ($)", self.cov_b)
        fl.addRow(QLabel("Coverage C (contents) is not modeled in v1."))
        for k, label in (("daily", "ALE per day ($)"), ("days", "ALE days"),
                         ("days_limit", "ALE days limit"), ("cap", "ALE cap ($)"),
                         ("pct", "ALE % of Coverage A")):
            fl.addRow(label, self.ale[k])
        lay.addWidget(self.res_box)
        # commercial
        self.com_box = QGroupBox("Commercial: structures, limits, business income")
        cl = QVBoxLayout(self.com_box)
        self.struct_table = QTableWidget(0, 7)
        self.struct_table.setHorizontalHeaderLabels(
            ["Name", "Value ($)", "Limit ($)", "Coinsurance %", "Valuation",
             "Own deductible ($)", "Kind"])
        cl.addWidget(self.struct_table)
        row = QHBoxLayout()
        b = QPushButton("Add structure")
        b.clicked.connect(self.add_structure_row)
        row.addWidget(b)
        cl.addLayout(row)
        fl = QFormLayout()
        self.limit_mode = QComboBox()
        self.limit_mode.addItems(["scheduled", "blanket"])
        self.blanket_limit = QLineEdit()
        self.blanket_coins = QLineEdit()
        self.agreed = QCheckBox("Agreed value (no coinsurance)")
        fl.addRow("Limits", self.limit_mode)
        fl.addRow("Blanket limit ($)", self.blanket_limit)
        fl.addRow("Blanket coinsurance %", self.blanket_coins)
        fl.addRow(self.agreed)
        self.bi = {k: QLineEdit() for k in ("income", "expense", "days", "wait",
                                            "ee", "limit")}
        for k, label in (("income", "BI net income per day ($)"),
                         ("expense", "Continuing expenses per day ($)"),
                         ("days", "Restoration days"), ("wait", "Waiting hours"),
                         ("ee", "Extra expense ($)"), ("limit", "BI/EE limit ($)")):
            fl.addRow(label, self.bi[k])
        cl.addLayout(fl)
        lay.addWidget(self.com_box)
        b = QPushButton("Apply")
        b.clicked.connect(self.apply_coverage_tab)
        lay.addWidget(b)
        lay.addStretch(1)
        self.tabs.addTab(w, TAB_NAMES[1])

    def add_structure_row(self) -> None:
        r = self.struct_table.rowCount()
        self.struct_table.insertRow(r)
        for col, v in enumerate((f"Building {r + 1}", "", "", "0", "rc", "", "building")):
            self.struct_table.setItem(r, col, QTableWidgetItem(v))

    def _fill_coverage_tab(self, c) -> None:
        d = c.deductible
        self.ded_kind.setCurrentText(d.kind)
        self.ded_amount.setText(money_text(d.amount_cents))
        self.ded_pct.setText(bp_text(d.bp))
        self.ded_basis.setCurrentText(d.basis)
        self.ded_mode.setCurrentText(c.deductible_mode)
        ol = c.ol or m.OrdinanceLaw()
        self.ol_pct.setText(bp_text(ol.bp))
        self.ol_cap.setText(_money_or_blank(ol.cap_cents))
        self.ol_cats.setText(", ".join(ol.categories))
        self.ol_op.setChecked(ol.apply_op)
        res = c.claim_type == "residential"
        self.res_box.setVisible(res)
        self.com_box.setVisible(not res)
        self.res_box.setEnabled(res)
        self.com_box.setEnabled(not res)
        dw = [s for s in c.structures if s.kind == "dwelling"]
        ot = [s for s in c.structures if s.kind == "other_structure"]
        self.cov_a.setText(_money_or_blank(dw[0].limit_cents) if dw else "")
        self.cov_b.setText(_money_or_blank(ot[0].limit_cents) if ot else "")
        a = c.ale or m.AleCoverage()
        self.ale["daily"].setText(money_text(a.daily_cents))
        self.ale["days"].setText(str(a.days))
        self.ale["days_limit"].setText("" if a.days_limit is None else str(a.days_limit))
        self.ale["cap"].setText(_money_or_blank(a.cap_cents))
        self.ale["pct"].setText("" if a.pct_of_cov_a_bp is None else bp_text(a.pct_of_cov_a_bp))
        self.struct_table.setRowCount(0)
        for s in c.structures:
            r = self.struct_table.rowCount()
            self.struct_table.insertRow(r)
            vals = (s.name, money_text(s.value_cents), _money_or_blank(s.limit_cents),
                    bp_text(s.coins_bp), s.valuation,
                    _money_or_blank(s.deductible.amount_cents if s.deductible else None),
                    s.kind)
            for col, v in enumerate(vals):
                self.struct_table.setItem(r, col, QTableWidgetItem(v))
        lp = c.limits
        self.limit_mode.setCurrentText(lp.mode)
        self.blanket_limit.setText(_money_or_blank(lp.blanket_limit_cents))
        self.blanket_coins.setText(bp_text(lp.blanket_coins_bp))
        self.agreed.setChecked(lp.agreed_value)
        b = c.bi_ee or m.BusinessIncome()
        for k, v in (("income", money_text(b.daily_net_income_cents)),
                     ("expense", money_text(b.daily_continuing_expense_cents)),
                     ("days", str(b.restoration_days)), ("wait", str(b.waiting_hours)),
                     ("ee", money_text(b.extra_expense_cents)),
                     ("limit", _money_or_blank(b.limit_cents))):
            self.bi[k].setText(v)

    def apply_coverage_tab(self) -> bool:
        c = self.claim
        try:
            ded = dataclasses.replace(
                c.deductible, kind=self.ded_kind.currentText(),
                amount_cents=parse_money(self.ded_amount.text() or "0"),
                bp=to_bp(self.ded_pct.text() or "0"),
                basis=self.ded_basis.currentText())
            ol_bp = _opt_bp(self.ol_pct.text()) or 0
            ol = m.OrdinanceLaw(
                bp=ol_bp, cap_cents=_opt_money(self.ol_cap.text()),
                categories=tuple(x.strip().upper() for x in
                                 self.ol_cats.text().split(",") if x.strip()),
                apply_op=self.ol_op.isChecked()) if ol_bp else None
            changes = dict(deductible=ded, deductible_mode=self.ded_mode.currentText(),
                           ol=ol)
            if c.claim_type == "residential":
                cov_a = _opt_money(self.cov_a.text())
                cov_b = _opt_money(self.cov_b.text())
                structs = []
                for s in c.structures:
                    if s.kind == "dwelling":
                        s = dataclasses.replace(s, limit_cents=cov_a)
                    elif s.kind == "other_structure":
                        s = dataclasses.replace(s, limit_cents=cov_b)
                    structs.append(s)
                if cov_b is not None and not any(s.kind == "other_structure"
                                                 for s in structs):
                    structs.append(m.Structure(id=m.new_id(), name="Other structures",
                                               kind="other_structure",
                                               limit_cents=cov_b))
                changes["structures"] = tuple(structs)
                daily = parse_money(self.ale["daily"].text() or "0")
                days = _opt_int(self.ale["days"].text()) or 0
                changes["ale"] = m.AleCoverage(
                    daily_cents=daily, days=days,
                    days_limit=_opt_int(self.ale["days_limit"].text()),
                    cap_cents=_opt_money(self.ale["cap"].text()),
                    pct_of_cov_a_bp=_opt_bp(self.ale["pct"].text())
                ) if (daily or days) else None
            else:
                old = {i: s for i, s in enumerate(c.structures)}
                structs = []
                for r in range(self.struct_table.rowCount()):
                    t = [(self.struct_table.item(r, col).text()
                          if self.struct_table.item(r, col) else "") for col in range(7)]
                    own = _opt_money(t[5])
                    base = old.get(r) or m.Structure(id=m.new_id(), name=t[0])
                    structs.append(dataclasses.replace(
                        base, name=t[0].strip() or base.name,
                        value_cents=parse_money(t[1] or "0"),
                        limit_cents=_opt_money(t[2]), coins_bp=to_bp(t[3] or "0"),
                        valuation=t[4].strip().lower() or "rc",
                        deductible=None if own is None else m.DeductibleSpec(
                            amount_cents=own),
                        kind=t[6].strip() or "building"))
                changes["structures"] = tuple(structs)
                changes["limits"] = m.LimitPlan(
                    mode=self.limit_mode.currentText(),
                    blanket_limit_cents=_opt_money(self.blanket_limit.text()),
                    blanket_coins_bp=to_bp(self.blanket_coins.text() or "0"),
                    agreed_value=self.agreed.isChecked())
                inc = parse_money(self.bi["income"].text() or "0")
                exp = parse_money(self.bi["expense"].text() or "0")
                ee = parse_money(self.bi["ee"].text() or "0")
                changes["bi_ee"] = m.BusinessIncome(
                    daily_net_income_cents=inc, daily_continuing_expense_cents=exp,
                    restoration_days=_opt_int(self.bi["days"].text()) or 0,
                    waiting_hours=_opt_int(self.bi["wait"].text()) or 0,
                    extra_expense_cents=ee,
                    limit_cents=_opt_money(self.bi["limit"].text())
                ) if (inc or exp or ee) else None
        except MoneyError as e:
            return self.error(str(e))
        return self._change("edit coverage", **changes)

    # ---------------------------------------------------------------- tab 3
    LINE_COLS = ("Item code", "Description", "Category", "Qty", "Unit",
                 "Unit cost ($)", "Dep %", "Structure", "RC", "Room")
    ALL_ROOMS = "All rooms"

    def _build_lines_tab(self) -> None:
        w = QWidget()
        outer = QHBoxLayout(w)
        # rooms on the left (0.2): pick one to see and add its lines
        left = QVBoxLayout()
        left.addWidget(QLabel("Rooms"))
        self.room_list = QListWidget()
        self.room_list.currentRowChanged.connect(lambda _r: self._room_changed())
        self.room_list.itemDoubleClicked.connect(lambda _i: self.edit_room())
        left.addWidget(self.room_list, 1)
        self.room_info = QLabel("")
        self.room_info.setWordWrap(True)
        left.addWidget(self.room_info)
        for text, fn in (("Add room…", lambda: self.add_room()),
                         ("Edit room…", lambda: self.edit_room()),
                         ("Delete room", self.delete_room),
                         ("Add a kit to this room…",
                          lambda: self.add_kit_to_room())):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            left.addWidget(b)
        lw = QWidget()
        lw.setLayout(left)
        lw.setMaximumWidth(280)
        outer.addWidget(lw)
        lay = QVBoxLayout()
        self.line_find = QLineEdit()
        self.line_find.setPlaceholderText("Find a line (code, description or "
                                          "category)")
        self.line_find.textChanged.connect(lambda _t: self._filter_lines())
        lay.addWidget(self.line_find)
        self.lines_table = QTableWidget(0, len(self.LINE_COLS))
        self.lines_table.setHorizontalHeaderLabels(list(self.LINE_COLS))
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.itemChanged.connect(self._line_edited)
        lay.addWidget(self.lines_table, 1)
        row = QHBoxLayout()
        for text, fn in (("Add line", self.add_line),
                         ("Duplicate", self.duplicate_line),
                         ("Copy to room…", lambda: self.copy_to_room()),
                         ("Cost split…", lambda: self.cost_split()),
                         ("Delete line", self.delete_line),
                         ("From my library…",
                          lambda: self.add_from_library()),
                         ("From takeoff…", lambda: self.add_from_takeoff()),
                         ("Add photo…", lambda: self.add_photo())):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        lay.addLayout(row)
        self.rooms_label = QLabel("Edits apply as you type. Ctrl+Z undoes.")
        lay.addWidget(self.rooms_label)
        outer.addLayout(lay, 1)
        self.tabs.addTab(w, TAB_NAMES[2])

    # ---------------------------------------------------- rooms (0.2)
    def _fill_rooms(self, c) -> None:
        keep = self.selected_room_id()
        self.room_list.blockSignals(True)
        self.room_list.clear()
        it = QListWidgetItem(f"{self.ALL_ROOMS} ({len(c.lines)} lines)")
        it.setData(Qt.UserRole, "")
        self.room_list.addItem(it)
        row = 0
        for i, r in enumerate(c.rooms, 1):
            n = sum(1 for ln in c.lines if ln.room_id == r.id)
            it = QListWidgetItem(f"{r.name} ({n})")
            it.setData(Qt.UserRole, r.id)
            self.room_list.addItem(it)
            if r.id == keep:
                row = i
        self.room_list.setCurrentRow(row)
        self.room_list.blockSignals(False)
        self._show_room_info()

    def selected_room_id(self) -> str:
        it = self.room_list.currentItem() if hasattr(self, "room_list") else None
        return (it.data(Qt.UserRole) or "") if it else ""

    def selected_room(self):
        rid = self.selected_room_id()
        return next((r for r in self.claim.rooms if r.id == rid), None) \
            if rid and self.claim else None

    def _show_room_info(self) -> None:
        r = self.selected_room()
        self.room_info.setText(roomcalc.summary(r) if r else
                               "All rooms. Pick a room to see its "
                               "measurements and add lines to it.")

    def _room_changed(self) -> None:
        self._show_room_info()
        self._filter_lines()

    def select_room(self, room_id: str) -> None:
        for i in range(self.room_list.count()):
            if (self.room_list.item(i).data(Qt.UserRole) or "") == room_id:
                self.room_list.setCurrentRow(i)
                return

    def _name_taken(self, name: str, except_id: str = "") -> bool:
        return any(r.name.strip().lower() == name.strip().lower()
                   and r.id != except_id for r in self.claim.rooms)

    def add_room(self, room=None) -> bool:
        if room is None:
            dlg = extras.RoomDialog(None, self)
            if dlg.exec() != QDialog.Accepted:
                return False
            room = dlg.room()
        if self._name_taken(room.name):
            return self.error(f"There is already a room called {room.name} "
                              "- give this one its own name")
        c = self.claim
        if not room.structure_id and c.structures:
            room = dataclasses.replace(room, structure_id=c.structures[0].id)
        ok = self._change("add room", rooms=c.rooms + (room,))
        if ok:
            self.select_room(room.id)
        return ok

    def edit_room(self, room=None) -> bool:
        old = self.selected_room()
        if old is None:
            return self.error("Pick a room first")
        if room is None:
            dlg = extras.RoomDialog(old, self)
            if dlg.exec() != QDialog.Accepted:
                return False
            room = dlg.room()
        if self._name_taken(room.name, old.id):
            return self.error(f"There is already a room called {room.name}")
        room = dataclasses.replace(room, id=old.id,
                                   structure_id=old.structure_id)
        c = self.claim
        lines = []
        for ln in c.lines:
            q = roomcalc.requantify(ln, room) if ln.room_id == old.id else None
            lines.append(dataclasses.replace(ln, qty_q4=q) if q is not None
                         else ln)
        ok = self._change("edit room", lines=tuple(lines), rooms=tuple(
            room if r.id == old.id else r for r in c.rooms))
        if ok:
            self.select_room(old.id)
        return ok

    def delete_room(self) -> bool:
        r = self.selected_room()
        if r is None:
            return self.error("Pick a room first")
        c = self.claim
        lines = tuple(dataclasses.replace(ln, room_id="")
                      if ln.room_id == r.id else ln for ln in c.lines)
        ok = self._change("delete room", lines=lines,
                          rooms=tuple(x for x in c.rooms if x.id != r.id))
        if ok:
            self.statusBar().showMessage(
                f"Room {r.name} deleted; its lines stay, without a room")
        return ok

    def kits_dialog(self, show=True):
        dlg = extras.KitsDialog(self)
        if show:
            dlg.exec()
        return dlg

    def add_kit_to_room(self, name=None) -> bool:
        room = self.selected_room()
        if room is None:
            return self.error("Pick a room first - a kit takes its "
                              "quantities from the room's size")
        if name is None:
            if not kits.all_kits():
                return self.error("No kits yet - File > My line kits… to "
                                  "make one from your own line items")
            dlg = extras.KitsDialog(self, pick=True)
            if dlg.exec() != QDialog.Accepted or not dlg.chosen():
                return False
            name = dlg.chosen()
        c = self.claim
        try:
            new = kits.apply(name, room, first_ordinal=len(c.lines))
        except (kits.KitError, roomcalc.RoomError) as e:
            return self.error(str(e))
        ok = self._change("add kit", lines=c.lines + new)
        if ok:
            self.statusBar().showMessage(
                f"Kit {name}: {len(new)} line(s) added to {room.name}")
        return ok

    # ---------------------------------------------------- line helpers (0.2)
    def _filter_lines(self) -> None:
        c = self.claim
        if c is None:
            return
        rid = self.selected_room_id()
        q = self.line_find.text().strip().lower()
        for r, ln in enumerate(c.lines):
            hide = bool(rid) and ln.room_id != rid
            if q and q not in " ".join((ln.item_code, ln.description,
                                        ln.category)).lower():
                hide = True
            self.lines_table.setRowHidden(r, hide)
        cur = self.lines_table.currentRow()
        if cur >= 0 and self.lines_table.isRowHidden(cur):
            self.lines_table.clearSelection()
            self.lines_table.setCurrentItem(None)

    def _line_edited(self, item) -> None:
        # applied right after the edit ends (not inside Qt's own signal,
        # which the refill would pull the cell out from under); only the
        # edited row, so one bad row elsewhere never blocks it
        if self._filling:
            return
        self._edited_rows = getattr(self, "_edited_rows", set())
        self._edited_rows.add(item.row())
        if not getattr(self, "_apply_queued", False):
            self._apply_queued = True
            QTimer.singleShot(0, self._apply_queued_edit)

    def _apply_queued_edit(self) -> None:
        self._apply_queued = False
        rows, self._edited_rows = getattr(self, "_edited_rows", set()), set()
        if self.claim is None:
            return
        if not self.apply_lines(rows=rows):
            self._fill_lines(self.claim)        # put the cells back

    def selected_line_index(self) -> int:
        """The current line, never one the filter hides."""
        r = self.lines_table.currentRow()
        if not self.claim or not 0 <= r < len(self.claim.lines) or \
                self.lines_table.isRowHidden(r):
            return -1
        return r

    def duplicate_line(self) -> bool:
        i = self.selected_line_index()
        if i < 0:
            return self.error("Pick a line first")
        c = self.claim
        ln = dataclasses.replace(c.lines[i], id=m.new_id(),
                                 ordinal=len(c.lines))
        return self._change("duplicate line",
                            lines=c.lines[:i + 1] + (ln,) + c.lines[i + 1:])

    def cost_split(self, values=None) -> bool:
        """0.2.2 (r47 #13): the selected line's unit cost as material,
        labor, equipment and other. `values` (dollar text, in that order)
        skips the dialog."""
        i = self.selected_line_index()
        if i < 0:
            return self.error("Pick a line first")
        c = self.claim
        if c.status != "draft":
            return self.error(f"The claim is {c.status}: start a supplement "
                              "to change it")
        ln = c.lines[i]
        if values is None:
            from PySide6.QtWidgets import QDialog, QDialogButtonBox
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Cost split - {ln.description or ln.item_code}")
            form = QFormLayout(dlg)
            eds = []
            for k in m.UnitCost.PARTS:
                e = QLineEdit(money_text(getattr(ln.unit_cost, k)))
                form.addRow(k.capitalize() + " $", e)
                eds.append(e)
            total = QLabel("")
            form.addRow("Unit cost", total)

            def upd():
                try:
                    total.setText(fmt(sum(parse_money(e.text() or "0")
                                          for e in eds)))
                except MoneyError as er:
                    total.setText("⚠ " + str(er))
            for e in eds:
                e.textChanged.connect(lambda _t: upd())
            upd()
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            form.addRow(bb)
            if dlg.exec() != QDialog.Accepted:
                return False
            values = [e.text() for e in eds]
        try:
            parts = [parse_money(str(v).strip().lstrip("$") or "0")
                     for v in values]
        except MoneyError as e:
            return self.error(str(e))
        if len(parts) != 4 or any(p < 0 for p in parts):
            return self.error("each part is $0.00 or more")
        uc = m.UnitCost(*parts)
        if uc == ln.unit_cost:
            return True
        return self._change("cost split", lines=c.lines[:i] + (
            dataclasses.replace(ln, unit_cost=uc),) + c.lines[i + 1:])

    def copy_to_room(self, room_id=None) -> bool:
        """Copy the selected lines to another room; a line whose quantity
        came from a room measurement is not re-measured (edit it after)."""
        c = self.claim
        rows = sorted({ix.row() for ix in self.lines_table.selectedIndexes()
                       if ix.row() < len(c.lines) and
                       not self.lines_table.isRowHidden(ix.row())})
        if not rows:
            return self.error("Pick one or more lines first")
        if not c.rooms:
            return self.error("Add a room first")
        if room_id is None:
            names = [r.name for r in c.rooms]
            name, ok = QInputDialog.getItem(self, "Copy to room",
                                            "Copy the lines to:", names, 0,
                                            False)
            if not ok:
                return False
            room_id = c.rooms[names.index(name)].id      # names are unique
        target = next(x for x in c.rooms if x.id == room_id)
        new = []
        for k, r in enumerate(rows):
            ln = dataclasses.replace(c.lines[r], id=m.new_id(),
                                     room_id=room_id,
                                     ordinal=len(c.lines) + k)
            q = roomcalc.requantify(ln, target)
            if q is not None:                 # measured: re-measure there
                ln = dataclasses.replace(ln, qty_q4=q)
            new.append(ln)
        return self._change("copy lines to room", lines=c.lines + tuple(new))

    def add_photo(self, paths=None, caption=None) -> bool:
        """Damage photos for the selected line (or the claim) - PM review
        NW-16. Copied next to the claim file; printed in the PDF."""
        from .. import photos
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Add damage photos", "",
                "Photos (*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.heic "
                "*.webp)")
            if not paths:
                return False
        if caption is None:
            from PySide6.QtWidgets import QInputDialog
            caption, ok = QInputDialog.getText(self, "Photo caption",
                                               "Caption (optional):")
            if not ok:
                return False
        row = self.selected_line_index()
        line_id = self.claim.lines[row].id if row >= 0 else ""
        c = self.claim
        try:
            for p in paths:
                c = photos.add(c, p, caption or "", line_id=line_id)
        except (OSError, ValueError, settings.UnsafePathError) as e:
            return self.error(str(e))
        return self._change("add photo", photos=c.photos)

    def _fill_lines(self, c) -> None:
        names = {s.id: s.name for s in c.structures}
        rnames = {r.id: r.name for r in c.rooms}
        was = self._filling
        self._filling = True
        try:
            self.lines_table.setRowCount(len(c.lines))
            for r, ln in enumerate(c.lines):
                vals = (ln.item_code, ln.description, ln.category,
                        qty_text(ln.qty_q4), ln.unit,
                        money_text(ln.unit_cost.total), bp_text(ln.dep_bp),
                        names.get(ln.structure_id, ""), fmt(ln.rc),
                        rnames.get(ln.room_id, ""))
                for col, v in enumerate(vals):
                    it = QTableWidgetItem(v)
                    if col == 8:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if col == 9:
                        it.setToolTip("Type a room name to move the line")
                    self.lines_table.setItem(r, col, it)
        finally:
            self._filling = was
        self.lines_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed if c.status == "draft"
            else QAbstractItemView.NoEditTriggers)
        self._filter_lines()

    def add_line(self) -> bool:
        c = self.claim
        sid = c.structures[0].id if c.structures else ""
        ln = m.Line(id=m.new_id(), item_code="NEW", description="New item",
                    category="OTHER", qty_q4=10_000, unit="EA",
                    unit_cost=m.UnitCost(), structure_id=sid,
                    room_id=self.selected_room_id(),
                    ordinal=len(c.lines))
        return self._change("add line", lines=c.lines + (ln,))

    def delete_line(self) -> bool:
        r = self.selected_line_index()
        c = self.claim
        if r < 0:
            return self.error("Pick a line first")
        return self._change("delete line",
                            lines=c.lines[:r] + c.lines[r + 1:])

    def apply_lines(self, rows=None) -> bool:
        """Read the table into the claim: every row, or only `rows`."""
        c = self.claim
        by_name = {s.name: s.id for s in c.structures}
        room_by = {r.name.lower(): r.id for r in c.rooms}
        out = []
        try:
            for r, ln in enumerate(c.lines):
                if rows is not None and r not in rows:
                    out.append(ln)
                    continue
                t = [self.lines_table.item(r, col).text() for col in range(8)]
                cell = self.lines_table.item(r, 9)
                rtext = cell.text().strip() if cell else None
                cur = next((x.name for x in c.rooms if x.id == ln.room_id), "")
                if rtext is None or rtext == cur:
                    room_id = ln.room_id
                elif rtext == "":
                    room_id = ""
                elif rtext.lower() in room_by:
                    room_id = room_by[rtext.lower()]
                else:
                    raise MoneyError(f"row {r + 1}: no room named {rtext!r}")
                cat = t[2].strip().upper()
                if not categories.is_known(cat):
                    raise MoneyError(f"row {r + 1}: unknown category {t[2]!r}")
                unit = m.unit_from_text(t[4])
                if unit is None:
                    raise MoneyError(f"row {r + 1}: unknown unit {t[4]!r}")
                cost = parse_money(t[5])
                uc = ln.unit_cost.scaled(cost)          # keeps the split
                dep = to_bp(t[6] or "0")
                if not 0 <= dep <= 10_000:
                    raise MoneyError(f"row {r + 1}: depreciation must be "
                                     "0% to 100%")
                qty = parse_qty(t[3])
                out.append(dataclasses.replace(
                    ln, item_code=t[0].strip(), description=t[1].strip(),
                    category=cat, qty_q4=qty, unit=unit, unit_cost=uc,
                    dep_bp=dep, room_id=room_id,
                    qty_from=ln.qty_from if qty == ln.qty_q4 else "",
                    qty_factor=ln.qty_factor if qty == ln.qty_q4 else "",
                    structure_id=by_name.get(t[7].strip(), ln.structure_id)))
        except MoneyError as e:
            return self.error(str(e))
        if tuple(out) == c.lines:
            return True
        return self._change("edit lines", lines=tuple(out))

    def add_from_library(self, codes=None) -> bool:
        """Lines from the user's own library (qty 1, then edit)."""
        from .. import library
        if codes is None:
            if not library.items():
                return self.error("Your library is empty - File > My line "
                                  "items… to add codes or import your CSV")
            dlg = LibraryDialog(self, pick=True)
            if dlg.exec() != QDialog.Accepted:
                return False
            codes = dlg.chosen()
        c = self.claim
        sid = c.structures[0].id if c.structures else ""
        try:
            rid = self.selected_room_id()
            new = tuple(dataclasses.replace(
                library.line_from(k, structure_id=sid,
                                  ordinal=len(c.lines) + i), room_id=rid)
                        for i, k in enumerate(codes))
        except library.LibraryError as e:
            return self.error(str(e))
        return self._change("add from library", lines=c.lines + new) \
            if new else False

    def library_dialog(self, show=True):
        dlg = LibraryDialog(self)
        if show:
            dlg.exec()
        return dlg

    def add_from_takeoff(self, items=None) -> bool:
        if self.snapshot is None:
            return self.error("No takeoff was sent from QuantiSheet")
        if items is None:
            dlg = TakeoffDialog(self.snapshot, self)
            if dlg.exec() != QDialog.Accepted:
                return False
            items = dlg.chosen()
        c = self.claim
        sid = c.structures[0].id if c.structures else ""
        new = []
        rid = self.selected_room_id()
        for it in items:
            new += [dataclasses.replace(x, room_id=rid) for x in
                    lines_for(it, c.recipes, structure_id=sid)]
        return self._change("add from takeoff", lines=c.lines + tuple(new))

    # ---------------------------------------------------------------- tab 4
    def _build_groups_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Group", "O&P mode", "RC", "O&P", "RCV", "Dep", "ACV"])
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        b = QPushButton("Auto-group by trade")
        b.clicked.connect(self.auto_group)
        row.addWidget(b)
        b = QPushButton("Save tree (after drag-to-reparent)")
        b.clicked.connect(self.save_tree)
        row.addWidget(b)
        lay.addLayout(row)
        self.tabs.addTab(w, TAB_NAMES[3])

    def _fill_groups(self, c) -> None:
        self.tree.clear()
        try:
            totals = rollup(c.wbs, c.lines, c.op)
        except WbsError as e:
            self.error(str(e))
            return
        items = {}
        pending = sorted(c.wbs, key=lambda n: n.ordinal)
        while pending:
            rest = []
            for n in pending:
                if n.parent_id and n.parent_id not in items:
                    rest.append(n)
                    continue
                t = totals[n.id]
                it = QTreeWidgetItem([n.name, n.op_mode, fmt(t.rc), fmt(t.op),
                                      fmt(t.rcv), fmt(t.dep), fmt(t.acv)])
                it.setData(0, Qt.UserRole, n.id)
                (items[n.parent_id].addChild(it) if n.parent_id
                 else self.tree.addTopLevelItem(it))
                items[n.id] = it
            if len(rest) == len(pending):
                break
            pending = rest
        self.tree.expandAll()

    def auto_group(self) -> bool:
        nodes, lines = auto_group(self.claim)
        return self._change("auto-group", wbs=nodes, lines=lines)

    def save_tree(self) -> bool:
        by = {n.id: n for n in self.claim.wbs}
        out = []

        def walk(item, parent_id, ordinal):
            nid = item.data(0, Qt.UserRole)
            out.append(dataclasses.replace(by[nid], parent_id=parent_id,
                                           ordinal=ordinal))
            for i in range(item.childCount()):
                walk(item.child(i), nid, i)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i), "", i)
        return self._change("reparent groups", wbs=tuple(out))

    # ---------------------------------------------------------------- tab 5
    def _build_op_tab(self) -> None:
        w = QWidget()
        fl = QFormLayout(w)
        self.oh = QLineEdit()
        self.pr = QLineEdit()
        self.compound = QCheckBox("Compound (profit on subtotal + overhead)")
        self.application = QComboBox()
        self.application.addItems(["aggregate", "per_line"])
        self.excl = QLineEdit()
        fl.addRow("Overhead %", self.oh)
        fl.addRow("Profit %", self.pr)
        fl.addRow(self.compound)
        fl.addRow("Apply", self.application)
        fl.addRow("Excluded categories", self.excl)
        self.op_tax = QCheckBox("Charge O&P on sales tax lines")
        self.op_tax.setToolTip("Off: no O&P on lines in the Sales tax "
                               "category, coded TAX, or described as tax")
        fl.addRow(self.op_tax)
        b = QPushButton("Apply")
        b.clicked.connect(self.apply_op)
        fl.addRow(b)
        self.tabs.addTab(w, TAB_NAMES[4])

    def _fill_op(self, c) -> None:
        self.oh.setText(bp_text(c.op.overhead_bp))
        self.pr.setText(bp_text(c.op.profit_bp))
        self.compound.setChecked(c.op.compound)
        self.application.setCurrentText(c.op.application)
        self.excl.setText(", ".join(c.op.exclude_categories))
        self.op_tax.setChecked(bool(c.op.op_on_tax))

    def apply_op(self) -> bool:
        try:
            op = m.OpPolicy(overhead_bp=to_bp(self.oh.text() or "0"),
                            profit_bp=to_bp(self.pr.text() or "0"),
                            compound=self.compound.isChecked(),
                            application=self.application.currentText(),
                            exclude_categories=tuple(
                                x.strip().upper() for x in self.excl.text().split(",")
                                if x.strip()),
                            op_on_tax=self.op_tax.isChecked())
        except MoneyError as e:
            return self.error(str(e))
        return self._change("edit O&P", op=op)

    # ---------------------------------------------------------------- tab 6
    def _build_settlement_tab(self) -> None:
        self.settlement_view = QPlainTextEdit()
        self.settlement_view.setReadOnly(True)
        f = self.settlement_view.font()
        f.setFamily("Consolas")
        f.setStyleHint(f.StyleHint.Monospace)
        self.settlement_view.setFont(f)
        self.tabs.addTab(self.settlement_view, TAB_NAMES[5])

    # ---------------------------------------------------------------- tab 7
    def _build_revisions_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.rev_list = QListWidget()
        self.rev_list.currentRowChanged.connect(lambda _r: self._fill_changes())
        lay.addWidget(self.rev_list)
        self.change_table = QTableWidget(0, 4)
        self.change_table.setHorizontalHeaderLabels(["Change", "Line", "RC change", "Reason"])
        lay.addWidget(self.change_table)
        row = QHBoxLayout()
        for text, fn in (("Start a supplement", self.start_supplement),
                         ("New revision from current claim", self.new_revision),
                         ("Save reasons", self.save_reasons),
                         ("Approve revision", self.approve_revision)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.supp_view = QPlainTextEdit()
        self.supp_view.setReadOnly(True)
        lay.addWidget(self.supp_view)
        self.tabs.addTab(w, TAB_NAMES[6])

    @property
    def revisions(self) -> list:
        return self.open_claims[self.current]["revisions"] if self.current >= 0 else []

    def _fill_revisions(self) -> None:
        self.rev_list.blockSignals(True)
        self.rev_list.clear()
        for r in self.revisions:
            left = len(unexplained(r.changes))
            self.rev_list.addItem(f"Rev {r.number} – {r.status} – {len(r.changes)} "
                                  f"change(s), {left} need a reason")
        self.rev_list.blockSignals(False)
        if self.revisions:
            self.rev_list.setCurrentRow(len(self.revisions) - 1)
        self._fill_changes()

    def _rev_index(self) -> int:
        i = self.rev_list.currentRow()
        return i if 0 <= i < len(self.revisions) else len(self.revisions) - 1

    def _fill_changes(self) -> None:
        i = self._rev_index()
        if i < 0:
            self.change_table.setRowCount(0)
            self.supp_view.setPlainText("")
            return
        rev = self.revisions[i]
        self.change_table.setRowCount(len(rev.changes))
        for r, ch in enumerate(rev.changes):
            for col, v in enumerate((ch.kind, ch.description, fmt(ch.rc_delta),
                                     ch.reason or "")):
                it = QTableWidgetItem(v)
                if col < 3:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                elif not ch.reason:
                    it.setToolTip("Suggestion: " + ch.suggestion())
                self.change_table.setItem(r, col, it)
        if i > 0:
            t = supplement_totals(self.revisions[i - 1].claim, rev.claim)
            self.supp_view.setPlainText(render_text(rev.changes, t))
        else:
            self.supp_view.setPlainText("Original estimate (revision 0).")

    def new_revision(self) -> bool:
        revs = self.revisions
        prev = revs[-1] if revs else None
        revs.append(create_revision(prev, self.claim, author=settings.author()))
        self.open_claims[self.current]["dirty"] = True
        self._fill_revisions()
        return True

    def start_supplement(self) -> bool:
        """A sent claim is changed only as a supplement: the version that
        was sent is kept as a revision first, then the claim opens for
        changes (r47 review #2)."""
        c = self.claim
        if c is None:
            return False
        if c.status not in m.SENT:
            return self.error("This claim hasn't been sent - change it "
                              "directly")
        revs = self.revisions
        if not revs or revs[-1].claim.lines != c.lines:
            self.new_revision()
        ok = self._change("start supplement", reopen=True, status="draft")
        if ok:
            self.statusBar().showMessage("Supplement started: the sent "
                                         "version is kept as a revision")
        return ok

    def save_reasons(self) -> bool:
        i = self._rev_index()
        if i < 0:
            return self.error("No revision yet")
        rev = self.revisions[i]
        if rev.status != "draft":
            return self.error("This revision is approved and can't change")
        ch = rev.changes
        for r in range(len(ch)):
            it = self.change_table.item(r, 3)
            ch = set_reason(ch, r, it.text() if it else "")
        self.revisions[i] = dataclasses.replace(rev, changes=ch)
        self.open_claims[self.current]["dirty"] = True
        self._fill_revisions()
        return True

    def approve_revision(self) -> bool:
        i = self._rev_index()
        if i < 0:
            return self.error("No revision yet")
        try:
            self.revisions[i] = approve(self.revisions[i])
        except Exception as e:  # UnexplainedChanges
            return self.error(str(e))
        self.open_claims[self.current]["dirty"] = True
        self._fill_revisions()
        return True

    # ---------------------------------------------------------------- tab 8
    def _build_export_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Exports go to a folder you pick. They are never sent "
                             "anywhere and never written into QuantiSheet's files."))
        for text, kind in (("Export CSV…", "csv"), ("Export Excel (XLSX)…", "xlsx"),
                           ("Export PDF…", "pdf")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=kind: self.export_dialog(k))
            lay.addWidget(b)
        lay.addStretch(1)
        self.tabs.addTab(w, TAB_NAMES[9])

    def export_dialog(self, kind: str) -> None:
        start = default_export_path(self.claim, kind)
        p, _ = QFileDialog.getSaveFileName(self, f"Export {kind.upper()}", start,
                                           f"{kind.upper()} (*.{kind})")
        if p:
            self.export_to(kind, p)

    def export_to(self, kind: str, path: str) -> Optional[str]:
        revs = self.revisions
        md = build_model(self.claim, revs[-1] if revs else None)
        fn = {"csv": to_csv, "xlsx": to_xlsx, "pdf": to_pdf}[kind]
        try:
            out = fn(md, path)
        except (OSError, settings.UnsafePathError) as e:
            self.error(str(e))
            return None
        self.statusBar().showMessage(f"Exported {out}")
        return out

    # ---------------------------------------------------- diary (0.2)
    def _build_diary_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Diary</b> - calls, inspections, emails and "
                             "notes, oldest first"))
        self.diary_table = QTableWidget(0, 4)
        self.diary_table.setHorizontalHeaderLabels(["Date", "Kind", "What happened",
                                                    "By"])
        self.diary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.diary_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.diary_table.horizontalHeader().setStretchLastSection(False)
        self.diary_table.setColumnWidth(2, 460)
        lay.addWidget(self.diary_table, 2)
        row = QHBoxLayout()
        self.d_date = QLineEdit(extras.today())
        self.d_date.setMaximumWidth(110)
        self.d_kind = QComboBox()
        self.d_kind.addItems(list(m.DIARY_KINDS))
        self.d_text = QLineEdit()
        self.d_text.setPlaceholderText("What happened")
        self.d_text.returnPressed.connect(lambda: self.add_diary())
        row.addWidget(self.d_date)
        row.addWidget(self.d_kind)
        row.addWidget(self.d_text, 1)
        for text, fn in (("Add", lambda: self.add_diary()),
                         ("Remove", self.remove_diary)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(QLabel("<b>Payments received</b> - a record only; "
                             "ClaimIT never moves money"))
        self.pay_table = QTableWidget(0, 4)
        self.pay_table.setHorizontalHeaderLabels(["Date", "Kind", "Amount",
                                                  "Check / reference"])
        self.pay_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pay_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self.pay_table, 1)
        row = QHBoxLayout()
        self.p_date = QLineEdit(extras.today())
        self.p_date.setMaximumWidth(110)
        self.p_kind = QComboBox()
        self.p_kind.addItems(list(m.PAYMENT_KINDS))
        self.p_amount = QLineEdit()
        self.p_amount.setPlaceholderText("$")
        self.p_ref = QLineEdit()
        self.p_ref.setPlaceholderText("Check or reference number")
        for wdg in (self.p_date, self.p_kind, self.p_amount, self.p_ref):
            row.addWidget(wdg)
        for text, fn in (("Add payment", lambda: self.add_payment()),
                         ("Remove", self.remove_payment)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        lay.addLayout(row)
        self.balance_label = QLabel("")
        lay.addWidget(self.balance_label)
        self.tabs.addTab(w, TAB_NAMES[7])

    def _fill_diary(self, c, s=None) -> None:
        self.diary_table.setRowCount(len(c.diary))
        for r, e in enumerate(c.diary):
            for col, v in enumerate((e.on, e.kind, e.text, e.by)):
                self.diary_table.setItem(r, col, QTableWidgetItem(v))
        self.pay_table.setRowCount(len(c.payments))
        for r, p in enumerate(c.payments):
            for col, v in enumerate((p.on, p.kind, fmt(p.amount_cents),
                                     p.reference)):
                self.pay_table.setItem(r, col, QTableWidgetItem(v))
        b = diary.balance(c, s or settle_claim(c))
        self.balance_label.setText(
            f"Owed now {fmt(b['owed_now'])} · recoverable later "
            f"{fmt(b['recoverable_later'])} · paid {fmt(b['paid'])} · "
            f"still open {fmt(b['open_total'])}")

    def add_diary(self, on=None, kind=None, text=None) -> bool:
        try:
            d = diary.add_entry(self.claim, on or self.d_date.text(),
                                kind or self.d_kind.currentText(),
                                text if text is not None else self.d_text.text(),
                                by=settings.author())
        except diary.DiaryError as e:
            return self.error(str(e))
        ok = self._change("diary entry", diary=d)
        if ok:
            self.d_text.clear()
        return ok

    def remove_diary(self) -> bool:
        r = self.diary_table.currentRow()
        c = self.claim
        if not 0 <= r < len(c.diary):
            return self.error("Pick a diary line first")
        return self._change("remove diary entry",
                            diary=diary.remove_entry(c, c.diary[r].id))

    def add_payment(self, on=None, amount=None, kind=None, reference=None) -> bool:
        try:
            p = diary.add_payment(
                self.claim, on or self.p_date.text(),
                amount if amount is not None else self.p_amount.text(),
                kind or self.p_kind.currentText(),
                reference if reference is not None else self.p_ref.text())
        except (diary.DiaryError, MoneyError) as e:
            return self.error(str(e))
        ok = self._change("payment received", payments=p)
        if ok:
            self.p_amount.clear()
            self.p_ref.clear()
        return ok

    def remove_payment(self) -> bool:
        r = self.pay_table.currentRow()
        c = self.claim
        if not 0 <= r < len(c.payments):
            return self.error("Pick a payment first")
        return self._change("remove payment",
                            payments=diary.remove_payment(c, c.payments[r].id))

    # ------------------------------------------------- contents (0.2.2)
    CONTENTS_COLS = ("Item", "Room", "Qty", "Each (RC)", "Dep %", "Age",
                     "RCV", "ACV")

    def _build_contents_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.contents_title = QLabel("")
        lay.addWidget(self.contents_title)
        top = QHBoxLayout()
        self.cc_limit = QLineEdit()
        self.cc_limit.setPlaceholderText("no limit entered")
        self.cc_val = QComboBox()
        self.cc_val.addItem("Replacement cost (depreciation paid later)", "rc")
        self.cc_val.addItem("Actual cash value", "acv")
        self.cc_ded = QLineEdit()
        self.cc_ded.setPlaceholderText("0.00")
        for lab, wdg in (("Limit $", self.cc_limit), ("Paid on", self.cc_val),
                         ("Own deductible $", self.cc_ded)):
            top.addWidget(QLabel(lab))
            top.addWidget(wdg)
        b = QPushButton("Apply")
        b.clicked.connect(lambda: self.set_contents_coverage())
        top.addWidget(b)
        top.addStretch(1)
        lay.addLayout(top)
        self.contents_table = QTableWidget(0, len(self.CONTENTS_COLS))
        self.contents_table.setHorizontalHeaderLabels(list(self.CONTENTS_COLS))
        self.contents_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.contents_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.contents_table.setColumnWidth(0, 300)
        lay.addWidget(self.contents_table, 1)
        row = QHBoxLayout()
        self.ci_desc = QLineEdit()
        self.ci_desc.setPlaceholderText("Item, e.g. 55 in. TV, Example brand")
        self.ci_room = QComboBox()
        self.ci_qty = QLineEdit("1")
        self.ci_qty.setMaximumWidth(50)
        self.ci_cost = QLineEdit()
        self.ci_cost.setPlaceholderText("$ each, to replace")
        self.ci_dep = QLineEdit("0")
        self.ci_dep.setMaximumWidth(60)
        self.ci_dep.setToolTip("Depreciation %")
        self.ci_age = QLineEdit()
        self.ci_age.setPlaceholderText("age")
        self.ci_age.setMaximumWidth(70)
        self.ci_desc.returnPressed.connect(lambda: self.add_contents_item())
        for wdg, st in ((self.ci_desc, 3), (self.ci_room, 1), (self.ci_qty, 0),
                        (self.ci_cost, 1), (self.ci_dep, 0), (self.ci_age, 0)):
            row.addWidget(wdg, st)
        for text, fn in (("Add item", lambda: self.add_contents_item()),
                         ("Remove", self.remove_contents_item)):
            bt = QPushButton(text)
            bt.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(bt)
        lay.addLayout(row)
        self.contents_total = QLabel("")
        lay.addWidget(self.contents_total)
        self.tabs.addTab(w, TAB_NAMES[8])

    def _fill_contents(self, c, s=None) -> None:
        from .. import contents as ct
        s = s or settle_claim(c)
        self.contents_title.setText(
            f"<b>{ct.label(c)}</b> - personal property, item by item")
        cov = c.contents_cov
        self.cc_limit.setText(_money_or_blank(cov.limit_cents))
        self.cc_val.setCurrentIndex(max(0, self.cc_val.findData(cov.valuation)))
        self.cc_ded.setText(money_text(cov.deductible_cents)
                            if cov.deductible_cents else "")
        names = {r.id: r.name for r in c.rooms}
        keep = self.ci_room.currentData()
        self.ci_room.blockSignals(True)
        self.ci_room.clear()
        self.ci_room.addItem("(no room)", "")
        for r in c.rooms:
            self.ci_room.addItem(r.name, r.id)
        self.ci_room.setCurrentIndex(max(0, self.ci_room.findData(keep or "")))
        self.ci_room.blockSignals(False)
        self.contents_table.setRowCount(len(c.contents))
        for r, it in enumerate(c.contents):
            for col, v in enumerate((it.description, names.get(it.room_id, ""),
                                     str(it.qty), fmt(it.unit_rc_cents),
                                     bp_text(it.dep_bp), it.age,
                                     fmt(ct.item_rcv(it)),
                                     fmt(ct.item_acv(it)))):
                self.contents_table.setItem(r, col, QTableWidgetItem(v))
        self.contents_total.setText(
            f"{len(c.contents)} item(s) · RCV {fmt(s.contents_rcv)} · ACV "
            f"{fmt(s.contents_acv)} · paid now {fmt(s.contents_now)} · "
            f"paid later {fmt(s.contents_holdback)}")
        ro = c.status != "draft"
        for wdg in (self.ci_desc, self.ci_cost, self.ci_qty, self.ci_dep,
                    self.ci_age, self.cc_limit, self.cc_ded):
            wdg.setReadOnly(ro)

    def _contents_locked(self) -> bool:
        if self.claim.status != "draft":
            self.error(f"The claim is {self.claim.status}: start a supplement "
                       "to change the contents")
            return True
        return False

    def add_contents_item(self, description=None, qty=None, cost=None,
                          dep=None, room_id=None, age=None) -> bool:
        from .. import contents as ct
        if self._contents_locked():
            return False
        try:
            items = ct.add_item(
                self.claim,
                description if description is not None else self.ci_desc.text(),
                qty if qty is not None else (self.ci_qty.text() or "1"),
                cost if cost is not None else self.ci_cost.text(),
                dep if dep is not None else (self.ci_dep.text() or "0"),
                room_id if room_id is not None else
                (self.ci_room.currentData() or ""),
                age if age is not None else self.ci_age.text())
        except ct.ContentsError as e:
            return self.error(str(e))
        ok = self._change("contents item", contents=items)
        if ok:
            for wdg in (self.ci_desc, self.ci_cost, self.ci_age):
                wdg.clear()
            self.ci_qty.setText("1")
        return ok

    def remove_contents_item(self) -> bool:
        from .. import contents as ct
        if self._contents_locked():
            return False
        r = self.contents_table.currentRow()
        c = self.claim
        if not 0 <= r < len(c.contents):
            return self.error("Pick a contents item first")
        return self._change("remove contents item",
                            contents=ct.remove_item(c, c.contents[r].id))

    def set_contents_coverage(self, limit=None, valuation=None,
                              deductible=None) -> bool:
        from .. import contents as ct
        if self._contents_locked():
            return False
        try:
            cov = ct.coverage(
                limit if limit is not None else self.cc_limit.text(),
                valuation or self.cc_val.currentData(),
                deductible if deductible is not None else self.cc_ded.text())
        except ct.ContentsError as e:
            return self.error(str(e))
        if cov == self.claim.contents_cov:
            return True
        return self._change("contents coverage", contents_cov=cov)

    # ---------------------------------------------------- totals bar (0.2)
    def _build_totals_bar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("TotalsBar")
        row = QHBoxLayout(w)
        row.setContentsMargins(8, 4, 8, 4)
        self.totals = {}
        for key, label in (("rcv", "RCV"), ("dep", "Depreciation"),
                           ("acv", "ACV"), ("ded", "Deductible"),
                           ("now", "Owed now"), ("open", "Still open")):
            lab = QLabel("")
            lab.setToolTip(label)
            self.totals[key] = lab
            row.addWidget(lab)
        row.addStretch(1)
        self.check_btn = QPushButton("Checklist")
        self.check_btn.setToolTip("What to fix or check before you send")
        self.check_btn.clicked.connect(lambda: self.checklist_dialog())
        row.addWidget(self.check_btn)
        return w

    def _fill_totals(self, c, s=None) -> None:
        s = s or settle_claim(c)
        b = diary.balance(c, s)
        for key, label, v in (("rcv", "RCV", s.rcv), ("dep", "Depreciation", s.dep),
                              ("acv", "ACV", s.acv),
                              ("ded", "Deductible", s.deductible),
                              ("now", "Owed now", s.total_indemnity),
                              ("open", "Still open", b["open_total"])):
            self.totals[key].setText(f"{label} <b>{fmt(v)}</b>")
        items = self.checklist_items()
        self.check_btn.setText("Checklist: " + checklist.summary(items))

    def checklist_items(self) -> list:
        from .. import photos
        c = self.claim
        # photo files are hashed only when the photos or their files change
        key = []
        for p in c.photos:
            try:
                f = photos.path_of(c, p)
                key.append((p.sha256, f, os.path.getmtime(f)))
            except (OSError, ValueError, settings.UnsafePathError):
                key.append((p.sha256, "", 0))
        key = (c.id, tuple(key))
        if key not in self._photo_cache:
            try:
                self._photo_cache = {key: photos.verify(c)}
            except Exception:                             # noqa: BLE001
                self._photo_cache = {key: []}
        return checklist.check(c, self.revisions, self._photo_cache[key])

    def checklist_dialog(self, show=True):
        if self.claim is None:
            return None
        dlg = extras.ChecklistDialog(self.checklist_items(), self)
        dlg.go.connect(self.tabs.setCurrentIndex)
        if show:
            dlg.exec()
        return dlg

    def getting_started(self, show=True):
        dlg = extras.GettingStartedDialog(self)
        if show:
            dlg.exec()
        return dlg
