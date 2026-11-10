"""Price These: every takeoff line with a quantity but no price, in one
list to price (GUI user test r42 F03 - the estimate exported $0 and
nothing led the user to price it).

Each row takes a unit cost typed by the user; a suggestion from the
user's OWN price books (pricedb - nothing bundled, review rule) is shown
when one item's description holds every word of the line's name in the
same unit. A suggestion is never applied by itself: the user ticks it or
types a cost. Saved through estimate.set_price, so the Estimate panel,
the exports and the proposal all pick it up."""
import logging
import re
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

_UNITS = {"sq ft": "sf", "sqft": "sf", "sf": "sf", "ft2": "sf",
          "ft": "lf", "lf": "lf", "lin ft": "lf", "ea": "ea", "each": "ea",
          "cu yd": "cy", "cy": "cy", "yd3": "cy", "cu ft": "cf",
          "cf": "cf", "sq yd": "sy", "sy": "sy", "sq m": "m2", "m2": "m2",
          "m": "m", "lb": "lb", "ton": "ton", "sq": "sq"}


def unit_key(u):
    t = " ".join(str(u or "").lower().replace(".", "").split())
    return _UNITS.get(t, t)


def unpriced_lines(doc):
    """estimate.lines rows with a quantity and no unit cost yet."""
    from . import estimate
    out = []
    for g in estimate.lines(doc):
        q = g.get("adjusted", g.get("quantity")) or 0
        if q and not g.get("unit_cost"):
            out.append(g)
    return out


def _words(s):
    return [w for w in re.findall(r"[a-z0-9]+", str(s or "").lower())
            if len(w) > 1]


def item_cost(it):
    """A price-book item's cost per unit (material + labor + equipment +
    sub), or None when it has none."""
    tot = 0.0
    for k in ("material", "labor", "equipment", "sub"):
        try:
            tot += float(it.get(k) or 0)
        except (TypeError, ValueError):
            pass
    return round(tot, 4) if tot > 0 else None


def suggest(line, books):
    """(cost, "book: code desc") from the user's price books for one line,
    or None. books: [book dict as pricedb.load_book gives]."""
    words = _words(line.get("name"))
    if not words or line.get("name", "").strip().lower() in (
            "area", "length", "count", "volume"):
        return None                     # a generic name matches anything
    uk = unit_key(line.get("unit"))
    for b in books or []:
        for code, it in sorted((b.get("items") or {}).items()):
            desc = " ".join(_words(it.get("desc")))
            if unit_key(it.get("unit")) != uk:
                continue
            if all(re.search(r"\b" + re.escape(w), desc) for w in words):
                c = item_cost(it)
                if c:
                    return c, f"{b.get('name')}: {code} {it.get('desc')}"
    return None


def user_books():
    """The user's own price books (empty when there are none)."""
    try:
        from . import pricedb
        return [b for b in (pricedb.load_book(n)
                            for n in pricedb.book_names()) if b]
    except Exception:                                     # noqa: BLE001
        log.warning("price books not read", exc_info=True)
        return []


def apply(doc, prices):
    """prices: {(name, type, unit): unit_cost}. Returns lines priced."""
    from . import estimate
    n = 0
    for (name, mtype, unit), cost in prices.items():
        try:
            cost = float(cost)
        except (TypeError, ValueError):
            continue
        if cost <= 0:
            continue
        estimate.set_price(doc, name, mtype, unit, unit_cost=cost)
        n += 1
    return n


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView,
                                   QLabel, QTableWidget, QTableWidgetItem,
                                   QVBoxLayout)
except ImportError:                                   # pragma: no cover
    QDialog = None

if QDialog is not None:
    class PriceTheseDialog(QDialog):
        COLS = ["Item", "Quantity", "Unit", "Unit cost",
                "From my price books"]

        def __init__(self, doc, parent=None, books=None):
            super().__init__(parent)
            self.setWindowTitle("Price These")
            self.doc = doc
            self.lines = unpriced_lines(doc)
            books = user_books() if books is None else books
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel(
                f"{len(self.lines)} takeoff line(s) have a quantity but no "
                "price. Type a unit cost, or double-click a suggestion from "
                "your own price books to use it. Lines left blank stay "
                "unpriced."))
            t = self.table = QTableWidget(len(self.lines), len(self.COLS))
            t.setHorizontalHeaderLabels(self.COLS)
            self.sugg = {}
            for i, g in enumerate(self.lines):
                q = g.get("adjusted", g.get("quantity")) or 0
                vals = [g["name"], f"{_c2(q):,.2f}", g.get("unit") or "", "", ""]
                s = suggest(g, books)
                if s:
                    self.sugg[i] = s[0]
                    vals[4] = f"${_c2(s[0]):,.2f}  ({s[1][:60]})"
                for c, v in enumerate(vals):
                    it = QTableWidgetItem(v)
                    if c != 3:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    t.setItem(i, c, it)
            t.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.Stretch)
            t.cellDoubleClicked.connect(self._use_suggestion)
            lay.addWidget(t)
            bb = QDialogButtonBox(QDialogButtonBox.Save |
                                  QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.resize(820, 420)

        def _use_suggestion(self, row, col):
            if col == 4 and row in self.sugg:
                self.table.item(row, 3).setText(f"{_c2(self.sugg[row]):.2f}")

        def prices(self):
            out = {}
            for i, g in enumerate(self.lines):
                txt = (self.table.item(i, 3).text() or "").replace(
                    "$", "").replace(",", "").strip()
                if txt:
                    out[(g["name"], g["type"], g["unit"])] = txt
            return out

        def save(self):
            return apply(self.doc, self.prices())
