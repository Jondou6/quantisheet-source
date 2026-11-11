"""Scope Sheets window: one sheet per trade, filled in like the Excel
template, with accounting-style amounts.

Estimate > Bidding > Scope Sheets (or Project Center > Bidding > Scope
Sheets). The top list shows the project's trades (CSI code, trade,
budget, low bid, recommended award, variance); the grid below is the
selected sheet: bidder header rows (company / phone / contact / bid
price), the YES/NO checklist, the scope lines (budget Qty x Unit $ =
Total, then per bidder an "included" flag and the amount), TOTAL PRICE,
Math Check (red when the bid price and the lines don't agree) and, when
leveling is on, the leveled totals with plugged cells shaded.

Amounts: right-aligned, $#,##0.00, credits in parentheses; type 1,250
or $1,250.00 or (500). A blank cell is "not priced", 0 is $0.00. Tab and
Enter move like a spreadsheet; Ctrl+C / Ctrl+V copy and paste blocks of
cells to and from Excel (tab-separated); Delete clears.

Under the grid, Clarifications: the bidder of the current column's
qualifications / exclusions / clarifications (type, text, $ adjustment,
Accept / Reject / Pending; Import from Proposal reads a sub's PDF), with
the budget column beside it (budget, as bid, plugged, accepted, leveled,
vs budget). Use Award in Estimate (top row) puts each awarded trade in
the open drawing's estimate (award_estimate.py).

The model and the Excel / PDF files are in scope_sheet.py.
"""
import logging
import os

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QKeySequence
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView,
                               QApplication, QComboBox, QCompleter, QDialog,
                               QFileDialog, QGridLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QSplitter,
                               QStyledItemDelegate, QTableWidget,
                               QTableWidgetItem, QToolTip, QVBoxLayout,
                               QWidget)

from .. import icons, settings
from ..reportname import report_file_name
from . import scope_sheet as ss

log = logging.getLogger(__name__)

# grid rows
R_COMPANY, R_PHONE, R_CONTACT, R_PRICE = 0, 1, 2, 3
R_CHECK = 4                               # 6 checklist rows
R_HEAD = R_CHECK + len(ss.CHECKLIST)      # the SCOPE caption row
R_LINE0 = R_HEAD + 1
# grid columns - the template's B..S, so a block copied from Excel
# pastes into the same cells (B:C is the description, spanned)
C_DESC, C_DESC2, C_QTY, C_UNIT, C_UPRICE, C_TOTAL = 0, 1, 2, 3, 4, 5
C_B0 = 6                                  # first bidder's flag column (H)
MONEY = {"bprice", "price", "btotal", "amount", "uprice"}
HEADER_KINDS = {R_COMPANY: "company", R_PHONE: "phone",
                R_CONTACT: "contact"}

YELLOW = QColor(255, 255, 192)
BUDGET_BG = QColor(236, 242, 250)
TOTAL_BG = QColor(235, 235, 235)
BAD_BG = QColor(255, 199, 206)
BAD_FG = QColor(156, 0, 6)
PLUG_BG = QColor(205, 240, 205)
NEG_FG = QColor(160, 0, 0)
INK = QColor(20, 20, 20)
GREY_INK = QColor(110, 110, 110)


def _bidder_col(k):
    return C_B0 + 2 * k, C_B0 + 2 * k + 1


# ======================================================== grid widgets
class _Delegate(QStyledItemDelegate):
    """A plain line editor; what's typed goes through the panel (parsed,
    stored, totals updated) - never straight into the cell."""

    def __init__(self, editor, grid):
        super().__init__(grid)
        self.ed = editor

    def createEditor(self, parent, option, index):
        e = QLineEdit(parent)
        e.setFrame(False)
        kind = self.ed.kind(index.row(), index.column())[0]
        if kind in MONEY or kind == "qty":
            e.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if kind == "company":
            names = self.ed.directory_names()
            if names:
                c = QCompleter(names, e)
                c.setCaseSensitivity(Qt.CaseInsensitive)
                c.setFilterMode(Qt.MatchContains)
                e.setCompleter(c)
        return e

    def setEditorData(self, e, index):
        e.setText(self.ed.edit_text(index.row(), index.column()))

    def setModelData(self, e, model, index):
        self.ed.commit_text(index.row(), index.column(), e.text(),
                            defer=True)


