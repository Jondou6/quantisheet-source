"""v17: a revision changed priced takeoffs - show old -> new in bold on
the estimate row, Apply per row and Apply all."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                   # noqa: E402
import pytest                                                 # noqa: E402
from app import annotate, revdelta, revisions                 # noqa: E402
from test_gui import qapp                                     # noqa: E402,F401


def _job(monkeypatch):
    d = fitz.open()
    d.new_page(width=600, height=400)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=10, unit="ft"))
    ops = {}
    for g, v, y in (("Wall", 100.0, 50), ("Footing", 40.0, 120),
                    ("Note", 5.0, 200)):
        op = annotate.new_op("add_polyline", 0, pts=[[10, y], [200, y]],
                             measure={"type": "length", "value": v,
                                      "unit": "ft", "group": g})
        annotate.apply_op(d, op)
        ops[g] = op
    prices = {"Wall": 20.0, "Footing": 50.0}       # $/ft; Note is unpriced

    def snap(doc):
        s = {"when": "", "total": 0, "direct": 0, "items": {},
             "quantities": {}, "measurements": 0}
        for it in annotate.takeoff_items(doc):
            k = f"{it['group']}|{it['unit']}"
            s["quantities"][k] = s["quantities"].get(k, 0) + it["value"]
            if it["group"] in prices:
                q = s["quantities"][k]
                s["items"][it["group"]] = {"trade": "", "qty": q,
                                           "unit": it["unit"],
                                           "price": q * prices[it["group"]]}
        s["total"] = sum(i["price"] for i in s["items"].values())
        return s
    monkeypatch.setattr(revisions, "snapshot", snap)
    before = snap(d)
    # the revision: the wall run and the note got longer, both flagged
    for g, nv in (("Wall", 130.0), ("Note", 9.0)):
        a = next(a for a in d[0].annots()
                 if (a.info or {}).get("subject", "").endswith(f":{g}"))
        ref = annotate.ref(a)
        annotate.apply_op(d, annotate.new_op("delete_annot", 0, **ref))
        y = 50 if g == "Wall" else 200
        op = annotate.new_op("add_polyline", 0, pts=[[10, y], [260, y]],
                             measure={"type": "length", "value": nv,
                                      "unit": "ft", "group": g})
        annotate.apply_op(d, op)
        a = [a for a in d[0].annots()
             if (a.info or {}).get("subject", "").endswith(f":{g}")][-1]
        annotate.apply_op(d, annotate.new_op("set_annot", 0,
                                             **dict(annotate.ref(a),
                                                    status=annotate.REVISED)))
    revisions.record(d, "Addendum 2", ["A-101"], before=before)
    return d


def test_pending_rows_only_priced_and_bold_old_to_new(monkeypatch):
    d = _job(monkeypatch)
    rows = revdelta.pending(d)
    assert [r["name"] for r in rows] == ["Wall"]        # Note isn't priced
    r = rows[0]
    assert (r["qty_before"], r["qty_after"]) == (100.0, 130.0)
    assert r["before"] == pytest.approx(2000) and r["after"] == pytest.approx(2600)
    assert r["flagged"] == 1
    html = revdelta.cell_html(r)
    assert "<b>100 → 130 ft</b>" in html and "<b>$2,000.00 → $2,600.00</b>" in html


def test_apply_row_clears_flags_and_records(monkeypatch):
    d = _job(monkeypatch)
    assert revdelta.as_bid_total(d) == pytest.approx(4000)   # old values kept
    revdelta.apply(d, ["Wall"])
    assert revdelta.pending(d) == []
    assert revdelta.as_bid_total(d) == pytest.approx(4600)
    wall = [a for a in d[0].annots()
            if (a.info or {}).get("subject", "").endswith(":Wall")]
    assert all(annotate.status_of(d, a) != annotate.REVISED for a in wall)
    note = [a for a in d[0].annots()
            if (a.info or {}).get("subject", "").endswith(":Note")]
    assert annotate.status_of(d, note[0]) == annotate.REVISED   # untouched
    assert revisions.read(d)["revisions"][-1]["applied"][0]["name"] == "Wall"


def test_apply_all(monkeypatch):
    d = _job(monkeypatch)
    assert revdelta.apply_all(d) == 1
    assert revdelta.pending(d) == []


def test_dialog_rows_bold_and_buttons(qapp, monkeypatch):
    d = _job(monkeypatch)
    dlg = revdelta.RevisionDeltaDialog(None, d)
    assert dlg.table.rowCount() == 1
    assert dlg.table.item(0, 1).font().bold()
    assert "→" in dlg.table.item(0, 1).text()
    dlg.table.cellWidget(0, 4).click()          # Apply this row
    # the table is rebuilt after the click has finished (the button that
    # was clicked goes with it), so let the event loop run
    from PySide6.QtCore import QCoreApplication, QEvent
    for _ in range(5):
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert dlg.table.rowCount() == 0 and revdelta.pending(d) == []
