"""How QuantiSheet rounds, in one place (Venice #15/#16, Nov 4).

Quantities add up in exact decimals: each markup's value is taken as
shown (0.1 is 0.1, not 0.1000000000000000055), so the total never depends
on the order the markups were drawn. Waste % and the multiplier are
applied in decimals and the adjusted quantity is kept to 4 decimal
places. Money is exact cents: each line is quantity x unit cost rounded
half-up to the cent (an added line rounds each of Mat / Lab / Eqp / Sub
the same way and adds them), and the estimate total is the sum of the
rounded lines, so the lines on a printout always add up to its total.
Nothing is rounded up to whole units unless you ask for it (Buy Qty).

The policy is the same for every job; jobs show it on the Estimate panel
and in the Estimate CSV so a reviewer can see how the numbers were made.
"""
from decimal import ROUND_HALF_UP, Decimal

QTY_PLACES = Decimal("0.0001")
VERSION = 1

SHORT = ("Rounding: quantities exact, adjusted qty to 4 places; each line "
         "to the cent (half up); total = sum of the lines.")

POLICY = (
    "Quantities: each markup's value as shown, added exactly (no "
    "floating-point drift).\n"
    "Adjusted quantity: quantity x (1 + waste %) x multiplier, kept to 4 "
    "decimal places.\n"
    "Line totals: adjusted quantity x unit cost, rounded half up to the "
    "cent. Added lines round Material, Labor, Equipment and Subcontract "
    "to the cent each, then add them.\n"
    "Estimate total: the sum of the rounded lines, so a printout always "
    "adds up.\n"
    "Whole units: nothing is rounded up to boxes, sticks or sheets unless "
    "you use Buy Qty.")


def qty(v):
    """An adjusted quantity kept to 4 places (half up)."""
    return Decimal(v).quantize(QTY_PLACES, rounding=ROUND_HALF_UP)


def csv_rows():
    """Rows for the bottom of an estimate export."""
    return [["Rounding (policy v%d)" % VERSION]] + \
        [[line] for line in POLICY.split("\n")]