class ScopeGrid(QTableWidget):
    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self._delegate = _Delegate(editor, self)
        self.setItemDelegate(self._delegate)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked |
                             QAbstractItemView.EditKeyPressed |
                             QAbstractItemView.AnyKeyPressed |
                             QAbstractItemView.SelectedClicked)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(22)
        self.setWordWrap(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(editor.context_menu)

    def keyPressEvent(self, e):
        editing = self.state() == QAbstractItemView.EditingState
        if not editing:
            if e.matches(QKeySequence.Copy):
                self.ed.copy_selection()
                return
            if e.matches(QKeySequence.Paste):
                self.ed.paste()
                return
            if e.matches(QKeySequence.Cut):
                self.ed.copy_selection()
                self.ed.clear_selection()
                return
            if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self.ed.clear_selection()
                return
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.ed.move(-1 if e.modifiers() & Qt.ShiftModifier else 1)
                return
        super().keyPressEvent(e)

    def closeEditor(self, editor, hint):
        super().closeEditor(editor, hint)
        if hint == QAbstractItemDelegate.EndEditHint.SubmitModelCache:
            self.ed.move(1)                # Enter: down, like Excel


# ======================================================== one sheet
class ScopeSheetEditor(QWidget):
    """The grid and header of one scope sheet. `on_change(sheet)` is told
    after every edit (the panel saves it)."""

    def __init__(self, store=None, parent=None, on_change=None):
        super().__init__(parent)
        self.store = store
        self.on_change = on_change
        self.sheet = None
        self.company = ss.company_info(store)
        self._loading = False
        self._shape = None
        self._contacts = None
        self._pending = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        # ---- header fields
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(4)
        self.csi = QComboBox()
        self.csi.setEditable(True)
        self.csi.setMinimumWidth(110)
        self.csi.setToolTip("CSI MasterFormat section, e.g. 09 29 00")
        for code, name in _trade_choices():
            self.csi.addItem(f"{code}  {name}", (code, name))
        self.csi.lineEdit().editingFinished.connect(self._csi_done)
        self.csi.activated.connect(lambda _i: self._csi_done())
        self.trade = QLineEdit()
        self.trade.setPlaceholderText("Trade, e.g. Drywall & framing")
        self.trade.editingFinished.connect(
            lambda: self._set_top("trade", self.trade.text().strip()))
        self.fields = {}
        g.addWidget(QLabel("CSI"), 0, 0)
        g.addWidget(self.csi, 0, 1)
        g.addWidget(QLabel("Trade"), 0, 2)
        g.addWidget(self.trade, 0, 3, 1, 3)
        specs = [("project", "Project", 1, 0, 3), ("project_no", "Project #",
                                                   1, 4, 1),
                 ("control_no", "Control #", 0, 6, 1),
                 ("bid_date", "Bid date", 1, 6, 1),
                 ("bid_time", "Time", 0, 8, 1),
                 ("estimator", "Estimator", 1, 8, 1),
                 ("addenda_from", "Addenda", 0, 10, 1),
                 ("addenda_to", "to", 1, 10, 1)]
        for key, label, row, col, span in specs:
            e = QLineEdit()
            e.editingFinished.connect(
                lambda k=key, w=e: self._set_header(k, w.text().strip()))
            self.fields[key] = e
            g.addWidget(QLabel(label), row, col)
            g.addWidget(e, row, col + 1, 1, span)
        self.fields["addenda_from"].setMaximumWidth(50)
        self.fields["addenda_to"].setMaximumWidth(50)
        self.fields["bid_date"].setPlaceholderText("yyyy-mm-dd")
        g.setColumnStretch(3, 2)
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        # ---- tools
        row = QHBoxLayout()
        for label, tip, fn in (
                ("Add Line", "Insert a scope line below the current one",
                 lambda: self.add_line()),
                ("Remove Lines", "Remove the selected scope lines",
                 lambda: self.remove_lines()),
                ("Up", "Move the current line up", lambda: self.move_line(-1)),
                ("Down", "Move the current line down",
                 lambda: self.move_line(1)),
                ("Add Bidder", "Add a bidder block",
                 lambda: self.add_bidder()),
                ("Remove Bidder", "Remove the bidder of the current column",
                 lambda: self.remove_bidder()),
                ("From Bid Package", "Fill bidder blocks from this trade's "
                 "bid package (company, contact, bid amount)",
                 lambda: self.from_package())):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            row.addWidget(b)
        row.addStretch()
        row.addWidget(QLabel("Leveling"))
        self.level = QComboBox()
        for m in ss.LEVEL_MODES:
            self.level.addItem(ss.LEVEL_LABEL[m], m)
        self.level.setToolTip("Plug the lines a bidder excluded (N, or left "
                              "blank in a broken-down bid) so the totals "
                              "compare apples to apples. Plugged cells are "
                              "shaded green; your entries don't change.")
        self.level.currentIndexChanged.connect(self._level_changed)
        row.addWidget(self.level)
        v.addLayout(row)
        # ---- the grid, and under it the bidders' clarifications
        self.grid = ScopeGrid(self)
        self.clar = ClarificationsBox(self)
        self.grid.currentCellChanged.connect(
            lambda r, c, _r, _c: self.clar.follow_grid(c))
        self._split = QSplitter(Qt.Vertical)
        self._split.addWidget(self.grid)
        self._split.addWidget(self.clar)
        self._split.setStretchFactor(0, 3)
        self._split.setStretchFactor(1, 1)
        v.addWidget(self._split, 1)
        self.msg = QLabel("")
        self.msg.setObjectName("muted")
        v.addWidget(self.msg)
        # ---- footer
        f = QHBoxLayout()
        f.addWidget(QLabel("Recommended award to"))
        self.award = QComboBox()
        self.award.setMinimumWidth(180)
        self.award.currentIndexChanged.connect(self._award_changed)
        f.addWidget(self.award)
        f.addWidget(QLabel("Amount"))
        self.award_amt = QLineEdit()
        self.award_amt.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.award_amt.setMaximumWidth(140)
        self.award_amt.setToolTip("Blank = the bidder's total")
        self.award_amt.editingFinished.connect(self._award_amount_done)
        f.addWidget(self.award_amt)
        f.addWidget(QLabel("Owner approval"))
        self.approved_by = QLineEdit()
        self.approved_by.editingFinished.connect(
            lambda: self._set_award("approved_by",
                                    self.approved_by.text().strip()))
        f.addWidget(self.approved_by, 1)
        f.addWidget(QLabel("Date"))
        self.approved_on = QLineEdit()
        self.approved_on.setMaximumWidth(110)
        self.approved_on.setPlaceholderText("yyyy-mm-dd")
        self.approved_on.editingFinished.connect(
            lambda: self._set_award("approved_on",
                                    self.approved_on.text().strip()))
        f.addWidget(self.approved_on)
        v.addLayout(f)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.setEnabled(False)

    # ------------------------------------------------------------ load
    def set_sheet(self, sheet):
        self.sheet = sheet
        self.setEnabled(sheet is not None)
        self._shape = None
        self._loading = True
        try:
            if sheet is None:
                self.grid.setRowCount(0)
                self.grid.setColumnCount(0)
                self.summary.setText("")
                self.clar.refresh()
                return
            self.csi.setEditText(sheet.get("csi") or "")
            self.trade.setText(sheet.get("trade") or "")
            for k, e in self.fields.items():
                e.setText(sheet["header"].get(k) or "")
            i = self.level.findData(sheet.get("level") or "none")
            self.level.setCurrentIndex(max(0, i))
            self.approved_by.setText(sheet["award"].get("approved_by") or "")
            self.approved_on.setText(sheet["award"].get("approved_on") or "")
        finally:
            self._loading = False
        self.render()

    # ------------------------------------------------------------ geometry
    def n_lines(self):
        return len(self.sheet["lines"]) if self.sheet else 0

    def row_new(self):
        return R_LINE0 + self.n_lines()

    def row_total(self):
        return self.row_new() + 1

    def row_check(self):
        return self.row_new() + 2

    def row_level(self):
        if self.sheet and ((self.sheet.get("level") or "none") != "none" or
                           ss.has_adjustments(self.sheet)):
            return self.row_new() + 3
        return None

    def kind(self, r, c, extend=False):
        """(kind, bidder id, line index, checklist key) of a cell; kind
        None = read only. extend=True: rows past the last line are new
        lines (for pasting)."""
        sh = self.sheet
        if sh is None or c < 0 or r < 0:
            return None, None, None, None
        nb = len(sh["bidders"])
        k = (c - C_B0) // 2 if c >= C_B0 else None
        if k is not None and k >= nb:
            return None, None, None, None
        bid = sh["bidders"][k]["id"] if k is not None else None
        flag_col = k is not None and (c - C_B0) % 2 == 0
        if c == C_DESC2 and r >= R_LINE0:
            c = C_DESC
        if r in HEADER_KINDS:
            return (HEADER_KINDS[r], bid, None, None) if k is not None \
                else (None, None, None, None)
        if r == R_PRICE:
            if k is not None:
                return "price", bid, None, None
            return ("bprice", None, None, None) if c >= C_QTY \
                else (None, None, None, None)
        if R_CHECK <= r < R_HEAD:
            key = ss.CHECK_KEYS[r - R_CHECK]
            if k is not None:
                return ("chk_ans" if flag_col else "chk_note"), bid, None, key
            if c in (C_QTY, C_UNIT):
                return "chk_ans", None, None, key
            if c in (C_UPRICE, C_TOTAL):
                return "chk_note", None, None, key
            return None, None, None, None
        if r < R_LINE0:
            return None, None, None, None
        li = r - R_LINE0
        if li > self.n_lines() and not extend:
            return None, None, None, None
        kind = {C_DESC: "desc", C_QTY: "qty", C_UNIT: "unit",
                C_UPRICE: "uprice", C_TOTAL: "btotal"}.get(c)
        if k is not None:
            kind = "flag" if flag_col else "amount"
        return kind, bid, li, None

    def _span_col(self, r, c):
        """Spanned cells are edited at their first column."""
        if c == C_DESC2:
            return C_DESC
        if c >= C_B0 and (r in HEADER_KINDS or r == R_PRICE):
            return c - (c - C_B0) % 2
        if c >= C_QTY and c < C_B0 and r == R_PRICE:
            return C_QTY
        if R_CHECK <= r < R_HEAD and C_QTY <= c < C_B0:
            return C_QTY if c < C_UPRICE else C_UPRICE
        return c

    # ------------------------------------------------------------ text
    def _line(self, li):
        ls = self.sheet["lines"]
        return ls[li] if li is not None and li < len(ls) else None

    def edit_text(self, r, c):
        kind, bid, li, key = self.kind(r, c)
        sh = self.sheet
        if kind is None:
            return ""
        if kind in ("company", "phone", "contact"):
            return ss.bidder(sh, bid).get(kind) or ""
        if kind == "price":
            return ss.fmt_money(ss.bidder(sh, bid)["price"], False)
        if kind == "bprice":
            return ss.fmt_money(sh["budget"]["price"], False)
        if kind in ("chk_ans", "chk_note"):
            src = ss.bidder(sh, bid) if bid else sh["budget"]
            return src["checklist"][key]["ans" if kind == "chk_ans"
                                         else "note"]
        ln = self._line(li)
        if ln is None:
            return ""
        if kind == "desc":
            return ln["desc"]
        if kind == "qty":
            return ss.fmt_qty(ln["qty"])
        if kind == "unit":
            return ln["unit"]
        if kind == "uprice":
            return ss.fmt_unit_price(ln["unit_price"]).replace("$", "")
        if kind == "btotal":
            return ss.fmt_money(ss.budget_line_total(ln), False)
        cell = ss.bid_cell(ln, bid)
        if kind == "flag":
            return cell["flag"]
        return ss.fmt_money(cell["amount"], False)

    def copy_text(self, r, c):
        if self._span_col(r, c) != c:
            return ""                   # the hidden part of a merged cell
        kind, bid, li, key = self.kind(r, c)
        it = self.grid.item(r, c)
        if kind is None:
            return it.text() if it is not None else ""
        if kind in ("price", "bprice", "amount", "btotal"):
            return self.edit_text(r, c).replace(",", "").replace(
                "(", "-").replace(")", "")
        if kind == "uprice" or kind == "qty":
            return self.edit_text(r, c).replace(",", "").replace(
                "(", "-").replace(")", "")
        return self.edit_text(r, c)

    def commit_text(self, r, c, text, defer=False, render=True):
        """Store what was typed in a cell. Returns an error message, or
        '' when stored (or nothing changed)."""
        if self.sheet is None:
            return ""
        if self._span_col(r, c) != c:
            return ""                  # the hidden part of a merged cell
        if self.store is not None and \
                getattr(self.store, "can_edit", True) is False:
            msg = "You have view-only access to this project."
            self.show_error(msg)
            return msg
        kind, bid, li, key = self.kind(r, c, extend=True)
        if kind is None:
            return ""
        sh = self.sheet
        text = "" if text is None else str(text)
        try:
            if kind in ("company", "phone", "contact"):
                b = ss.bidder(sh, bid)
                b[kind] = text.strip()
                if kind == "company":
                    self._fill_from_directory(b)
            elif kind == "price":
                ss.bidder(sh, bid)["price"] = ss.parse_money(text)
            elif kind == "bprice":
                sh["budget"]["price"] = ss.parse_money(text)
            elif kind in ("chk_ans", "chk_note"):
                src = ss.bidder(sh, bid) if bid else sh["budget"]
                if kind == "chk_ans":
                    src["checklist"][key]["ans"] = ss.parse_answer(text)
                else:
                    src["checklist"][key]["note"] = text.strip()
            else:
                ln = self._line(li)
                if ln is None:
                    if not text.strip():
                        return ""
                    while self.n_lines() <= li:
                        ln = ss.add_line(sh)
                if kind == "desc":
                    ln["desc"] = text.strip()
                elif kind == "qty":
                    ln["qty"] = ss.parse_qty(text)
                elif kind == "unit":
                    ln["unit"] = text.strip()
                elif kind == "uprice":
                    ln["unit_price"] = ss.parse_unit_price(text)
                    if ln["unit_price"] is not None and ln["qty"] is not None:
                        ln["lump"] = None
                elif kind == "btotal":
                    v = ss.parse_money(text)
                    if v != ss.budget_line_total(ln):
                        ln["lump"] = v      # a typed total: lump sum
                        ln["unit_price"] = None
                elif kind == "flag":
                    ss.set_bid(sh, ln["id"], bid, flag=text)
                elif kind == "amount":
                    ss.set_bid(sh, ln["id"], bid,
                               amount=ss.parse_money(text))
        except ss.ScopeError as e:
            self.show_error(str(e), r, c)
            return str(e)
        self.msg.setText("")
        self.changed(defer=defer, render=render)
        return ""

    def show_error(self, text, r=None, c=None):
        self.msg.setText(f"<span style='color:#b00020'>{text}</span>")
        try:
            if r is not None and self.isVisible():
                rect = self.grid.visualRect(self.grid.model().index(r, c))
                QToolTip.showText(self.grid.viewport().mapToGlobal(
                    rect.bottomLeft()), text, self.grid)
        except Exception:
            log.debug("tooltip", exc_info=True)

    # ------------------------------------------------------------ changes
    def changed(self, defer=False, render=True):
        if self.on_change is not None and self.sheet is not None:
            self.on_change(self.sheet)
        if not render:
            return
        if defer:
            if not self._pending:
                self._pending = True
                QTimer.singleShot(0, self._deferred_render)
        else:
            self.render()

    def _deferred_render(self):
        self._pending = False
        self.render()

    def _set_top(self, key, value):
        if self._loading or self.sheet is None:
            return
        if self.sheet.get(key) != value:
            self.sheet[key] = value
            self.changed()

    def _csi_done(self):
        if self._loading or self.sheet is None:
            return
        i = self.csi.currentIndex()
        txt = self.csi.currentText().strip()
        data = self.csi.itemData(i) if i >= 0 and \
            self.csi.itemText(i) == txt else None
        if data:
            code, name = data
            self._loading = True
            self.csi.setEditText(code)
            self._loading = False
            if not self.sheet.get("trade"):
                self.trade.setText(name)
                self.sheet["trade"] = name
        else:
            from ..csi import parse_code
            code = parse_code(txt.split("  ")[0]) or txt
        self._set_top("csi", code)

    def _set_header(self, key, value):
        if self._loading or self.sheet is None:
            return
        if self.sheet["header"].get(key) != value:
            self.sheet["header"][key] = value
            self.changed()

    def _level_changed(self, _i):
        if self._loading or self.sheet is None:
            return
        self.sheet["level"] = self.level.currentData() or "none"
        self.changed()

    def _award_changed(self, _i):
        if self._loading or self.sheet is None:
            return
        bid = self.award.currentData() or ""
        if self.sheet["award"].get("bidder") != bid:
            b = ss.bidder(self.sheet, bid) if bid else None
            if b is not None and not self.confirm_award(b):
                self.render()             # back to the award as it was
                return
            if b is None:
                self.sheet["award"].pop("override", None)
            self.sheet["award"]["bidder"] = bid
            self.sheet["award"]["amount"] = None
            self.changed()

    def _award_amount_done(self):
        if self._loading or self.sheet is None:
            return
        try:
            v = ss.parse_money(self.award_amt.text())
        except ss.ScopeError as e:
            self.show_error(str(e))
            return
        sh = self.sheet
        b = ss.bidder(sh, sh["award"].get("bidder") or "")
        if b is not None and v == ss.bidder_total(sh, b):
            v = None                      # same as the default: keep live
        if sh["award"].get("amount") != v:
            sh["award"]["amount"] = v
            self.changed()
        else:
            self.render()

    def _set_award(self, key, value):
        if self._loading or self.sheet is None:
            return
        if self.sheet["award"].get(key) != value:
            self.sheet["award"][key] = value
            self.changed()

    # ------------------------------------------------------------ editing
    def current_line(self):
        r = self.grid.currentRow()
        li = r - R_LINE0
        return li if 0 <= li < self.n_lines() else None

    def current_bidder(self):
        c = self.grid.currentColumn()
        if self.sheet is None or c < C_B0:
            return None
        k = (c - C_B0) // 2
        return self.sheet["bidders"][k] if k < len(self.sheet["bidders"]) \
            else None

    def add_line(self, desc=""):
        if self.sheet is None:
            return None
        li = self.current_line()
        ln = ss.add_line(self.sheet, desc,
                         None if li is None else li + 1)
        self.changed()
        i = self.sheet["lines"].index(ln)
        self.grid.setCurrentCell(R_LINE0 + i, C_DESC)
        return ln

    def remove_lines(self, indexes=None):
        if self.sheet is None:
            return 0
        if indexes is None:
            rows = {ix.row() for ix in self.grid.selectedIndexes()}
            if not rows and self.current_line() is not None:
                rows = {self.grid.currentRow()}
            indexes = sorted(r - R_LINE0 for r in rows
                             if 0 <= r - R_LINE0 < self.n_lines())
        ids = [self.sheet["lines"][i]["id"] for i in indexes
               if 0 <= i < self.n_lines()]
        for lid in ids:
            ss.remove_line(self.sheet, lid)
        if ids:
            self.changed()
        return len(ids)

    def move_line(self, delta):
        li = self.current_line()
        if li is None:
            return None
        j = ss.move_line(self.sheet, self.sheet["lines"][li]["id"], delta)
        self.changed()
        self.grid.setCurrentCell(R_LINE0 + j, self.grid.currentColumn())
        return j

    def add_bidder(self, company=""):
        if self.sheet is None:
            return None
        b = ss.add_bidder(self.sheet, company)
        self.changed()
        return b

    def remove_bidder(self, b=None, confirm=True):
        b = b or self.current_bidder()
        if b is None or self.sheet is None:
            return False
        has = b.get("company") or ss.active(self.sheet, b)
        if confirm and has and QMessageBox.question(
                self, "Remove Bidder",
                f"Remove {ss.bidder_name(self.sheet, b)} and every amount "
                "entered for them?") != QMessageBox.Yes:
            return False
        ss.remove_bidder(self.sheet, b["id"])
        self.changed()
        return True

    def from_package(self):
        if self.sheet is None or self.store is None:
            return 0
        n = ss.bidders_from_package(self.store, self.sheet)
        if n:
            self.changed()
            self.msg.setText(f"Added {n} bidder(s) from the bid package.")
        else:
            self.msg.setText("No bid package with new bidders for this "
                             "trade (Project Center > Bid Packages).")
        return n

    def clear_selection(self):
        cells = sorted({(ix.row(), self._span_col(ix.row(), ix.column()))
                        for ix in self.grid.selectedIndexes()})
        for r, c in cells:
            kind, _bid, li, _key = self.kind(r, c)
            if kind is None or (li is not None and li >= self.n_lines()):
                continue
            self.commit_text(r, c, "", render=False)
        self.changed()

    def copy_selection(self):
        ixs = self.grid.selectedIndexes()
        if not ixs:
            return ""
        r0, r1 = min(i.row() for i in ixs), max(i.row() for i in ixs)
        c0, c1 = min(i.column() for i in ixs), max(i.column() for i in ixs)
        text = "\n".join("\t".join(self.copy_text(r, c)
                                   for c in range(c0, c1 + 1))
                         for r in range(r0, r1 + 1))
        QApplication.clipboard().setText(text)
        return text

    def paste(self, text=None, at=None):
        """Paste tab-separated cells (from Excel) at the current cell;
        rows past the last line add lines. Returns the number of cells
        that couldn't be read."""
        if self.sheet is None:
            return 0
        if text is None:
            text = QApplication.clipboard().text()
        if not text:
            return 0
        r0, c0 = at if at is not None else (self.grid.currentRow(),
                                            self.grid.currentColumn())
        if r0 < 0 or c0 < 0:
            return 0
        rows = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if rows and rows[-1] == "":
            rows.pop()
        bad = []
        for i, line in enumerate(rows):
            for j, val in enumerate(line.split("\t")):
                r, c = r0 + i, c0 + j
                if r >= R_LINE0:
                    li = r - R_LINE0
                    if li >= self.n_lines() and not val.strip():
                        continue
                err = self.commit_text(r, c, val.strip('"'), render=False)
                if err:
                    bad.append(err)
        self.changed()
        if bad:
            self.show_error(f"{len(bad)} pasted cell(s) couldn't be read: "
                            f"{bad[0]}")
        else:
            self.msg.setText("")
        return len(bad)

    def move(self, step):
        r, c = self.grid.currentRow(), self.grid.currentColumn()
        n = self.grid.rowCount()
        r += step
        while 0 <= r < n:
            if self.kind(r, self._span_col(r, c))[0] is not None:
                self.grid.setCurrentCell(r, self._span_col(r, c))
                return
            r += step

    # ------------------------------------------------------------ directory
    def contacts(self):
        if self._contacts is None:
            try:
                from .. import subdir
                self._contacts = subdir.load()
            except Exception:
                log.debug("company directory", exc_info=True)
                self._contacts = []
        return self._contacts

    def directory_names(self):
        if self.sheet is None:
            return []
        first, rest = ss.directory_matches(
            self.contacts(), self.sheet.get("csi"), self.sheet.get("trade"))
        names, seen = [], set()
        for c in first + rest:
            n = (c.get("company") or "").strip()
            if n and n.lower() not in seen:
                seen.add(n.lower())
                names.append(n)
        return names

    def _fill_from_directory(self, b):
        name = (b.get("company") or "").strip().lower()
        if not name:
            return
        hit = next((c for c in self.contacts()
                    if (c.get("company") or "").strip().lower() == name),
                   None)
        if hit is None:
            return
        b["company"] = hit.get("company") or b["company"]
        b["directory_id"] = hit.get("id") or ""
        if not b.get("phone"):
            b["phone"] = hit.get("phone") or ""
        if not b.get("contact"):
            b["contact"] = hit.get("contact") or ""

    def pick_company(self, b=None):
        b = b or self.current_bidder()
        if b is None:
            return None
        names = self.directory_names()
        if not names:
            QMessageBox.information(
                self, "Company Directory", "Your Company Directory is empty "
                "(Project Center > Bidding > Company Directory). Type the "
                "company in the cell instead.")
            return None
        name, ok = QInputDialog.getItem(
            self, "Company Directory", "Bidder (this trade's companies "
            "first):", names, 0, True)
        if not ok or not name:
            return None
        b["company"] = name.strip()
        self._fill_from_directory(b)
        self.changed()
        return b

    def context_menu(self, pos):
        m = QMenu(self)
        m.addAction("Add Line", lambda: self.add_line())
        m.addAction("Remove Selected Lines", lambda: self.remove_lines())
        m.addAction("Move Line Up", lambda: self.move_line(-1))
        m.addAction("Move Line Down", lambda: self.move_line(1))
        m.addSeparator()
        m.addAction("Copy", lambda: self.copy_selection())
        m.addAction("Paste", lambda: self.paste())
        m.addAction("Clear", lambda: self.clear_selection())
        if self.current_bidder() is not None:
            m.addSeparator()
            m.addAction("Pick Company from Directory…",
                        lambda: self.pick_company())
            m.addAction("Recommend This Bidder for Award",
                        lambda: self.recommend(self.current_bidder()))
            m.addAction("Remove This Bidder", lambda: self.remove_bidder())
        m.exec(self.grid.viewport().mapToGlobal(pos))

    def recommend(self, b):
        if b is None or self.sheet is None:
            return
        self.sheet["award"]["bidder"] = b["id"]
        self.sheet["award"]["amount"] = None
        self.changed()

    # ------------------------------------------------------------ render
    def render(self):
        sh = self.sheet
        if sh is None:
            return
        g = self.grid
        nb = len(sh["bidders"])
        rows = self.row_check() + 1 + (1 if self.row_level() else 0)
        cols = C_B0 + 2 * nb
        cur = (g.currentRow(), g.currentColumn())
        if self._shape != (rows, cols):
            g.clearSpans()
            g.setRowCount(rows)
            g.setColumnCount(cols)
            self._shape = (rows, cols)
            hh = g.horizontalHeader()
            hh.setSectionResizeMode(QHeaderView.Interactive)
            g.setColumnWidth(C_DESC, 190)
            g.setColumnWidth(C_DESC2, 110)
            g.setColumnWidth(C_QTY, 72)
            g.setColumnWidth(C_UNIT, 48)
            g.setColumnWidth(C_UPRICE, 80)
            g.setColumnWidth(C_TOTAL, 112)
            for k in range(nb):
                a, b = _bidder_col(k)
                g.setColumnWidth(a, 44)
                g.setColumnWidth(b, 112)
                for r in (R_COMPANY, R_PHONE, R_CONTACT, R_PRICE):
                    g.setSpan(r, a, 1, 2)
            g.setSpan(R_COMPANY, C_QTY, 1, 4)
            g.setSpan(R_PRICE, C_QTY, 1, 4)
            for i in range(len(ss.CHECKLIST)):
                g.setSpan(R_CHECK + i, C_QTY, 1, 2)
                g.setSpan(R_CHECK + i, C_UPRICE, 1, 2)
            for r in range(rows):
                g.setSpan(r, C_DESC, 1, 2)
        heads = ["Scope", "", "Qty", "Unit", "Unit $",
                 ss.budget_label(sh, self.company)]
        for k in range(nb):
            heads += ["Incl", ss.bidder_name(sh, sh["bidders"][k], k)]
        g.setHorizontalHeaderLabels(heads)
        lv_mode = sh.get("level") or "none"
        lv = ss.leveled(sh, lv_mode)
        for r in range(rows):
            for c in range(cols):
                self._paint(r, c, lv)
        if 0 <= cur[0] < rows and 0 <= cur[1] < cols and \
                (g.currentRow(), g.currentColumn()) != cur:
            g.setCurrentCell(*cur)
        self._footer(lv_mode, lv)
        self.clar.refresh()

    def _item(self, r, c):
        it = self.grid.item(r, c)
        if it is None:
            it = QTableWidgetItem()
            self.grid.setItem(r, c, it)
        return it

    def _paint(self, r, c, lv):
        sh = self.sheet
        it = self._item(r, c)
        kind, bid, li, key = self.kind(r, c)
        text, align, bg, fg, bold, italic, tip = "", None, None, None, \
            False, False, ""
        is_b = c >= C_B0
        if kind is not None:
            text = self.edit_text(r, c)
            if kind in MONEY:
                align = Qt.AlignRight | Qt.AlignVCenter
                if kind == "uprice":
                    ln = self._line(li)
                    text = ss.fmt_unit_price(ln["unit_price"]) if ln else ""
                elif kind == "btotal":
                    ln = self._line(li)
                    text = ss.fmt_money(ss.budget_line_total(ln)) if ln \
                        else ""
                    if ln is not None and ln["qty"] is not None and \
                            ln["unit_price"] is not None:
                        tip = "Qty x Unit $ (type a total to use a lump sum)"
                else:
                    text = ("$" + text if text and not text.startswith("(")
                            else ("($" + text[1:] if text else ""))
                if text.startswith("("):
                    fg = NEG_FG
            elif kind == "qty":
                align = Qt.AlignRight | Qt.AlignVCenter
            elif kind in ("flag", "chk_ans"):
                align = Qt.AlignCenter
            if kind == "company":
                bold = True
            if is_b:
                bg = YELLOW
                fg = fg or INK
            elif kind in ("bprice", "chk_ans", "chk_note") or \
                    (li is not None and c in (C_QTY, C_UNIT, C_UPRICE,
                                              C_TOTAL)):
                bg = BUDGET_BG
                fg = fg or INK
            if kind == "amount" and li is not None and li < self.n_lines():
                plug = lv.get(bid, {}).get("plugs", {}).get(
                    sh["lines"][li]["id"])
                if plug:
                    text = ss.fmt_money(plug[0])
                    bg, fg, italic = PLUG_BG, GREY_INK, True
                    tip = (f"Plugged ({plug[1]}): this bidder excluded the "
                           "line. Type an amount to replace the plug.")
            if li is not None and li == self.n_lines() and c == C_DESC:
                text = ""
                tip = "Type here to add a scope line"
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable
        else:
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            text, align, bg, fg, bold, tip = self._fixed(r, c, lv)
        if it.text() != text:
            it.setText(text)
        it.setFlags(flags)
        if align is not None:
            it.setTextAlignment(align)
        else:
            it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        it.setBackground(QBrush(bg) if bg is not None else QBrush())
        it.setForeground(QBrush(fg) if fg is not None else QBrush())
        f = QFont(it.font())
        f.setBold(bold)
        f.setItalic(italic)
        it.setFont(f)
        it.setToolTip(tip)

    def _fixed(self, r, c, lv):
        """Labels, captions, totals and math check (read only)."""
        sh = self.sheet
        right = Qt.AlignRight | Qt.AlignVCenter
        k = (c - C_B0) // 2 if c >= C_B0 else None
        b = sh["bidders"][k] if k is not None and \
            k < len(sh["bidders"]) else None
        amount_col = k is not None and (c - C_B0) % 2 == 1
        if c == C_DESC2:
            return "", None, None, None, False, ""
        if c == C_DESC:
            labels = {R_COMPANY: "COMPANY", R_PHONE: "TELEPHONE",
                      R_CONTACT: "CONTACT", R_PRICE: "BID PRICE",
                      R_HEAD: "SCOPE", self.row_total(): "TOTAL PRICE",
                      self.row_check(): "MATH CHECK (Bid Price - Total)"}
            if self.row_level():
                labels[self.row_level()] = "LEVELED TOTAL"
            if R_CHECK <= r < R_HEAD:
                key, lab = ss.CHECKLIST[r - R_CHECK]
                if key == "addenda":
                    h = sh["header"]
                    lab = f"ADDENDA  {h.get('addenda_from') or '__'}  TO  " \
                          f"{h.get('addenda_to') or '__'}"
                return lab, None, None, None, False, ""
            bold = r in (R_HEAD, self.row_total(), self.row_level())
            return labels.get(r, ""), None, TOTAL_BG if r >= self.row_total() \
                or r == R_HEAD else None, INK if r >= self.row_total() or \
                r == R_HEAD else None, bold, ""
        if r == R_COMPANY and C_QTY <= c < C_B0:
            return ss.budget_label(sh, self.company), None, BUDGET_BG, INK, \
                True, ""
        if r == R_HEAD:
            cap = {C_QTY: "QTY", C_UNIT: "UNIT", C_UPRICE: "UNIT $",
                   C_TOTAL: "TOTAL"}.get(c, "")
            if k is not None:
                cap = "INCL" if not amount_col else "AMOUNT"
            return cap, Qt.AlignCenter, TOTAL_BG, INK, True, ""
        if r == self.row_total():
            if c == C_TOTAL:
                return ss.fmt_money(ss.budget_total(sh)), right, TOTAL_BG, \
                    INK, True, "Sum of the budget lines (or the budget " \
                    "price when there are none)"
            if amount_col and b is not None:
                t = ss.bidder_total(sh, b)
                return ss.fmt_money(t), right, TOTAL_BG, \
                    NEG_FG if t is not None and t < 0 else INK, True, \
                    "Sum of the scope amounts (or the bid price when the " \
                    "bid isn't broken down)"
            return "", None, TOTAL_BG, None, False, ""
        if r == self.row_check():
            m = None
            if c == C_TOTAL:
                m = ss.budget_math_check(sh)
            elif amount_col and b is not None:
                m = ss.math_check(sh, b)
            elif not (c == C_TOTAL or amount_col):
                return "", None, TOTAL_BG, None, False, ""
            bad = m is not None and m != 0
            return ss.fmt_money(m), right, BAD_BG if bad else TOTAL_BG, \
                BAD_FG if bad else INK, bad, \
                ("The bid price and the summed lines differ by "
                 f"{ss.fmt_money(m)}" if bad else
                 "Bid price minus the summed lines")
        if self.row_level() and r == self.row_level():
            if amount_col and b is not None:
                d = lv.get(b["id"]) or {}
                t = d.get("total")
                tip = (f"Includes {ss.fmt_money(d.get('plugged'))} plugged"
                       if d.get("plugged") else "Nothing plugged")
                if d.get("adjusted"):
                    tip += (f"; {ss.fmt_money(d['adjusted'])} of accepted "
                            "clarifications")
                return ss.fmt_money(t), right, PLUG_BG, INK, True, tip
            if c == C_TOTAL:
                return ss.fmt_money(ss.budget_total(sh)), right, PLUG_BG, \
                    INK, True, ""
            return "", None, PLUG_BG, None, False, ""
        return "", None, None, None, False, ""

    def _footer(self, lv_mode, lv):
        sh = self.sheet
        self._loading = True
        try:
            cur = sh["award"].get("bidder") or ""
            self.award.clear()
            self.award.addItem("(none)", "")
            for i, b in enumerate(sh["bidders"]):
                if b.get("company") or ss.active(sh, b):
                    self.award.addItem(ss.bidder_name(sh, b, i), b["id"])
            i = self.award.findData(cur)
            self.award.setCurrentIndex(max(0, i))
            dflt = None
            b = ss.bidder(sh, cur) if cur else None
            if b is not None:
                dflt = ss.bidder_total(sh, b)
            self.award_amt.setPlaceholderText(ss.fmt_money(dflt) or "")
            self.award_amt.setText(ss.fmt_money(sh["award"].get("amount")))
            self.award_amt.setEnabled(b is not None)
        finally:
            self._loading = False
        s = ss.summary(sh)
        bud = s["budget"]
        parts = [f"<b>{ss.budget_label(sh, self.company)}:</b> "
                 f"{ss.fmt_money(bud) or 'none'}"]
        if s["low_bidder"]:
            v, p = ss.spread(sh, s["low_bid"])
            parts.append(f"<b>Low bid:</b> {s['low_bidder']} "
                         f"{ss.fmt_money(s['low_bid'])}" + _vs(v, p))
        if (lv_mode != "none" or ss.has_adjustments(sh)) and \
                s["leveled_low_bidder"]:
            v, p = ss.spread(sh, s["leveled_low"])
            parts.append(f"<b>Leveled low:</b> {s['leveled_low_bidder']} "
                         f"{ss.fmt_money(s['leveled_low'])}" + _vs(v, p))
        if s["math_errors"]:
            parts.append(f"<span style='color:#b00020'><b>Math check:</b> "
                         f"{s['math_errors']} bidder(s) don't add up</span>")
        q = self.qualification_html()
        self.summary.setText("  ·  ".join(parts) + ("<br>" + q if q else ""))

    # -------------------------------------------------------- qualification
    def contact_for(self, b):
        """The bidder's Company Directory entry, or None."""
        from .. import qualify
        cs = self.contacts()
        did = b.get("directory_id")
        hit = next((c for c in cs if did and c.get("id") == did), None)
        return hit or qualify.find(b.get("company"), cs)

    def bidder_badges(self, b):
        from .. import qualify
        t = ss.bidder_total(self.sheet, b)
        return qualify.badges(self.contact_for(b),
                              None if t is None else t / 100)

    def qualification_html(self):
        from .. import qualify
        sh = self.sheet
        if sh is None:
            return ""
        return qualify.html([
            (ss.bidder_name(sh, b, i), self.bidder_badges(b))
            for i, b in enumerate(sh["bidders"])
            if b.get("company") or ss.active(sh, b)])

    def award_warnings(self, b):
        from .. import qualify
        t = ss.bidder_total(self.sheet, b)
        return qualify.award_warnings(self.contact_for(b),
                                      None if t is None else t / 100)

    def confirm_award(self, b, reason=None):
        """True when the award may go to this bidder. With a qualification
        warning (expired insurance or license, over the bonding or the
        approved limit) a reason is asked for and kept on the award."""
        from .. import qualify
        warn = self.award_warnings(b)
        if not warn:
            self.sheet["award"].pop("override", None)
            return True
        if reason is None:
            reason, ok = QInputDialog.getText(
                self, "Recommended Award",
                ss.bidder_name(self.sheet, b) + ":\n- " + "\n- ".join(warn)
                + "\n\nTo award anyway, give the reason (it is kept with "
                "the award):")
            if not ok:
                return False
        try:
            self.sheet["award"]["override"] = qualify.override(
                ss.bidder_name(self.sheet, b), warn, reason,
                settings.get("author", "") or "")
        except ValueError:
            return False
        return True


# ======================================================== clarifications
class ClarificationsBox(QWidget):
    """Per bidder: qualifications / exclusions / clarifications, each with
    an optional $ adjustment and Accept / Reject / Pending. Accepted
    amounts go into the bidder's leveled total (a credit deducts);
    rejected rows stay as the award record. Beside the list, the budget
    column: budget, as bid, plugged, accepted, leveled, vs budget."""

    COLS = ["Type", "Qualification / exclusion / clarification",
            "Adjustment", "Status"]
    C_KIND, C_TEXT, C_AMT, C_STATUS = range(4)

    def __init__(self, editor):
        super().__init__(editor)
        self.ed = editor
        self._shown = None             # (bidder id, row ids) in the table
        self._loading = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel("<b>Clarifications</b> for"))
        self.bidder = QComboBox()
        self.bidder.setMinimumWidth(200)
        self.bidder.currentIndexChanged.connect(lambda _i: self.refresh())
        top.addWidget(self.bidder)
        self.add_btn = QPushButton("Add")
        self.add_btn.setToolTip("Add a qualification, exclusion or "
                                "clarification for this bidder")
        self.add_btn.clicked.connect(lambda: self.add_row())
        self.del_btn = QPushButton("Remove")
        self.del_btn.setToolTip("Remove the selected rows")
        self.del_btn.clicked.connect(lambda: self.remove_rows())
        self.imp_btn = QPushButton("Import from Proposal…")
        self.imp_btn.setToolTip("Read the exclusions listed in this "
                                "bidder's proposal PDF (text PDFs) as "
                                "Pending rows")
        self.imp_btn.clicked.connect(lambda: self.import_from_proposal())
        self.ai_btn = QPushButton("Import with AI…")
        self.ai_btn.setToolTip("Read the proposal with the AI on this PC "
                               "(nothing leaves the computer). Only what "
                               "is in the quote word for word is offered, "
                               "and you accept each one")
        self.ai_btn.clicked.connect(
            lambda: self.import_from_proposal(ai=True))
        self.src_btn = QPushButton("Show Source")
        self.src_btn.setToolTip("Open the bidder's proposal at the words "
                                "this row was read from (rows made by "
                                "Import from Proposal)")
        self.src_btn.clicked.connect(lambda: self.show_source())
        self.ex_btn = QPushButton("Compare Exclusions…")
        self.ex_btn.setToolTip("Who excludes what, side by side: every "
                               "bidder's Exclusion rows in one table")
        self.ex_btn.clicked.connect(lambda: self.compare_exclusions())
        for b in (self.add_btn, self.del_btn, self.imp_btn, self.ai_btn,
                  self.src_btn, self.ex_btn):
            top.addWidget(b)
        top.addStretch()
        v.addLayout(top)
        row = QHBoxLayout()
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(self.C_TEXT, QHeaderView.Stretch)
        self.table.setColumnWidth(self.C_KIND, 120)
        self.table.setColumnWidth(self.C_AMT, 110)
        self.table.setColumnWidth(self.C_STATUS, 96)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._item_changed)
        row.addWidget(self.table, 1)
        self.budget = QLabel("")
        self.budget.setMinimumWidth(230)
        self.budget.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.budget.setWordWrap(True)
        self.budget.setTextFormat(Qt.RichText)
        row.addWidget(self.budget)
        v.addLayout(row, 1)

    # ------------------------------------------------------------ state
    def sheet(self):
        return self.ed.sheet

    def current_bidder(self):
        sh = self.sheet()
        bid = self.bidder.currentData()
        return ss.bidder(sh, bid) if sh is not None and bid else None

    def follow_grid(self, c):
        """The grid's current column is a bidder's: show theirs."""
        sh = self.sheet()
        if sh is None or c < C_B0:
            return
        k = (c - C_B0) // 2
        if k < len(sh["bidders"]):
            i = self.bidder.findData(sh["bidders"][k]["id"])
            if i >= 0 and i != self.bidder.currentIndex():
                self.bidder.setCurrentIndex(i)

    def select_bidder(self, b):
        i = self.bidder.findData(b["id"] if isinstance(b, dict) else b)
        if i >= 0:
            self.bidder.setCurrentIndex(i)
        return i >= 0

    def refresh(self):
        sh = self.sheet()
        cur = self.bidder.currentData()
        items = [] if sh is None else [
            (ss.bidder_name(sh, b, i), b["id"])
            for i, b in enumerate(sh["bidders"])]
        have = [(self.bidder.itemText(i), self.bidder.itemData(i))
                for i in range(self.bidder.count())]
        if have != items:
            self.bidder.blockSignals(True)
            try:
                self.bidder.clear()
                for name, bid in items:
                    self.bidder.addItem(name, bid)
                i = self.bidder.findData(cur)
                self.bidder.setCurrentIndex(max(0, i) if items else -1)
            finally:
                self.bidder.blockSignals(False)
        b = self.current_bidder()
        on = b is not None
        for w in (self.add_btn, self.del_btn, self.imp_btn, self.table):
            w.setEnabled(on)
        rows = ss.clarifications(sh, b) if on else []
        shown = (b["id"], tuple(c["id"] for c in rows)) if on else None
        if shown != self._shown:
            self._fill(rows)
            self._shown = shown
        self._budget(b)

    def _fill(self, rows):
        self._loading = True
        try:
            t = self.table
            t.setRowCount(0)
            t.setRowCount(len(rows))
            for r, c in enumerate(rows):
                kind = QComboBox()
                kind.addItems(list(ss.CLAR_KINDS))
                kind.setCurrentText(c["kind"])
                kind.currentTextChanged.connect(
                    lambda txt, cid=c["id"]: self._set(cid, kind=txt))
                t.setCellWidget(r, self.C_KIND, kind)
                it = QTableWidgetItem(c["text"])
                it.setData(Qt.UserRole, c["id"])
                t.setItem(r, self.C_TEXT, it)
                amt = QTableWidgetItem(ss.fmt_money(c["amount"]))
                amt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                amt.setData(Qt.UserRole, c["id"])
                amt.setToolTip("Blank = no $; 500 adds, (500) or -500 "
                               "deducts. Counted only when accepted.")
                if c["amount"] is not None and c["amount"] < 0:
                    amt.setForeground(QBrush(NEG_FG))
                t.setItem(r, self.C_AMT, amt)
                st = QComboBox()
                for key in ss.CLAR_STATUS:
                    st.addItem(ss.CLAR_STATUS_LABEL[key], key)
                st.setCurrentIndex(max(0, st.findData(c["status"])))
                st.currentIndexChanged.connect(
                    lambda _i, cid=c["id"], w=st: self._set(
                        cid, status=w.currentData()))
                t.setCellWidget(r, self.C_STATUS, st)
        finally:
            self._loading = False

    def _budget(self, b):
        sh = self.sheet()
        if sh is None or b is None:
            self.budget.setText("")
            return
        lab = ss.budget_label(sh, self.ed.company)
        d = ss.leveled(sh).get(b["id"]) or {}
        n = ss.clarification_counts(sh, b)
        var, pct = ss.spread(sh, d.get("total"))

        def row(k, v, bold=False):
            v = v or "-"
            return (f"<tr><td>{k}</td><td align='right'>"
                    + (f"<b>{v}</b>" if bold else v) + "</td></tr>")
        html = ("<table cellspacing='2'>"
                + row(lab, ss.fmt_money(ss.budget_total(sh)), True)
                + row("As bid", ss.fmt_money(d.get("base")))
                + (row("Plugged", ss.fmt_money(d.get("plugged")))
                   if d.get("plugged") else "")
                + row("Accepted adjustments",
                      ss.fmt_money(d.get("adjusted") or 0))
                + row("Leveled total", ss.fmt_money(d.get("total")), True)
                + (row("vs " + lab, ss.fmt_money(var) +
                       (f" ({pct}%)" if pct is not None else ""))
                   if var is not None else "")
                + "</table>"
                f"<small>{n['accepted']} accepted · {n['pending']} pending"
                f" · {n['rejected']} rejected (kept as the award record, "
                "not counted)</small>")
        self.budget.setText(html)

    # ------------------------------------------------------------ edits
    def _editable(self):
        st = self.ed.store
        if st is not None and getattr(st, "can_edit", True) is False:
            self.ed.show_error("You have view-only access to this project.")
            return False
        return True

    def _done(self):
        self.ed.changed(render=False)
        self.ed.render()               # leveled row, totals, summary

    # ------------------------------------------------- exclusions compare
    def compare_exclusions(self, show=True):
        """The Exclusions table for this sheet's bidders. Returns the
        dialog (shown unless show=False)."""
        from ..exclusions_ui import ExclusionsDialog
        sh = self.sheet()
        if sh is None:
            return None
        dlg = ExclusionsDialog(
            self, "Exclusions - " + (ss.title(sh) or "Scope Sheet"),
            ("Set $ adjustment…", lambda n, w: self.price_exclusion(
                n, w, dlg=dlg)))
        dlg.panel.source = lambda n, w: self.show_source(name=n, wording=w)
        dlg.panel.set_bids(ss.exclusion_bids(sh), sh.get("ex_moves"))
        dlg.panel.moves_changed.connect(self._moves_changed)
        if show:
            dlg.exec()
        return dlg

    def source_for(self, row=None, name=None, wording=None):
        """The stored source of a row: the selected one, or the named
        bidder's Exclusion row with that wording. None when it has none."""
        sh = self.sheet()
        if sh is None:
            return None, ""
        if name is not None:
            b = next((x for i, x in enumerate(sh["bidders"])
                      if ss.bidder_name(sh, x, i) == name), None)
            c = ss.exclusion_row(sh, b, wording) if b else None
        else:
            b = self.current_bidder()
            lst = ss.clarifications(sh, b) if b else []
            r = self.table.currentRow() if row is None else row
            c = lst[r] if 0 <= r < len(lst) else None
        return (c or {}).get("src"), (c or {}).get("text", "")

    def show_source(self, row=None, name=None, wording=None, modal=True):
        from .. import source_view
        src, text = self.source_for(row, name, wording)
        return source_view.show(self, src, text, modal=modal)

    def _moves_changed(self, moves):
        sh = self.sheet()
        if sh is None:
            return
        if moves:
            sh["ex_moves"] = dict(moves)
        else:
            sh.pop("ex_moves", None)
        self.ed.changed(render=False)

    def price_exclusion(self, name, wording, amount=None, dlg=None):
        """One click from the Exclusions table: put a $ adjustment on the
        bidder's Exclusion row (it stays Pending until you accept or
        reject it, as before)."""
        sh = self.sheet()
        b = next((x for i, x in enumerate(sh["bidders"])
                  if ss.bidder_name(sh, x, i) == name), None)
        if b is None:
            return None
        c = ss.exclusion_row(sh, b, wording)
        if c is None:
            c = ss.add_clarification(sh, b, wording, "Exclusion")
        if amount is None:
            text, ok = QInputDialog.getText(
                self, "Exclusion", f"{name} excludes \"{wording}\".\n"
                "What it will cost to cover it ($, a credit in "
                "parentheses):", text=ss.plain_money(c.get("amount")) or "")
            if not ok:
                return None
            try:
                amount = ss.parse_money(text)
            except ss.ScopeError as e:
                self.ed.show_error(str(e))
                return None
        if amount is None:
            ss.set_clarification(sh, b, c["id"], clear_amount=True)
        else:
            ss.set_clarification(sh, b, c["id"], amount=amount)
        i = self.bidder.findData(b["id"])
        if i >= 0:
            self.bidder.setCurrentIndex(i)
        self._done()
        self.refresh()
        return c

    def _set(self, cid, **kw):
        if self._loading or not self._editable():
            return False
        b = self.current_bidder()
        if b is None:
            return False
        try:
            ss.set_clarification(self.sheet(), b, cid, **kw)
        except ss.ScopeError as e:
            self.ed.show_error(str(e))
            return False
        self._done()
        return True

    def set_row(self, r, **kw):
        """Change row r of the shown bidder (text=, kind=, amount= cents,
        status=, clear_amount=) as the cells would; refreshes the cells."""
        b = self.current_bidder()
        lst = ss.clarifications(self.sheet(), b) if b else []
        if not 0 <= r < len(lst):
            return False
        ok = self._set(lst[r]["id"], **kw)
        self._shown = None
        self.refresh()
        return ok

    def _item_changed(self, it):
        if self._loading:
            return
        cid = it.data(Qt.UserRole)
        if not cid:
            return
        if it.column() == self.C_TEXT:
            self._set(cid, text=it.text())
        elif it.column() == self.C_AMT:
            try:
                v = ss.parse_money(it.text())
            except ss.ScopeError as e:
                self.ed.show_error(str(e))
                self._shown = None         # put the stored $ back, later:
                QTimer.singleShot(0, self.refresh)   # not inside the signal
                return
            if v is None:
                self._set(cid, clear_amount=True)
            else:
                self._set(cid, amount=v)
            self._loading = True
            try:
                it.setText(ss.fmt_money(v))
                it.setForeground(QBrush(NEG_FG) if v is not None and v < 0
                                 else QBrush())
            finally:
                self._loading = False

    def add_row(self, text="", kind="Clarification", amount=None,
                status="pending"):
        b = self.current_bidder()
        if b is None or not self._editable():
            return None
        c = ss.add_clarification(self.sheet(), b, text, kind, amount, status)
        self._done()
        r = len(ss.clarifications(self.sheet(), b)) - 1
        self.table.setCurrentCell(r, self.C_TEXT)
        return c

    def remove_rows(self, rows=None):
        b = self.current_bidder()
        if b is None or not self._editable():
            return 0
        if rows is None:
            rows = {ix.row() for ix in self.table.selectedIndexes()}
            if not rows and self.table.currentRow() >= 0:
                rows = {self.table.currentRow()}
        lst = ss.clarifications(self.sheet(), b)
        ids = [lst[r]["id"] for r in sorted(rows) if 0 <= r < len(lst)]
        for cid in ids:
            ss.remove_clarification(self.sheet(), b, cid)
        if ids:
            self._done()
        return len(ids)

    def import_from_proposal(self, path=None, ai=False, ask=None,
                             review=None):
        """Prefill rows from a sub's proposal PDF (proposal_level.parse):
        its exclusions as Pending rows with no $. Returns how many were
        added. ai=True: Read with AI first (the local model; you accept
        each value it found in the quote) - for a quote whose exclusions
        the patterns didn't find."""
        b = self.current_bidder()
        if b is None or not self._editable():
            return 0
        if path is None:
            path, _f = QFileDialog.getOpenFileName(
                self, "Import from Proposal", "", "PDF (*.pdf)")
            if not path:
                return 0
        try:
            from .. import proposal_level
            p = proposal_level.parse(path)
        except Exception as e:                            # noqa: BLE001
            log.warning("proposal not read", exc_info=True)
            self.ed.show_error(f"Couldn't read that proposal: {e}")
            return 0
        if ai:
            from .. import proposal_ai_ui
            p = (review or proposal_ai_ui.offer)(self, p, ask)
            if p is None:
                return 0
        have = [c["text"] for c in ss.clarifications(self.sheet(), b)]
        rows = ss.rows_from_proposal(p, have)
        b.setdefault("clar", []).extend(rows)
        name = os.path.basename(path)
        if rows:
            self._done()
            self.ed.msg.setText(f"Added {len(rows)} row(s) from {name} as "
                                "Pending - price them, then accept or "
                                "reject each.")
        else:
            self.ed.msg.setText(f"No new exclusions found in {name}. If "
                                "the quote lists some, Import with AI can "
                                "look for them.")
        return len(rows)


