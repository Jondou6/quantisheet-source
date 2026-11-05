"""Cost Summary and Forecast pages in Project Center."""
import html
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import icons, theme
from ..reportname import report_file_name
from . import cashflow, cost, schema


def _m(v):
    return cost.money_fmt(v)


class CostSummaryPage(QWidget):
    def __init__(self, center):
        super().__init__()
        self.center = center
        self.store = center.store
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        head = QFrame()
        head.setObjectName("pcPageHead")
        h = QHBoxLayout(head)
        h.setContentsMargins(18, 14, 18, 12)
        ic = QLabel()
        ic.setPixmap(icons.icon("budget").pixmap(22, 22))
        h.addWidget(ic)
        t = QLabel("Cost Summary")
        t.setObjectName("pcH1")
        h.addWidget(t)
        h.addStretch()
        for label, icon, fn in (("Export for Sage 300…", "csv", self._sage),
                                ("Save as PDF…", "print", self._pdf),
                                ("Refresh", "sync", self.refresh)):
            b = QPushButton(label)
            b.setIcon(icons.icon(icon))
            b.clicked.connect(fn)
            h.addWidget(b)
        v.addWidget(head)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        self.body = QLabel()
        self.body.setTextFormat(Qt.RichText)
        self.body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.body.setContentsMargins(26, 18, 26, 26)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sc.setWidget(self.body)
        v.addWidget(sc, 1)

    def html(self):
        s = cost.summary(self.store)
        t = theme.tokens()
        th = (f"style='text-align:right;color:{t['muted']};font-weight:600;"
              f"padding:6px 12px;border-bottom:1px solid {t['border']}'")
        td = "style='text-align:right;padding:6px 12px'"
        tl = "style='text-align:left;padding:6px 12px'"

        def neg(v):
            return f"<span style='color:{t['danger']}'>{_m(v)}</span>" \
                if v < 0 else _m(v)
        c = s["contract"]
        out = [f"<h2 style='margin:0 0 4px 0'>{html.escape(self.store.name)}"
               "</h2>"]
        if not (self.store.list("budget") or self.store.list("contract")):
            out.append(f"<p style='color:{t['muted']}'>Add your budget "
                       "(Budget), the owner contract's schedule of values "
                       "(Prime Contract) and subcontracts (Commitments) - "
                       "this page then shows margin, buyout, billing and "
                       "the forecast.</p>")
        out.append("<h3>Owner contract</h3><table cellspacing=0>")
        out.append("<tr>" + "".join(f"<th {th}>{h}</th>" for h in (
            "Original", "Approved changes", "Revised", "Pending changes",
            "With pending")) + "</tr>")
        out.append("<tr>" + "".join(f"<td {td}>{_m(c[k])}</td>" for k in (
            "original", "approved", "revised", "pending", "with_pending"))
            + "</tr></table>")
        out.append("<h3>Cost by category</h3><table cellspacing=0>")
        cols = [("original", "Original budget"), ("approved",
                                                  "Approved changes"),
                ("revised", "Revised budget"), ("committed", "Committed"),
                ("actual", "Actual cost"), ("etc", "Cost to complete"),
                ("fac", "Forecast at completion")]
        out.append(f"<tr><th {th.replace('right', 'left')}></th>" +
                   "".join(f"<th {th}>{h}</th>" for _k, h in cols) + "</tr>")
        for cat, vals in s["categories"].items():
            if not any(vals.values()):
                continue
            out.append(f"<tr><td {tl}>{cat}</td>" + "".join(
                f"<td {td}>{_m(vals[k])}</td>" for k, _h in cols) + "</tr>")
        out.append(f"<tr style='font-weight:700'><td {tl}>Total</td>" +
                   "".join(f"<td {td}>{_m(s['totals'][k])}</td>"
                           for k, _h in cols) + "</tr></table>")
        out.append("<h3>Margin</h3><table cellspacing=0>")
        out.append(f"<tr><td {tl}>Gross margin (revised contract - revised "
                   f"budget)</td><td {td}><b>{neg(s['margin'])}</b></td>"
                   f"<td {td}>{s['margin_pct']:.1f}%</td></tr>")
        out.append(f"<tr><td {tl}>Projected margin (revised contract - "
                   f"forecast)</td><td {td}><b>"
                   f"{neg(s['projected_margin'])}</b></td><td {td}>"
                   f"{s['projected_margin_pct']:.1f}%</td></tr></table>")
        out.append("<h3>Billing</h3><table cellspacing=0>")
        for label, k in (("Billed to date", "billed"),
                         ("Retainage held", "retained"),
                         ("Payments received", "received"),
                         ("Owed to us (AR)", "ar")):
            out.append(f"<tr><td {tl}>{label}</td><td {td}>{_m(s[k])}"
                       "</td></tr>")
        out.append("</table>")

        def bar(label, pct):
            pct = max(0.0, min(pct, 100.0))
            return (f"<p style='margin:10px 0 2px 0'>{label}: "
                    f"<b>{pct:.0f}%</b></p><table cellspacing=0 "
                    f"width='420'><tr><td width='{max(pct, 0.5):.1f}%' "
                    f"style='background:{t['accent']};height:8px'></td>"
                    f"<td style='background:{t['raised']}'></td></tr>"
                    "</table>")
        out.append("<h3>Progress</h3>")
        out.append(bar("Cost spent of forecast", s["pct_complete"]))
        out.append(bar("Budget bought out (committed)", s["bought_out"]))
        return "".join(out)

    def refresh(self):
        self.body.setText(self.html())

    def _pdf(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF", os.path.join(
                self.store.folder,
                report_file_name("Cost Summary", self.store.name)),
            "PDF (*.pdf)")
        if not path:
            return
        cost_summary_pdf(self.store, path)
        self.center.toast(f"Saved {os.path.basename(path)}")

    def _sage(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export for Sage 300", os.path.join(
                self.store.folder, "Sage 300 budget and commitments.csv"),
            "CSV (*.csv)")
        if path:
            cost.sage_csv(self.store, path)
            self.center.toast("Exported. In Sage 300 CRE use Job Cost > "
                              "Import, and map the columns once.")


