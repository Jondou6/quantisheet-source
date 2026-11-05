"""PM review NW-10: billed to date and retainage held follow the newest
certified pay app, before and after an AR invoice; a pending PCO shows its
amount (made-up job from the test snapshot)."""
from quantisheet_backoffice import billing, cents, jobs


def test_billed_and_retainage_from_certified_apps(office, job3):
    billing.set_contract(office, job3)
    cert = billing.latest_certified(office, job3)
    assert cert is not None
    want4 = cents.to_cents(cert["summary"]["4"])
    want5 = cents.to_cents(cert["summary"]["5"])
    assert want5 > 0
    s = billing.contract_summary(office, job3)          # no invoice yet
    assert s["billed_to_date"] == want4 and s["retainage_held"] == want5
    billing.approve(office, billing.invoice_from_payapp(
        office, job3, cert["number"]))
    s = billing.contract_summary(office, job3)
    assert s["billed_to_date"] == want4 and s["retainage_held"] == want5


def test_pending_change_shows_its_amount():
    assert billing.change_amount({"stage": "pco", "amount": "9800.00",
                                  "approved_amount": "0.00"}) == 980_000
    assert billing.change_amount({"stage": "co", "amount": "1.00",
                                  "approved_amount": "500.00"}) == 50_000
