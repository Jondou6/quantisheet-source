"""P2-09 credit card receipt tracking beyond 9.2 (which is in
test_p2_banking): match, missing receipts, coding with approval, job cost."""
import pytest

from quantisheet_backoffice import (approvals, banking, cards, cents, jobcost,
                                    ledger)

MERCHANTS = ["EXAMPLE LUMBER #12", "EXAMPLE ELECTRIC SUPPLY", "EXAMPLE FUEL 5521",
             "EXAMPLE HOMECENTER #4410", "EXAMPLE FASTENERS OR-PORT", "EXAMPLE INDUSTRIAL 118",
             "EXAMPLE RENTALS", "EXAMPLE LIFTS 92", "EXAMPLE HARDWARE",
             "EXAMPLE CONCRETE", "EXAMPLE PLUMBING SUPPLY", "EXAMPLE PIPE 2231",
             "EXAMPLE OFFICE SUPPLY 33", "EXAMPLE GAS 0091", "EXAMPLE BUILDMART #1720", "EXAMPLE WIRE",
             "EXAMPLE COATINGS", "EXAMPLE SITE SUPPLY 41", "EXAMPLE STEEL",
             "EXAMPLE TIMBER", "EXAMPLE GLASS", "EXAMPLE PAINT", "EXAMPLE TOOLS NW",
             "EXAMPLE PRINT", "EXAMPLE SAFETY SUPPLY"]


@pytest.fixture
def full(office):
    office.set_company(accounting_mode="full")
    return office


def _statement(office, job):
    card = banking.add_account(office, "Company Card", "2300", kind="card",
                               last4="4242", statement_format="csv")
    cards.set_cardholder(office, card, "Pat Morgan", default_job_id=job)
    rows = ["Date,Description,Amount"]
    for i, m in enumerate(MERCHANTS):
        rows.append(f"10/{i + 1:02d}/2026,{m},-{100 + i}.{i:02d}")
    res = banking.import_statement(office, card, text="\n".join(rows) + "\n",
                                   fmt="csv")
    return card, res["ids"]


def _receipts(office, card):
    """21 receipts that match outright, 1 that only suggests (date 6 days
    off), and nothing for the last 3 charges."""
    for i, m in enumerate(MERCHANTS[:21]):
        name = m.split("#")[0].split()[0].title() + " " + \
            " ".join(m.split()[1:2]).title()
        cards.add_receipt(office, card, f"2026-10-{i + 1 + (i % 3):02d}",
                          name.strip(), f"{100 + i}.{i:02d}")
    cards.add_receipt(office, card, "2026-10-28", "Example Paint", "121.21")


def test_9_1_auto_suggested_missing(full, job):
    card, ids = _statement(full, job)
    _receipts(full, card)
    m = cards.match(full, card)
    assert (len(m["auto"]), len(m["suggested"]), len(m["missing"])) == \
        (21, 1, 3)
    (sug,) = m["suggested"]
    assert banking.line(full, sug["line_id"])["payee"] == "EXAMPLE PAINT"
    assert "6 days apart" in sug["reason"]
    miss = cards.missing(full, card)
    assert sorted(x["payee"] for x in miss) == sorted(MERCHANTS[22:])
    assert all(x["cardholder"] == "Pat Morgan" for x in miss)
    assert "receipt" in cards.reminder_text(full, "Pat Morgan", miss).lower()
    # matching again changes nothing; accepting the suggestion clears it
    assert len(cards.match(full, card)["auto"]) == 0
    cards.accept_match(full, sug["line_id"], sug["receipt_id"])
    assert len(cards.missing(full, card)) == 3


def test_9_coded_charge_routes_then_posts_and_hits_job_cost(full, job):
    card, ids = _statement(full, job)
    approvals.set_path(full, "card_charge", [approvals.step("jobrole:PM")])
    lid = ids[0]                                         # Example Lumber
    before = jobcost.by_code(full, job)["03-3000"]["actual"]
    cards.code(full, lid, "5020", job_id=job, cost_code="03-3000")
    with pytest.raises(banking.BankError, match="approval"):
        banking.accept(full, lid)
    full.act_as("pm@bo.test")
    cards.approve(full, lid)
    full.act_as("admin@bo.test")
    eid = banking.accept(full, lid)
    assert ledger.entry(full, eid)["lines"]
    after = jobcost.by_code(full, job)["03-3000"]
    assert after["actual"] - before == cents.parse_amount("100.00")
    assert any(s["type"] == "card_charge" for s in after["sources"])