def cost_summary_pdf(store, path):
    from .report import _Doc
    s = cost.summary(store)
    d = _Doc("Cost Summary", store.name)
    c = s["contract"]
    d.heading("Owner contract")
    d.table(["Original", "Approved changes", "Revised", "Pending",
             "With pending"],
            [[_m(c[k]) for k in ("original", "approved", "revised",
                                 "pending", "with_pending")]])
    d.heading("Cost by category")
    keys = ["original", "approved", "revised", "committed", "actual", "etc",
            "fac"]
    rows = [[cat] + [_m(v[k]) for k in keys]
            for cat, v in s["categories"].items() if any(v.values())]
    rows.append(["Total"] + [_m(s["totals"][k]) for k in keys])
    d.table(["", "Original", "Approved", "Revised", "Committed", "Actual",
             "To complete", "Forecast"], rows,
            [1.4, 1, 1, 1, 1, 1, 1, 1])
    d.heading("Margin and billing")
    d.grid([("Gross margin", f"{_m(s['margin'])} ({s['margin_pct']:.1f}%)"),
            ("Projected margin", f"{_m(s['projected_margin'])} "
                                 f"({s['projected_margin_pct']:.1f}%)"),
            ("Billed to date", _m(s["billed"])),
            ("Retainage held", _m(s["retained"])),
            ("Payments received", _m(s["received"])),
            ("Owed to us", _m(s["ar"])),
            ("Cost spent of forecast", f"{s['pct_complete']:.0f}%"),
            ("Budget bought out", f"{s['bought_out']:.0f}%")])
    d.heading("By cost code")
    d.table(["Code", "Description", "Revised", "Committed", "Actual",
             "To complete", "Forecast", "Variance"],
            [[r["code"], r["description"], _m(r["revised"]),
              _m(r["committed"]), _m(r["actual"]), _m(r["etc"]),
              _m(r["fac"]), _m(r["variance"])]
             for r in s["rows"].values()],
            [1, 2.2, 1, 1, 1, 1, 1, 1])
    return d.finish(path)


