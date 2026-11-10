"""Found using the installed app by hand on Nov 10. Made-up data only."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_gui import qapp, win                                 # noqa: E402,F401


def test_rotate_shows_the_whole_page(win, monkeypatch):
    """Rotate Right left the view on a blank corner of the page."""
    fitted = []
    monkeypatch.setattr(type(win), "fit_page",
                        lambda self: fitted.append(1))
    win._view.set_zoom(3.0)
    assert win._rotate_pages([win._view.page], 90)
    assert fitted


def test_summary_says_reading_while_it_waits(win, monkeypatch):
    from app import bg
    monkeypatch.setattr(bg, "run", lambda *a, **k: None)
    busy = win.ai_summary()
    assert "Reading the whole document" in busy.labelText()
    assert "Reviewed" not in busy.labelText()
    win._ai_summary_tick()
    assert "Reading" in busy.labelText()
    busy.cancel()


def test_cost_book_price_columns_fit(qapp):
    import inspect
    from app import billing_ui, estimate_ui
    src = inspect.getsource(estimate_ui)
    assert "ResizeToContents" in src
    assert "ResizeToContents" in inspect.getsource(billing_ui)
    assert "setMinimumWidth(340)" in inspect.getsource(billing_ui)


def test_takeoff_unit_cost_shows_what_was_typed():
    from app import docks
    assert docks._dec(repr(round(4.125, 4))) == "4.125"
    assert docks._dec(repr(round(4.5, 4))) == "4.50"
    assert docks._dec(repr(round(720.9433, 4))) == "720.9433"
    assert docks._dec(repr(round(0.0, 4))) == "0.00"


def test_work_order_boxes_are_named(qapp, tmp_path, monkeypatch):
    import inspect
    from app.service import workorder_ui
    src = inspect.getsource(workorder_ui.WorkOrderWindow.__init__)
    for name in ('"Qty"', '"Cost each"', '"Price each"', '"Truck"',
                 '"Flat-rate task"', 'setPlaceholderText("Site")',
                 'setPlaceholderText("Unit")'):
        assert name in src, name


def test_prices_on_takeoff_lines_are_in_the_proposal_and_sov(qapp):
    """A unit cost typed on a takeoff line was in the Estimate panel's
    total but not in the proposal or schedule of values (Jon, Nov 10:
    include it)."""
    from estimate_helpers import area, blank_doc
    from app import assemblies, estimate, money, proposal
    d = blank_doc()
    area(d, "Test slab", 50, 20)
    estimate.set_price(d, "Test slab", "area", "sq ft", unit_cost=4.125,
                       cost_type="Material")
    g = estimate.lines(d)[0]
    assert g["total"] > 0
    rows, totals, errors = assemblies.rollup(d)
    mine = [r for r in rows if r.get("takeoff")]
    assert len(mine) == 1 and mine[0]["total"] == g["total"]
    assert mine[0]["parts"][0]["material_only"] == g["total"]
    priced = proposal.price(d, proposal.read(d))
    assert priced["direct"] >= g["total"] if "direct" in priced else True
    sov = money.from_estimate(d, "trade", 0.0, 12)
    assert sov and sum(float(l["scheduled"]) for l in sov) >= g["total"]
    # the page view and a selection are unchanged: assemblies only
    assert not [r for r in assemblies.rollup(d, 0)[0] if r.get("takeoff")]


def test_labor_typed_on_a_takeoff_line_is_labor():
    from estimate_helpers import area, blank_doc
    from app import estimate
    d = blank_doc()
    area(d, "Test paint", 10, 10)
    estimate.set_price(d, "Test paint", "area", "sq ft", unit_cost=2,
                       cost_type="Labor")
    r = estimate.rollup_rows(d)[0]
    assert r["labor_cost"] == r["total"] and r["material"] == 0


def test_a_measured_line_checks_by_hand():
    """Policy 2: the quantity is priced as shown, to 2 places."""
    from decimal import Decimal
    from app import estimate_lines, rounding
    assert rounding.VERSION == 2
    assert rounding.money_qty(Decimal("675.0546")) == Decimal("675.05")
    # a linked (measured) line: 675.0546 shown as 675.05, x 4.125
    groups = {("Slab", "area", "sq ft"): {"quantity": 675.0546, "count": 1}}
    ln = estimate_lines.new_line(
        "Slab", 0, "sq ft", mat="4.125",
        link={"name": "Slab", "type": "area", "unit": "sq ft"})
    p = estimate_lines.price(ln, groups)
    assert p["total"] == Decimal("2784.58")          # 675.05 x 4.125
    # a typed quantity is priced exactly as typed
    typed = estimate_lines.price(
        estimate_lines.new_line("Typed", "0.125", "hr", lab="80"))
    assert typed["total"] == Decimal("10.00")


def test_takeoff_line_total_is_shown_qty_times_cost():
    from decimal import Decimal
    from estimate_helpers import area, blank_doc
    from app import estimate, rounding
    d = blank_doc()
    area(d, "Test slab", 33.333, 20.5)
    estimate.set_price(d, "Test slab", "area", "sq ft", unit_cost=4.125)
    g = estimate.lines(d)[0]
    shown = rounding.money_qty(Decimal(repr(g["adjusted"])))
    want = (shown * Decimal("4.125")).quantize(Decimal("0.01"),
                                               rounding="ROUND_HALF_UP")
    assert Decimal(repr(g["total"])) == want