def _vs(v, p):
    """' ($1,200.00 under budget, 4.1%)'."""
    if v is None:
        return ""
    word = "over" if v > 0 else "under" if v < 0 else "on"
    pct = f", {abs(p)}%" if p is not None and v else ""
    return f" ({ss.fmt_money(abs(v))} {word} budget{pct})"


def split_trade(text):
    """'09 29 00  Drywall & framing' -> ('09 29 00', 'Drywall & framing');
    no code -> ('', text)."""
    import re
    from ..csi import parse_code
    t = (text or "").strip()
    m = re.match(r"^(\d{2}[\s.]?\d{2}[\s.]?\d{2}(?:\.\d{1,2})?)"
                 r"\s*[-:]?\s*(.*)$", t)
    if m and parse_code(m.group(1)):
        return parse_code(m.group(1)), m.group(2).strip()
    return "", t


def _trade_choices():
    """CSI sections for the picker: the bid package trades, then the
    MasterFormat divisions."""
    out, seen = [], set()
    try:
        from .bidui import TRADES
        for code, name, _form in TRADES:
            out.append((code, name))
            seen.add(code)
    except Exception:
        log.debug("bid trades", exc_info=True)
    for code, name in ss.trade_choices():
        if code not in seen:
            out.append((code, name))
    out.sort()
    return out