class ForecastPage(QWidget):
    """Every cost code: budget, committed, spent, what's left, and your
    estimate to complete (type over it)."""
    COLS = ["Cost code", "Description", "Revised budget", "Committed",
            "Actual cost", "Cost to complete", "Risk",
            "Forecast at completion", "Variance", "% used"]

    def __init__(self, center):
        super().__init__()
        self.center = center
        self.store = center.store
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        head = QFrame()
        head.setObjectName("pcPageHead")
        h = QHBoxLayout(head)
        h.setContentsMargins(18, 14, 18, 12)
        ic = QLabel()
        ic.setPixmap(icons.icon("forecast").pixmap(22, 22))
        h.addWidget(ic)
        t = QLabel("Forecast")
        t.setObjectName("pcH1")
        h.addWidget(t)
        hint = QLabel("Type over Cost to complete or Risk to change the "
                      "forecast. Blank = what's left of budget or "
                      "commitment.")
        hint.setObjectName("muted")
        h.addWidget(hint)
        h.addStretch()
        v.addWidget(head)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setObjectName("pcList")
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._edited)
        v.addWidget(self.table, 1)
        self._loading = False
        self.codes = []

    def refresh(self):
        self._loading = True
        rows = list(cost.by_code(self.store).values())
        self.codes = [r["code"] for r in rows]
        self.table.setRowCount(len(rows) + 1)
        tot = {k: 0.0 for k in ("revised", "committed", "actual", "etc",
                                "risk", "fac_risk", "variance")}
        bad = QColor(theme.color("danger"))
        for i, r in enumerate(rows):
            vals = [r["code"], r["description"], _m(r["revised"]),
                    _m(r["committed"]), _m(r["actual"]), f"{r['etc']:,.0f}",
                    f"{r['risk']:,.0f}" if r["risk"] else "",
                    _m(r["fac_risk"]), _m(r["variance"]),
                    f"{r['used_pct']:.0f}%"]
            for k in tot:
                tot[k] += r[k]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c >= 2:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c not in (5, 6):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                else:
                    it.setToolTip("Type your estimate")
                if c == 8 and r["variance"] < 0:
                    it.setForeground(bad)
                if c == 3 and r["committed"] > r["revised"] + 0.5:
                    it.setForeground(bad)
                    it.setToolTip("Committed more than the budget")
                self.table.setItem(i, c, it)
        n = len(rows)
        totals = ["Total", "", _m(tot["revised"]), _m(tot["committed"]),
                  _m(tot["actual"]), _m(tot["etc"]), _m(tot["risk"]),
                  _m(tot["fac_risk"]), _m(tot["variance"]), ""]
        for c, val in enumerate(totals):
            it = QTableWidgetItem(val)
            f = it.font()
            f.setBold(True)
            it.setFont(f)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            if c >= 2:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(n, c, it)
        self.table.resizeColumnsToContents()
        self._loading = False

    def _edited(self, it):
        if self._loading or it.row() >= len(self.codes):
            return
        code = self.codes[it.row()]
        field = {5: "etc", 6: "risk"}.get(it.column())
        if not field:
            return
        txt = it.text().replace("$", "").replace(",", "").strip()
        try:
            val = float(txt) if txt else None
        except ValueError:
            self.refresh()
            return
        recs = [b for b in self.store.list("budget")
                if cost.code_key(b.get("cost_code")) == code]
        if recs:
            b = recs[0]
            b[field] = val
            for other in recs[1:]:              # one line holds the estimate
                if other.get(field) not in (None, ""):
                    other[field] = None
                    self.store.save_record("budget", other)
        else:
            b = {"cost_code": code, "description": "(forecast only)",
                 "original": 0, field: val}
        self.store.save_record("budget", b)
        self.refresh()


