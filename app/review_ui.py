"""Review CHECK Items (AI Takeoff > Review): one flagged item at a time,
on its sheet, least sure first - Accept it as found, type the right
quantity and Accept, or Delete it, optionally saying why (not there,
wrong shape, misidentified); Report Missed logs something the AI didn't
find. Decisions go straight into the takeoff and the estimate workbook
(app/review.py); the reasons stay on this PC."""
import fitz
from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator, QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout)

from . import review


class ReviewDialog(QDialog):
    def __init__(self, win, res, who="reviewer", on_change=None):
        super().__init__(win)
        self.win = win
        self.res = res
        self.who = who
        self.on_change = on_change
        self.setWindowTitle("Review CHECK Items")
        self.setModal(False)
        self.resize(620, 330)
        v = QVBoxLayout(self)
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        v.addWidget(self.progress)
        self.title = QLabel()
        self.title.setWordWrap(True)
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setBold(True)
        self.title.setFont(f)
        v.addWidget(self.title)
        self.where = QLabel()
        v.addWidget(self.where)
        self.why = QLabel()
        self.why.setWordWrap(True)
        self.why.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.why, 1)
        qrow = QHBoxLayout()
        qrow.addWidget(QLabel("Quantity:"))
        self.qty = QLineEdit()
        self.qty.setValidator(QDoubleValidator(0.0, 1e9, 2, self))
        self.qty.setMaximumWidth(140)
        self.qty.returnPressed.connect(self.accept_one)
        qrow.addWidget(self.qty)
        self.unit = QLabel()
        qrow.addWidget(self.unit)
        qrow.addStretch()
        qrow.addWidget(QLabel("Why:"))
        self.reason = QComboBox()
        self.reason.addItem("—", None)
        for r in review.REASONS[1:]:
            self.reason.addItem(r.capitalize(), r)
        self.reason.setToolTip("Optional: why you delete or fix it. Kept on "
                               "this PC to improve the takeoff.")
        qrow.addWidget(self.reason)
        v.addLayout(qrow)
        row = QHBoxLayout()
        self.acc_btn = QPushButton("Accept (A)")
        self.acc_btn.setObjectName("primary")
        self.acc_btn.setToolTip("Take it off at the quantity shown - type a "
                                "different number first to fix it")
        self.acc_btn.clicked.connect(self.accept_one)
        self.del_btn = QPushButton("Delete (D)")
        self.del_btn.setToolTip("Leave it out of the takeoff and workbook")
        self.del_btn.clicked.connect(self.delete_one)
        self.skip_btn = QPushButton("Skip (S)")
        self.skip_btn.clicked.connect(self.skip)
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self.back)
        self.miss_btn = QPushButton("Report Missed…")
        self.miss_btn.setToolTip("Log something the AI didn't find (measure "
                                 "it with the normal tools)")
        self.miss_btn.clicked.connect(lambda _c=False: self.report_missed())
        for b in (self.acc_btn, self.del_btn, self.skip_btn, self.back_btn,
                  self.miss_btn):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        for key, fn in (("A", self.accept_one), ("D", self.delete_one),
                        ("S", self.skip)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda fn=fn: None if self.qty.hasFocus()
                                 else fn())
        self.items = review.queue(res, order="least_sure")
        self.i = 0
        self.show_current()

    # ---- state ---------------------------------------------------------
    def current(self):
        return self.items[self.i] if 0 <= self.i < len(self.items) else None

    def show_current(self):
        c = review.counts(self.res)
        self.progress.setText(
            f"{c['left']} to check · {c['accepted']} accepted · "
            f"{c['fixed']} fixed · {c['deleted']} deleted")
        it = self.current()
        on = it is not None
        for w in (self.acc_btn, self.del_btn, self.skip_btn, self.qty):
            w.setEnabled(on)
        self.back_btn.setEnabled(self.i > 0)
        if not on:
            self.title.setText("Every CHECK item is decided." if not c["left"]
                               else "End of the list - the skipped items "
                               "are still to check (Back, or open Review "
                               "again).")
            self.where.setText("")
            self.why.setText("Make the Estimate Workbook again: it carries "
                             "your decisions.")
            self.qty.clear()
            self.unit.clear()
            return None
        q = it.get("qty")
        qs = f"{q:,.2f}".rstrip("0").rstrip(".") \
            if isinstance(q, (int, float)) else "no quantity"
        self.title.setText(f"{it.get('name') or 'Item'} - {qs} "
                           f"{it.get('unit') or ''}".strip())
        self.where.setText(f"Sheet {it.get('sheet') or '—'}"
                           + f" · score {review.score(it)}/100"
                           + (" · scanned sheet" if it.get("source") ==
                              "scan" else "")
                           + (" · already counted elsewhere - Delete "
                              "unless it is really a second one"
                              if review.is_repeat(it) else ""))
        self.why.setText(it.get("why") or "")
        self.qty.setText("" if not isinstance(q, (int, float))
                         else f"{q:g}")
        self.unit.setText(it.get("unit") or "")
        self.reason.setCurrentIndex(0)
        self.acc_btn.setText("Accept (A)")
        self._show_on_sheet(it)
        return it

    def _show_on_sheet(self, it):
        v = getattr(self.win, "_view", None)
        p = it.get("page")
        if v is None or not isinstance(p, int) or not \
                0 <= p < v.doc.page_count:
            return
        if v.page != p:
            v.go_to(p)
        r = it.get("rect")
        if r and hasattr(self.win, "zoom_to_rect"):
            rect = fitz.Rect(r)
            pad = max(rect.width, rect.height) * 0.8 + 40
            self.win.zoom_to_rect(rect + (-pad, -pad, pad, pad))

    def _changed(self):
        if self.on_change:
            self.on_change()

    # ---- decisions -----------------------------------------------------
    def typed(self):
        t = self.qty.text().replace(",", "").strip()
        try:
            return float(t) if t else None
        except ValueError:
            return None

    def accept_one(self):
        it = self.current()
        if it is None:
            return None
        q = self.typed()
        if q is None:
            self.why.setText((it.get("why") or "") +
                             "\n\nType the quantity to accept it.")
            self.qty.setFocus()
            return None
        line = review.accept(self.res, it,
                             None if q == it.get("qty") else q, self.who,
                             reason=self.reason.currentData())
        self.items.pop(self.i)
        self._changed()
        self.show_current()
        return line

    def delete_one(self):
        it = self.current()
        if it is None:
            return False
        review.delete(self.res, it, self.who,
                      reason=self.reason.currentData())
        self.items.pop(self.i)
        self._changed()
        self.show_current()
        return True

    def report_missed(self, name=None):
        """Log an item the AI didn't find (asks for its name)."""
        if name is None:
            name, ok = QInputDialog.getText(
                self, "Report Missed", "What did the AI miss? (e.g. "
                "WOMEN'S SHOWER 109)")
            if not ok:
                return None
        name = (name or "").strip()
        if not name:
            return None
        it = self.current() or {}
        rec = review.missed(self.res, name, sheet=it.get("sheet"),
                            page=it.get("page"), who=self.who)
        self._changed()
        self.show_current()
        return rec

    def skip(self):
        if self.i < len(self.items):
            self.i += 1
        self.show_current()

    def back(self):
        if self.i > 0:
            self.i -= 1
        self.show_current()


