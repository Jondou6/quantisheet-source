"""PM review NW-15: no O&P on the sales-tax line unless asked (made-up
residential claim like RES-TEST-002: $5,822 of work + $210 tax, O&P
10+10)."""
import dataclasses

from quantisheet_claims import model as m
from quantisheet_claims import store
from quantisheet_claims.settle import settle_claim
from .helpers import line


def _claim(**op):
    return m.Claim(
        id="r2", claim_number="RES-TEST-002", claim_type="residential",
        op=m.OpPolicy(overhead_bp=1000, profit_bp=1000, **op),
        deductible=m.DeductibleSpec(kind="flat", amount_cents=0),
        structures=(m.Structure(id="S1", name="Dwelling", kind="dwelling",
                                limit_cents=30_000_000),),
        lines=(line(582_200, lid="W"),
               line(21_000, category="GENERAL", lid="TAX",
                    description="Sales tax on materials")))


def test_tax_left_out_of_op_by_default():
    s = settle_claim(_claim())
    assert s.op == 116_440                 # 20% of 5,822.00 only
    assert s.rcv == 582_200 + 21_000 + 116_440 == 719_640


def test_setting_puts_op_on_tax():
    s = settle_claim(_claim(op_on_tax=True))
    assert s.op == 120_640                 # 20% of 6,032.00


def test_tax_found_by_category_code_or_description():
    def mk(**kw):
        base = dict(id="x", item_code="ITEM", description="item",
                    category="DRYWALL", qty_q4=10_000, unit="EA",
                    unit_cost=m.UnitCost())
        base.update(kw)
        return m.Line(**base)
    assert m.is_tax_line(mk(category="TAX"))
    assert m.is_tax_line(mk(item_code="tax"))
    assert m.is_tax_line(mk(description="Tax (input)"))
    assert not m.is_tax_line(mk(description="Taxi fare"))
    assert not m.is_tax_line(mk(description="Remove and replace"))


def test_old_claim_file_reads_with_tax_left_out(tmp_path):
    c = _claim()
    p = store.save(c, folder=str(tmp_path))
    import json
    raw = json.load(open(p, encoding="utf-8"))
    raw["claim"]["op"].pop("op_on_tax", None)       # a pre-NW-15 file
    json.dump(raw, open(p, "w", encoding="utf-8"))
    back, _r = store.load(p)
    assert back.op.op_on_tax is False
    assert dataclasses.replace(back.op, op_on_tax=False) == back.op