class _Curve(QWidget):
    """Cumulative planned / actual+forecast / billed, by month."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self.setMinimumHeight(240)

    def paintEvent(self, e):
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QPainter, QPen
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(t["surface"]))
        rows = self.rows
        L, T, R, B = 80, 30, self.width() - 20, self.height() - 30
        p.setPen(QPen(QColor(t["border"]), 1))
        if not rows:
            p.setPen(QColor(t["muted"]))
            p.drawText(QRectF(L, T, R - L, B - T), Qt.AlignCenter,
                       "Add a budget and a schedule (with cost codes on the "
                       "activities) to see the cost curve.")
            return
        top = max([1.0] + [max(r["cum_planned"], r["cum_forecast"],
                               r["cum_billed"]) for r in rows])
        n = len(rows)

        def X(i):
            return L + (R - L) * (i + 1) / n

        def Y(v):
            return B - (B - T) * v / top
        for k in range(5):
            v = top * k / 4
            p.setPen(QPen(QColor(t["border"]), 1))
            p.drawLine(QPointF(L, Y(v)), QPointF(R, Y(v)))
            p.setPen(QColor(t["muted"]))
            p.drawText(QRectF(0, Y(v) - 8, L - 6, 16),
                       Qt.AlignRight | Qt.AlignVCenter,
                       f"${v / 1000:,.0f}k" if top >= 10000 else f"${v:,.0f}")
        step = max(1, n // 12)
        for i, r in enumerate(rows):
            if i % step == 0:
                p.drawText(QRectF(X(i) - 30, B + 4, 60, 16), Qt.AlignCenter,
                           cashflow.label(r["month"]))
        from datetime import date
        now = f"{date.today():%Y-%m}"
        series = [("cum_planned", "Planned", QColor("#2563eb"), Qt.SolidLine),
                  ("cum_forecast", "Actual + forecast", QColor("#d32f2f"),
                   Qt.SolidLine),
                  ("cum_billed", "Billed", QColor("#2e7d32"), Qt.DashLine)]
        for key, _name, col, style in series:
            p.setPen(QPen(col, 2.2, style))
            prev = QPointF(L, B)
            for i, r in enumerate(rows):
                pt = QPointF(X(i), Y(r[key]))
                p.drawLine(prev, pt)
                prev = pt
        for i, r in enumerate(rows):
            if r["month"] == now:
                p.setPen(QPen(QColor("#f08c00"), 1.2, Qt.DashLine))
                p.drawLine(QPointF(X(i), T), QPointF(X(i), B))
        x = L
        for _key, name, col, style in series:
            p.setPen(QPen(col, 3, style))
            p.drawLine(QPointF(x, 14), QPointF(x + 22, 14))
            p.setPen(QColor(t["text"]))
            p.drawText(QPointF(x + 28, 18), name)
            x += 170


class CashFlowPage(QWidget):
    """Cost-loaded schedule: the S-curve and cash in and out by month."""

    def __init__(self, center):
        super().__init__()
        self.center = center
        self.store = center.store
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        head = QFrame()
        head.setObjectName("pcPageHead")
        h = QHBoxLayout(head)
        h.setContentsMargins(18, 14, 18, 12)
        ic = QLabel()
        ic.setPixmap(icons.icon("trend").pixmap(22, 22))
        h.addWidget(ic)
        t = QLabel("Cash Flow")
        t.setObjectName("pcH1")
        h.addWidget(t)
        self.note = QLabel()
        self.note.setObjectName("muted")
        h.addWidget(self.note)
        h.addStretch()
        for label, icon, fn in (("Excel…", "excel", self._xlsx),
                                ("Save as PDF…", "print", self._pdf),
                                ("Refresh", "sync", self.refresh)):
            b = QPushButton(label)
            b.setIcon(icons.icon(icon))
            b.clicked.connect(lambda _=False, f=fn: f())
            h.addWidget(b)
        v.addWidget(head)
        self.curve = _Curve()
        v.addWidget(self.curve)
        self.table = QTableWidget(0, len(cashflow.COLS))
        self.table.setObjectName("pcList")
        self.table.setHorizontalHeaderLabels([l for _k, l in cashflow.COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        v.addWidget(self.table, 1)

    def refresh(self):
        heads, rows, data = cashflow.table(self.store)
        self.data = data
        self.curve.rows = data["rows"]
        self.curve.update()
        self.table.setRowCount(len(rows))
        bad = QColor(theme.color("danger"))
        for i, (vals, r) in enumerate(zip(rows, data["rows"])):
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if cashflow.COLS[c][0] == "net_cash" and r["net_cash"] < 0:
                    it.setForeground(bad)
                self.table.setItem(i, c, it)
        self.note.setText(
            "  ·  budget spread over the schedule by cost code" +
            (f"  ·  {_m(data['unscheduled'])} not on the schedule yet"
             if data["unscheduled"] else ""))

    def _save(self, title, ext, filt, path=None):
        if path:
            return path
        path, _ = QFileDialog.getSaveFileName(
            self, title,
            report_file_name("Cash Flow", self.store.name, ext=f".{ext}"),
            filt)
        return path

    def _pdf(self, path=None):
        path = self._save("Save PDF", "pdf", "PDF (*.pdf)", path)
        if path:
            cashflow.pdf(self.store, path)
            self.center.toast(f"Saved {os.path.basename(path)}")
        return path

    def _xlsx(self, path=None):
        path = self._save("Export to Excel", "xlsx", "Excel (*.xlsx)", path)
        if path:
            cashflow.xlsx(self.store, path)
            self.center.toast(f"Saved {os.path.basename(path)}")
        return path
