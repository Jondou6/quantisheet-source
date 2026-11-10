"""Chief's estimator test, Nov 7: no overpayment guard ($99,999,999,999
was accepted and showed "still open -$99,999,999,759.02"), and the
standard door came off walls as 6.67 ft (383.99 SF). Made-up data only."""
import dataclasses
from decimal import Decimal

import os

import pytest

from quantisheet_claims import diary, rooms, settle
from .helpers import t1_claim


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _owed(c):
    b = diary.balance(c, settle.settle_claim(c))
    return b["owed_now"] + b["recoverable_later"]


def test_a_huge_typo_is_refused():
    c = t1_claim()
    with pytest.raises(diary.DiaryError, match="check the amount"):
        diary.add_payment(c, "2026-10-05", "99,999,999,999", "acv")
    with pytest.raises(diary.DiaryError, match="check the amount"):
        diary.add_payment(c, "2026-10-05", "99,999,999,999", "acv",
                          allow_over=True)


def test_more_than_owed_needs_a_yes():
    c = t1_claim()
    owed = _owed(c)
    over = f"{(owed + 100) / 100:.2f}"
    with pytest.raises(diary.OverpaymentError, match="more than"):
        diary.add_payment(c, "2026-10-05", over, "acv", owed_cents=owed)
    p = diary.add_payment(c, "2026-10-05", over, "acv", owed_cents=owed,
                          allow_over=True)
    c2 = dataclasses.replace(c, payments=p)
    b = diary.balance(c2, settle.settle_claim(c2))
    assert b["open_total"] == -100 and b["overpaid"] == 100
    assert diary.open_text(b) == ("Overpaid", 100)
    # exactly what is owed is fine without asking
    exact = f"{owed / 100:.2f}"
    diary.add_payment(c, "2026-10-05", exact, "acv", owed_cents=owed)
    # before there is an estimate, an advance is just recorded
    diary.add_payment(c, "2026-10-05", "5,000.00", "acv", owed_cents=0)


def test_open_text_never_negative():
    c = t1_claim()
    b = diary.balance(c, settle.settle_claim(c))
    lab, v = diary.open_text(b)
    assert lab == "Still open" and v >= 0


def test_window_asks_before_an_overpayment(qapp):
    from quantisheet_claims.ui.workspace import ClaimsWindow
    win = ClaimsWindow()
    win.open_practice()
    owed = _owed(win.claim)
    before = win.claim.paid_cents()
    big = f"{(owed - before + 5000) / 100:.2f}"
    asked = []
    assert win.add_payment("2026-10-05", big, "acv",
                           confirm=lambda t: asked.append(t) or False) \
        is False
    assert asked and "overpayment" in asked[0]
    assert win.claim.paid_cents() == before
    assert win.add_payment("2026-10-05", big, "acv",
                           confirm=lambda t: True)
    assert "overpaid" in win.balance_label.text()
    assert "-$" not in win.balance_label.text()
    win.close()


def test_standard_door_is_twenty_square_feet():
    r = rooms.new_room("Example room", "16", "8", "8", doors=1)
    ms = rooms.measure(r)
    assert ms.openings == Decimal("20.00")
    assert ms.walls == Decimal("364.00")             # 48 x 8 - 20
    r4 = rooms.new_room("Example hall", "20", "10", "8", doors=4)
    assert rooms.measure(r4).openings == Decimal("80.00")
    # other sizes are as typed
    odd = dataclasses.replace(r, openings=(dataclasses.replace(
        r.openings[0], height_ft=Decimal("7")),))
    assert rooms.measure(odd).openings == Decimal("21.00")