KIND_NAMES = {"area": "Area", "length": "Length", "count": "Count",
              "scale": "Scale", "schedule row": "Schedule row",
              "item": "Item"}


class ReviewQueueDialog(QDialog):
    """One review queue (AI Takeoff v3): every AI measurement not accepted
    yet and every CHECK item - doors, windows, rooms, areas, schedule rows,
    a doubtful scale - least sure first (review_queue.py). Accept, Deny or
    Undo; an item in review is in no total until it is accepted. A scale
    shows the printed words it was read from."""

    def __init__(self, win, res, who="reviewer", on_change=None):
        super().__init__(win)
        from . import review_queue
        self.win = win
        self.res = res
        self.who = who
        self.on_change = on_change
        v = getattr(win, "_view", None)
        self.doc = v.doc if v is not None else None
        self.session = review_queue.Session(self.doc, res, win=win, who=who)
        self.setWindowTitle("Review Queue")
        self.setModal(False)
        self.resize(660, 470)
        lay = QVBoxLayout(self)
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        lay.addWidget(self.progress)
        self.title = QLabel()
        self.title.setWordWrap(True)
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setBold(True)
        self.title.setFont(f)
        lay.addWidget(self.title)
        self.where = QLabel()
        self.where.setWordWrap(True)
        lay.addWidget(self.where)
        self.crop = QLabel()
        self.crop.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.crop.setToolTip("The words on the sheet the scale was read "
                             "from")
        lay.addWidget(self.crop)
        self.why = QLabel()
        self.why.setWordWrap(True)
        self.why.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.why, 1)
        qrow = QHBoxLayout()
        self.qty_lbl = QLabel("Quantity:")
        qrow.addWidget(self.qty_lbl)
        self.qty = QLineEdit()
        self.qty.setValidator(QDoubleValidator(0.0, 1e9, 2, self))
        self.qty.setMaximumWidth(140)
        self.qty.returnPressed.connect(self.accept_one)
        qrow.addWidget(self.qty)
        self.unit = QLabel()
        qrow.addWidget(self.unit)
        qrow.addStretch()
        qrow.addWidget(QLabel("Why:"))
        self.reason = QComboBox()
        self.reason.addItem("—", None)
        for r in review.REASONS[1:]:
            self.reason.addItem(r.capitalize(), r)
        qrow.addWidget(self.reason)
        lay.addLayout(qrow)
        row = QHBoxLayout()
        self.acc_btn = QPushButton("Accept (A)")
        self.acc_btn.setObjectName("primary")
        self.acc_btn.clicked.connect(self.accept_one)
        self.del_btn = QPushButton("Deny (D)")
        self.del_btn.setToolTip("Delete it from the drawing / leave it out "
                                "of the takeoff")
        self.del_btn.clicked.connect(self.deny_one)
        self.skip_btn = QPushButton("Skip (S)")
        self.skip_btn.clicked.connect(self.skip)
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self.back)
        self.undo_btn = QPushButton("Undo (U)")
        self.undo_btn.setToolTip("Put the last Accept or Deny back")
        self.undo_btn.clicked.connect(self.undo_one)
        self.miss_btn = QPushButton("Report Missed…")
        self.miss_btn.setToolTip("Log something the AI didn't find (measure "
                                 "it with the normal tools)")
        self.miss_btn.clicked.connect(lambda _c=False: self.report_missed())
        for b in (self.acc_btn, self.del_btn, self.skip_btn, self.back_btn,
                  self.undo_btn, self.miss_btn):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        for key, fn in (("A", self.accept_one), ("D", self.deny_one),
                        ("S", self.skip), ("U", self.undo_one)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda fn=fn: None if self.qty.hasFocus()
                                 else fn())
        self.decided = {"accepted": 0, "denied": 0}
        self.refresh()

    # ---- state ---------------------------------------------------------
    def refresh(self, keep=0):
        from . import review_queue
        self.entries = review_queue.build(self.doc, self.res)
        self.i = min(keep, len(self.entries))
        self.show_current()

    def current(self):
        return self.entries[self.i] if 0 <= self.i < len(self.entries) \
            else None

    def show_current(self):
        n = len(self.entries)
        pend = sum(1 for e in self.entries if e["pending"])
        self.progress.setText(
            f"{n} to check ({pend} not in the totals until accepted) · "
            f"{self.decided['accepted']} accepted · "
            f"{self.decided['denied']} denied")
        e = self.current()
        on = e is not None
        for w in (self.acc_btn, self.del_btn, self.skip_btn):
            w.setEnabled(on)
        self.back_btn.setEnabled(self.i > 0)
        self.undo_btn.setEnabled(bool(self.session.done))
        self.crop.clear()
        self.crop.setVisible(False)
        if not on:
            self.title.setText("Nothing left to check." if not n else
                               "End of the list - the skipped ones are "
                               "still to check (Back).")
            self.where.setText("")
            self.why.setText("")
            self.qty.clear()
            self.unit.clear()
            return None
        q = e.get("qty")
        qs = f"{q:,.2f}".rstrip("0").rstrip(".") \
            if isinstance(q, (int, float)) else ""
        self.title.setText(f"{KIND_NAMES.get(e['kind'], 'Item')}: "
                           f"{e['name']}" + (f" - {qs} {e['unit']}"
                                             if qs else ""))
        p = e.get("page")
        sheet = e.get("sheet") or (p + 1 if isinstance(p, int) else "—")
        self.where.setText(
            f"Sheet {sheet}"
            + f" · score {e['score']}/100"
            + (" · not in the totals until accepted" if e["pending"]
               else " · in the totals (AI, not checked)")
            + (" · scanned sheet" if e.get("source") == "scan" else "")
            + (" · already counted elsewhere - Deny unless it is really "
               "a second one" if e["repeat"] else ""))
        self.why.setText(str(e.get("why") or ""))
        typed = e["mark"] is None and e["kind"] != "scale"
        for w in (self.qty_lbl, self.qty, self.unit):
            w.setVisible(typed)
        self.qty.setText(f"{q:g}" if typed and isinstance(q, (int, float))
                         else "")
        self.unit.setText(e.get("unit") or "")
        self.reason.setCurrentIndex(0)
        self.acc_btn.setText("Confirm Scale (A)" if e["kind"] == "scale"
                             else "Accept (A)")
        if e["kind"] == "scale":
            self._show_crop(e)
        self._show_on_sheet(e)
        return e

    def _show_crop(self, e):
        from PySide6.QtGui import QPixmap
        from . import scale_evidence
        r = e.get("rect")
        if self.doc is None or not r or not isinstance(e.get("page"), int):
            self.crop.setText("(no printed scale found to show)")
            self.crop.setVisible(True)
            return
        try:
            png = scale_evidence.crop_png(self.doc[e["page"]], fitz.Rect(r))
            pm = QPixmap()
            pm.loadFromData(png, "PNG")
            if pm.width() > 600:
                pm = pm.scaledToWidth(600, Qt.SmoothTransformation)
            self.crop.setPixmap(pm)
        except Exception:                                # noqa: BLE001
            self.crop.setText("(couldn't show the printed scale)")
        self.crop.setVisible(True)

    def _show_on_sheet(self, e):
        v = getattr(self.win, "_view", None)
        p = e.get("page")
        if v is None or not isinstance(p, int) or not \
                0 <= p < v.doc.page_count:
            return
        if v.page != p:
            v.go_to(p)
        r = e.get("rect")
        if r is None and e.get("mark") is not None:
            from . import annotate
            a = annotate.find_annots(v.pg, e["mark"]["ref"])
            if a:
                r = annotate.from_page(v.pg, fitz.Rect(a[0].rect))
            del a
        if r and hasattr(self.win, "zoom_to_rect"):
            rect = fitz.Rect(r)
            pad = max(rect.width, rect.height) * 0.8 + 40
            self.win.zoom_to_rect(rect + (-pad, -pad, pad, pad))

    def _changed(self):
        if self.on_change:
            self.on_change()

    def _typed(self):
        t = self.qty.text().replace(",", "").strip()
        try:
            return float(t) if t else None
        except ValueError:
            return None

    # ---- decisions -----------------------------------------------------
    def accept_one(self):
        e = self.current()
        if e is None:
            return None
        q = None
        if e["mark"] is None and e["kind"] != "scale":
            q = self._typed()
            if q is None:
                self.why.setText(str(e.get("why") or "") +
                                 "\n\nType the quantity to accept it.")
                self.qty.setFocus()
                return None
        out = self.session.accept(e, qty=q,
                                  reason=self.reason.currentData())
        if out is None:
            return None
        self.decided["accepted"] += 1
        self._changed()
        self._drop(e)
        return out

    def deny_one(self):
        e = self.current()
        if e is None:
            return False
        self.session.deny(e, reason=self.reason.currentData())
        self.decided["denied"] += 1
        self._changed()
        self._drop(e)
        return True

    def _drop(self, e):
        """The decided entry leaves the list (a full rebuild reads every
        page of the drawing: slow on a big set; Undo rebuilds)."""
        if e in self.entries:
            self.entries.remove(e)
        self.i = min(self.i, len(self.entries))
        self.show_current()

    def undo_one(self):
        if not self.session.done:
            return False
        act = self.session.done[-1]["action"]
        if not self.session.undo():
            self.why.setText("Can't undo here - the drawing was changed "
                             "since. Use Edit > Undo.")
            return False
        self.decided["accepted" if act == "accept" else "denied"] -= 1
        self._changed()
        self.refresh(self.i)
        return True

    def report_missed(self, name=None):
        """Log an item the AI didn't find (asks for its name)."""
        asked = name is None
        if name is None:
            name, ok = QInputDialog.getText(
                self, "Report Missed", "What did the AI miss? (e.g. "
                "WOMEN'S SHOWER 109)")
            if not ok:
                return None
        name = (name or "").strip()
        if not name:
            return None
        e = self.current() or {}
        rec = review.missed(self.res, name, sheet=e.get("sheet"),
                            page=e.get("page"), who=self.who)
        self._changed()
        self.show_current()
        if asked:                 # typed in the dialog: offer the search
            self.offer_search(name)
        return rec

    def offer_search(self, name, ask=True):
        """Nov 1: after Report Missed, box one missed copy on the drawing
        and the program looks for more like it that aren't counted (they
        come back as counts in review). Returns True when the drawing is
        waiting for the box."""
        v = getattr(self.win, "_view", None)
        if v is None or not hasattr(v, "ask_missed_example"):
            return False
        if ask:
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(
                    self, "Report Missed",
                    f"Is '{name}' a symbol? Box one copy on the drawing "
                    "and the program will look for more like it that "
                    "aren't counted yet.\n\nThey come back as counts in "
                    "review - nothing is added to the totals until you "
                    "accept them.") != QMessageBox.Yes:
                return False
        v.ask_missed_example(name)
        return True

    def skip(self):
        if self.i < len(self.entries):
            self.i += 1
        self.show_current()

    def back(self):
        if self.i > 0:
            self.i -= 1
        self.show_current()
