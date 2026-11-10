"""Revision changed a priced takeoff: old -> new on the estimate (v17).

After a slip sheet (or any later change), each priced estimate row whose
quantity or price moved since the last revision was logged shows
"old → new" in bold until you Apply it. Apply (per row or all) accepts the
new number: it clears "Check - drawing revised" on that item's takeoffs
and records what was applied in the revision log. `as_bid_total` is the
bid with only applied changes in it. Uses revisions.snapshot/changes,
which already compare the estimate by assembly.
Hook: Estimate tab / Revision Log can open RevisionDeltaDialog(win, doc)
or call `cell_html(row)` to draw the bold old → new on its own rows."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import annotate, revisions
from .dmoney import c2 as _c2


def _last(doc):
    revs = revisions.read(doc)["revisions"]
    return revs[-1] if revs else None


def _flagged_by_group(doc):
    out = {}
    for it in annotate.takeoff_items(doc):
        try:
            page = doc[it["page"]]
            a = next(iter(annotate.find_annots(page, it["ref"]) or []), None)
        except Exception:
            a = None
        if a is not None and annotate.status_of(doc, a) == annotate.REVISED:
            out.setdefault(it["group"], []).append((it["page"], it["ref"]))
    return out


def pending(doc):
    """Priced estimate rows changed since the last revision and not yet
    applied: [{name, unit, qty_before, qty_after, before, after, change,
    flagged, refs}] biggest change first."""
    e = _last(doc)
    if not e or not e.get("before"):
        return []
    done = {a["name"] for a in e.get("applied", [])}
    ch = revisions.changes(e["before"], revisions.snapshot(doc))
    flagged = _flagged_by_group(doc)
    rows = []
    for r in ch["items"]:
        if r["name"] in done:
            continue
        if not (r["before"] or r["after"]):
            continue                                  # not priced
        refs = flagged.get(r["name"], [])
        rows.append(dict(r, flagged=len(refs), refs=refs))
    return rows


def _num(v):
    return f"{_c2(v):,.2f}".rstrip("0").rstrip(".")


def qty_text(r):
    return f"{_num(r['qty_before'])} → {_num(r['qty_after'])} {r['unit'] or ''}".strip()


def price_text(r):
    return f"${_c2(r['before']):,.2f} → ${_c2(r['after']):,.2f}"


def cell_html(r):
    return f"<b>{qty_text(r)}</b> &nbsp; <b>{price_text(r)}</b>"


def apply(doc, names):
    """Accept these rows. Returns how many were applied."""
    e_rows = {r["name"]: r for r in pending(doc)}
    picked = [e_rows[n] for n in names if n in e_rows]
    if not picked:
        return 0
    for r in picked:
        for page, ref in r["refs"]:
            annotate.apply_op(doc, annotate.new_op(
                "set_annot", page, **dict(ref, status="")))
    data = revisions.read(doc)
    e = data["revisions"][-1]
    e.setdefault("applied", []).extend(
        {"name": r["name"], "qty_before": r["qty_before"],
         "qty_after": r["qty_after"], "before": r["before"],
         "after": r["after"], "at": revisions._now(),
         "by": revisions._author()} for r in picked)
    revisions.write(doc, data)
    return len(picked)


def apply_all(doc):
    return apply(doc, [r["name"] for r in pending(doc)])


def as_bid_total(doc):
    """The bid total with unapplied revision changes left at old values."""
    now = float(revisions.snapshot(doc).get("total") or 0)
    return _c2(now - sum(r["after"] - r["before"] for r in pending(doc)))


class RevisionDeltaDialog(QDialog):
    HEAD = ["Item", "Quantity", "Price", "Change", ""]

    def __init__(self, parent, doc, on_change=None):
        super().__init__(parent)
        self.doc, self.on_change = doc, on_change
        self.setWindowTitle("Revision Changes to Apply")
        self.resize(760, 360)
        lay = QVBoxLayout(self)
        self.info = QLabel()
        lay.addWidget(self.info)
        self.table = QTableWidget(0, len(self.HEAD))
        self.table.setHorizontalHeaderLabels(self.HEAD)
        lay.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.all_btn = bb.addButton("Apply All", QDialogButtonBox.ActionRole)
        self.all_btn.clicked.connect(self.apply_all)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill()

    def fill(self):
        rows = pending(self.doc)
        self.table.setRowCount(len(rows))
        bold = QFont()
        bold.setBold(True)
        for i, r in enumerate(rows):
            vals = [r["name"], qty_text(r), price_text(r),
                    f"{'+' if r['change'] >= 0 else '-'}${_c2(abs(r['change'])):,.2f}"]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if j in (1, 2, 3):
                    it.setFont(bold)
                if r["flagged"]:
                    it.setToolTip(f"{r['flagged']} takeoff(s) flagged "
                                  "'Check - drawing revised'")
                self.table.setItem(i, j, it)
            b = QPushButton("Apply")
            # rebuilding the table deletes this button: do it after its
            # click has finished, not inside it (that crashed Qt)
            b.clicked.connect(lambda _c=False, n=r["name"]:
                              QTimer.singleShot(0, lambda: self.apply([n])))
            self.table.setCellWidget(i, 4, b)
        self.table.resizeColumnsToContents()
        self.all_btn.setEnabled(bool(rows))
        e = _last(self.doc)
        self.info.setText(
            f"{len(rows)} priced row(s) changed since "
            f"{e['label'] if e else 'the last revision'}. Bid as applied: "
            f"${_c2(as_bid_total(self.doc)):,.2f}" if rows else
            "No unapplied revision changes.")

    def apply(self, names):
        n = apply(self.doc, names)
        self.fill()
        if n and self.on_change:
            self.on_change()
        return n

    def apply_all(self):
        n = apply_all(self.doc)
        self.fill()
        if n and self.on_change:
            self.on_change()
        return n