# ======================================================== the list + editor
LIST_COLS = ["CSI", "Trade", "Budget", "Low Bid", "Recommended Award",
             "Award Amount", "Variance"]


class ScopeSheetsPanel(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.sheets = []
        self.company = ss.company_info(store)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        ic = QLabel()
        try:
            ic.setPixmap(icons.icon("scopesheet").pixmap(22, 22))
        except Exception:
            pass
        top.addWidget(ic)
        t = QLabel("Scope Sheets")
        t.setObjectName("pcH1")
        t.setStyleSheet("font-size:13pt;font-weight:700")
        top.addWidget(t)
        self.note = QLabel(store.name if store is not None else "")
        self.note.setObjectName("muted")
        top.addWidget(self.note)
        top.addStretch()
        for label, tip, fn, primary in (
                ("New Trade…", "A scope sheet for another trade",
                 lambda: self.new_sheet(), True),
                ("Duplicate", "Copy the selected sheet (lines, bidders, "
                 "budget) for another trade", lambda: self.duplicate(),
                 False),
                ("Delete", "Delete the selected sheet",
                 lambda: self.delete(), False),
                ("Import Excel…", "Read scope sheets from a workbook in the "
                 "Scope Sheet layout (one tab per trade)",
                 lambda: self.import_xlsx(), False),
                ("Export Excel…", "Every sheet as a workbook with live "
                 "formulas: one tab per trade plus a Summary",
                 lambda: self.export_xlsx(), False),
                ("Export PDF…", "The selected sheet (or all) as a PDF",
                 lambda: self.export_pdf(), False),
                ("Use Award in Estimate", "Put each awarded trade in the "
                 "open drawing's estimate as one Subcontract line (CSI "
                 "code, trade, award amount), replacing that trade's "
                 "allowance line; running it again updates the lines",
                 lambda: self.use_award_in_estimate(), False)):
            b = QPushButton(label)
            b.setToolTip(tip)
            if primary:
                b.setObjectName("primary")
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            top.addWidget(b)
        v.addLayout(top)
        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, len(LIST_COLS))
        self.table.setHorizontalHeaderLabels(LIST_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._picked)
        self.table.setMinimumHeight(90)
        split.addWidget(self.table)
        self.editor = ScopeSheetEditor(store, self, on_change=self._edited)
        split.addWidget(self.editor)
        split.setStretchFactor(1, 1)
        split.setSizes([150, 600])
        v.addWidget(split, 1)
        self.empty = QLabel("No scope sheets yet. <b>New Trade…</b> starts "
                            "one (one sheet per trade), or <b>Import "
                            "Excel…</b> reads your existing Scope Sheet "
                            "workbooks.")
        self.empty.setObjectName("muted")
        v.addWidget(self.empty)
        self.refresh()

    # ------------------------------------------------------------ list
    def refresh(self, select_id=None):
        cur = self.current()
        select_id = select_id or (cur.get("_id") if cur else None)
        self.sheets = ss.list_sheets(self.store) if self.store is not None \
            else []
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.sheets))
        for i, sh in enumerate(self.sheets):
            self._fill_row(i, sh)
        self.table.blockSignals(False)
        self.empty.setVisible(not self.sheets)
        row = next((i for i, s in enumerate(self.sheets)
                    if s.get("_id") == select_id), 0 if self.sheets else -1)
        if row >= 0:
            self.table.selectRow(row)
        self._picked()

    def _fill_row(self, i, sh):
        s = ss.summary(sh)
        aw = s["award_bidder"]
        var = s["variance"]
        cells = [s["csi"], s["trade"], ss.fmt_money(s["budget"]),
                 (ss.fmt_money(s["low_bid"]) + (f"  {s['low_bidder']}"
                                                if s["low_bidder"] else "")),
                 aw, ss.fmt_money(s["award_amount"]),
                 (ss.fmt_money(var) + (f"  ({s['variance_pct']}%)"
                                       if s["variance_pct"] is not None
                                       else "")) if var is not None else ""]
        for c, text in enumerate(cells):
            it = self.table.item(i, c)
            if it is None:
                it = QTableWidgetItem()
                self.table.setItem(i, c, it)
            it.setText(text)
            if c in (2, 3, 5, 6):
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if c == 6 and var is not None:
                it.setForeground(QBrush(NEG_FG if var > 0 else
                                        QColor(0, 120, 60)))
            if c == 3 and s["math_errors"]:
                it.setToolTip("A bidder's math check is off")

    def current(self):
        r = self.table.currentRow()
        rows = self.table.selectionModel().selectedRows() \
            if self.table.selectionModel() else []
        if rows:
            r = rows[0].row()
        return self.sheets[r] if 0 <= r < len(self.sheets) else None

    def _picked(self):
        self.editor.set_sheet(self.current())

    def _edited(self, sheet):
        if self.store is not None:
            ss.save_sheet(self.store, sheet)
        i = next((n for n, s in enumerate(self.sheets) if s is sheet), None)
        if i is not None:
            self._fill_row(i, sheet)

    # ------------------------------------------------------------ commands
    def new_sheet(self, csi=None, trade=None):
        if csi is None and trade is None:
            items = [f"{c}  {n}" for c, n in _trade_choices()]
            text, ok = QInputDialog.getItem(
                self, "New Scope Sheet", "Trade (CSI section and name - "
                "pick one or type your own):", items, 0, True)
            if not ok or not text:
                return None
            csi, trade = split_trade(text)
        header = ss.prefill_header(self.store, csi or "", trade or "")
        sh = ss.new_sheet(csi or "", trade or "", header=header)
        if self.store is not None:
            ss.save_sheet(self.store, sh)
        self.refresh(sh.get("_id"))
        return self.current()

    def duplicate(self, trade=None):
        sh = self.current()
        if sh is None:
            return None
        new = ss.duplicate(sh, trade)
        ss.save_sheet(self.store, new)
        self.refresh(new.get("_id"))
        return self.current()

    def delete(self, confirm=True):
        sh = self.current()
        if sh is None:
            return False
        if confirm and QMessageBox.question(
                self, "Delete Scope Sheet",
                f"Delete the scope sheet for {ss.title(sh)}?") != \
                QMessageBox.Yes:
            return False
        ss.delete_sheet(self.store, sh)
        self.refresh()
        return True

    def use_award_in_estimate(self, doc=None, sheets=None, confirm=True,
                              main=None, today=None):
        """Scope Sheets > Use Award in Estimate: one Subcontract line per
        awarded trade in the open drawing's estimate (award_estimate.py).
        Returns the report rows, or None when nothing was done."""
        from .. import award_estimate
        sheets = self.sheets if sheets is None else sheets
        mw = main
        if doc is None:
            mw = mw or _main_window(self)
            v = getattr(mw, "_view", None) if mw is not None else None
            doc = v.doc if v is not None else None
        if doc is None:
            QMessageBox.information(
                self, "Use Award in Estimate", "Open the drawing whose "
                "estimate should get the awards, then try again.")
            return None
        aw = award_estimate.awards(sheets)
        if not aw:
            QMessageBox.information(
                self, "Use Award in Estimate", "No trade has a recommended "
                "award yet. Pick the bidder under Recommended award to.")
            return None
        if confirm and QMessageBox.question(
                self, "Use Award in Estimate",
                f"Put {len(aw)} awarded trade(s) in the estimate as "
                "Subcontract lines? A trade's allowance line is marked "
                "replaced (kept, quantity 0); lines already added from "
                "these sheets are updated.") != QMessageBox.Yes:
            return None
        try:
            report = award_estimate.apply(doc, sheets, today)
        except Exception as e:                            # noqa: BLE001
            log.warning("award to estimate failed", exc_info=True)
            QMessageBox.warning(self, "Use Award in Estimate",
                                f"The estimate wasn't changed: {e}")
            return None
        if mw is not None and any(r["action"] != "unchanged"
                                  for r in report):
            for fn in ("_doc_edited", "_show_estimate"):
                try:
                    getattr(mw, fn)()
                except Exception:                         # noqa: BLE001
                    log.debug(fn, exc_info=True)
            for panel in ("estimate", "assemblies"):
                try:
                    getattr(mw, panel).refresh()
                except Exception:                         # noqa: BLE001
                    log.debug(panel, exc_info=True)
        QMessageBox.information(self, "Use Award in Estimate",
                                award_estimate.describe(report))
        return report

    def _default_dir(self):
        if self.store is not None and os.path.isdir(self.store.folder):
            return self.store.folder
        return settings.last_dir() if hasattr(settings, "last_dir") else ""

    def _open(self, path):
        if path and not os.environ.get("QUANTISHEET_NO_OPEN"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def import_xlsx(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import Scope Sheets", self._default_dir(),
                "Excel workbook (*.xlsx *.xlsm)")
        if not path:
            return []
        try:
            sheets, _skipped = ss.import_xlsx(path)
        except Exception as e:
            log.info("scope sheet import failed", exc_info=True)
            QMessageBox.warning(self, "Import Scope Sheets",
                                f"Couldn't read that workbook:\n{e}")
            return []
        if not sheets:
            QMessageBox.information(
                self, "Import Scope Sheets", "No tab in that workbook is laid "
                "out like a Scope Sheet (TRADE in cell B4).")
            return []
        pre = ss.prefill_header(self.store) if self.store is not None else {}
        last = None
        for sh in sheets:
            for k in ("project", "project_no"):
                if not sh["header"].get(k):
                    sh["header"][k] = pre.get(k, "")
            if self.store is not None:
                ss.save_sheet(self.store, sh)
            last = sh
        self.refresh(last.get("_id") if last else None)
        self.editor.msg.setText(f"Imported {len(sheets)} scope sheet(s).")
        return sheets

    def export_xlsx(self, path=None, sheets=None, open_after=True):
        sheets = sheets if sheets is not None else self.sheets
        if not sheets:
            QMessageBox.information(self, "Export Scope Sheets",
                                    "There are no scope sheets to export.")
            return None
        if path is None:
            name = report_file_name(
                "Scope Sheets",
                self.store.name if self.store is not None else "",
                ext=".xlsx")
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Scope Sheets (Excel)",
                os.path.join(self._default_dir(), name),
                "Excel workbook (*.xlsx)")
        if not path:
            return None
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            ss.export_xlsx(sheets, path, self.company,
                           self.store.name if self.store is not None
                           else "")
        except OSError as e:
            QMessageBox.warning(self, "Export Scope Sheets",
                                f"Couldn't save the workbook (is it open in "
                                f"Excel?):\n{e}")
            return None
        if open_after:
            self._open(path)
        return path

    def export_pdf(self, path=None, which=None, open_after=True):
        if not self.sheets:
            QMessageBox.information(self, "Export Scope Sheets",
                                    "There are no scope sheets to export.")
            return None
        if which is None:
            which = "all"
            if path is None and len(self.sheets) > 1 and \
                    self.current() is not None:
                opts = ["This sheet", "All sheets"]
                pick, ok = QInputDialog.getItem(
                    self, "Export PDF", "Export:", opts, 0, False)
                if not ok:
                    return None
                which = "one" if pick == opts[0] else "all"
        sheets = [self.current()] if which == "one" and self.current() \
            else self.sheets
        if path is None:
            if len(sheets) == 1:
                csi = str(sheets[0].get("csi") or "").strip()
                trade = str(sheets[0].get("trade") or "").strip()
                kind = "Scope Sheet" + (f" {csi}" if csi else "") + \
                    (f" - {trade}" if trade else "")
            else:
                kind = "Scope Sheets"
            base = report_file_name(
                kind, self.store.name if self.store is not None else "",
                ext=".pdf")
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Scope Sheets (PDF)",
                os.path.join(self._default_dir(), base),
                "PDF (*.pdf)")
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            ss.export_pdf(sheets, path, self.company, self.store)
        except Exception as e:
            log.info("scope sheet pdf failed", exc_info=True)
            QMessageBox.warning(self, "Export Scope Sheets",
                                f"Couldn't save the PDF:\n{e}")
            return None
        if open_after:
            self._open(path)
        return path


