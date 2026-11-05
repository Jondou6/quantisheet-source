"""Small builders shared by tests (exact numbers from the brief, section 4)."""
from quantisheet_claims import model as m


def line(rc_cents, dep_bp=0, structure="S1", category="DRYWALL", lid=None,
         group="", qty_q4=10_000, unit="LS", recoverable=True, **kw):
    unit_cents = rc_cents if qty_q4 == 10_000 else kw.pop("unit_cents")
    return m.Line(id=lid or m.new_id(), item_code=kw.pop("item_code", "ITEM"),
                  description=kw.pop("description", "item"), category=category,
                  qty_q4=qty_q4, unit=unit, unit_cost=m.UnitCost(labor=unit_cents),
                  structure_id=structure, group_id=group, dep_bp=dep_bp,
                  dep_recoverable=recoverable, **kw)


def t1_claim(**kw):
    """T1: $10,000 RC (dep 50%) + $240 tax line (dep 50%), O&P 10+10
    additive aggregate, $1,000 flat deductible."""
    base = dict(
        id="t1", claim_number="T1", claim_type="residential",
        # the brief's T1 numbers put O&P on the tax line; since NW-15 that
        # takes the explicit setting (the default leaves tax out)
        op=m.OpPolicy(overhead_bp=1000, profit_bp=1000, op_on_tax=True),
        deductible=m.DeductibleSpec(kind="flat", amount_cents=100_000),
        structures=(m.Structure(id="S1", name="Dwelling", kind="dwelling",
                                limit_cents=30_000_000),),
        lines=(line(1_000_000, 5000, lid="L1"),
               line(24_000, 5000, category="GENERAL", lid="TAX",
                    item_code="TAX", description="Sales tax (input)")),
    )
    base.update(kw)
    return m.Claim(**base)


def c8_claim(**kw):
    """C8: RC $200,000, O&P 10+10 compound, dep 25% on RC, value $600,000,
    limit $400,000, 90%, deductible $2,500."""
    base = dict(
        id="c8", claim_number="C-2026-0008", claim_type="commercial",
        insured="Main Street Retail LLC", carrier="Example Mutual",
        loss_address="100 Main St", loss_date="2026-09-14", peril="wind",
        op=m.OpPolicy(overhead_bp=1000, profit_bp=1000, compound=True),
        deductible=m.DeductibleSpec(kind="flat", amount_cents=250_000),
        deductible_mode="per_building",
        structures=(m.Structure(id="B1", name="Building 1", kind="building",
                                value_cents=60_000_000, limit_cents=40_000_000,
                                coins_bp=9000),),
        lines=(line(20_000_000, 2500, structure="B1", lid="C8L1",
                    item_code="ROOF-TPO", description="Roof membrane, replace"),),
    )
    base.update(kw)
    return m.Claim(**base)