def _main_window(w):
    """The QuantiSheet window above `w` (or any open one with a drawing):
    the one whose estimate gets the awards."""
    p = w
    while p is not None:
        if hasattr(p, "_view") and hasattr(p, "estimate"):
            return p
        p = p.parent()
    for top in QApplication.topLevelWidgets():
        if hasattr(top, "_view") and hasattr(top, "estimate") and \
                getattr(top, "_view", None) is not None:
            return top
    return None


class ScopeSheetsDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(f"Scope Sheets - {store.name}")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1400, 860)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        self.panel = ScopeSheetsPanel(store, self)
        v.addWidget(self.panel)

    def closeEvent(self, e):
        try:
            self.store.flush()
        except Exception:
            log.debug("flush", exc_info=True)
        super().closeEvent(e)


class ScopeSheetsPage(QWidget):
    """Project Center > Bidding > Scope Sheets."""

    def __init__(self, center):
        super().__init__()
        self.center = center
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        self.panel = ScopeSheetsPanel(center.store, self)
        v.addWidget(self.panel)

    def refresh(self):
        self.panel.refresh()


# ======================================================== opening
def choose_project(parent=None):
    """Recent projects, or a folder. Returns a store or None."""
    from .store import ProjectStore, open_store
    recent = [f for f in settings.get("pm_recent", []) or []
              if os.path.isdir(f) and ProjectStore.exists(f)]
    d = QDialog(parent)
    d.setWindowTitle("Scope Sheets")
    d.setMinimumWidth(520)
    v = QVBoxLayout(d)
    v.addWidget(QLabel("Scope sheets belong to a project. Open one:"))
    lw = QListWidget()
    for f in recent:
        try:
            name = ProjectStore(f).name
        except Exception:
            name = os.path.basename(f)
        it = QListWidgetItem(icons.icon("folder"), f"{name}\n{f}")
        it.setData(Qt.UserRole, f)
        lw.addItem(it)
    v.addWidget(lw)
    out = {}

    def pick(it=None):
        it = it or lw.currentItem()
        if it is not None:
            out["folder"] = it.data(Qt.UserRole)
            d.accept()

    def browse():
        f = QFileDialog.getExistingDirectory(d, "Project folder")
        if f:
            out["folder"] = f
            d.accept()
    lw.itemDoubleClicked.connect(pick)
    row = QHBoxLayout()
    b = QPushButton("Choose Folder…")
    b.clicked.connect(browse)
    row.addWidget(b)
    row.addStretch()
    ok = QPushButton("Open")
    ok.setDefault(True)
    ok.clicked.connect(lambda: pick())
    row.addWidget(ok)
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(d.reject)
    row.addWidget(cancel)
    v.addLayout(row)
    if d.exec() and out.get("folder"):
        return open_store(out["folder"])
    return None


def store_for_path(path):
    """The project of an open drawing's folder (or its parent)."""
    from .store import ProjectStore, open_store
    if not path:
        return None
    d = os.path.dirname(os.path.abspath(path))
    for folder in (d, os.path.dirname(d)):
        if ProjectStore.exists(folder):
            return open_store(folder)
    return None


def open_scope_sheets(store, parent=None):
    w = ScopeSheetsDialog(store, parent)
    w.show()
    if parent is not None:
        parent._scope_sheets = w
    return w


def open_for_window(main, store=None):
    """Estimate > Scope Sheets: the open drawing's project, else ask
    which project (no project chosen: nothing opens)."""
    if store is None:
        store = store_for_path(getattr(main, "_path", None))
    if store is None:
        store = choose_project(main)
    if store is None:
        return None
    return open_scope_sheets(store, main)
