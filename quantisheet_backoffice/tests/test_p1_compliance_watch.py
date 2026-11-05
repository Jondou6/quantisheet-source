"""P1 'compliance / insurance tracking': an expired certificate holds the
payment (existing rule); one running out within 30 days is a warning on
the invoice and on the watch list (made-up vendors; test clock
2026-10-22)."""
from quantisheet_backoffice import ap

from .helpers import ap_invoice


def test_warning_thirty_days_before_expiry(office, job):
    ap.seed_vendors(office, job)
    v = ap.vendor_by_name(office, "Example Framing")
    ap.update_vendor(office, v["id"], insurance_expires="2026-11-10")
    iid = ap_invoice(office, "Example Framing", "AF-1", "2026-10-20",
                     "500.00")
    w = ap.warnings(office, iid)
    assert any("insurance expires 2026-11-10 (in 19 days)" in x for x in w)
    watch = ap.compliance_watch(office)
    assert any(x["vendor"] == "Example Framing" and x["days"] == 19
               for x in watch)


def test_expired_is_a_hold_not_a_warning(office, job):
    ap.seed_vendors(office, job)
    v = ap.vendor_by_name(office, "Example Framing")
    ap.update_vendor(office, v["id"], insurance_expires="2026-10-01")
    iid = ap_invoice(office, "Example Framing", "AF-2", "2026-10-20",
                     "500.00")
    assert not any("insurance expires" in x for x in ap.warnings(office, iid))
    assert any("insurance expired" in h["reason"]
               for h in ap.check_compliance(office, iid))
    assert ap.compliance_watch(office)[0]["status"] == "HOLD - expired"


def test_far_off_dates_say_nothing(office, job):
    ap.seed_vendors(office, job)
    v = ap.vendor_by_name(office, "Example Framing")
    ap.update_vendor(office, v["id"], insurance_expires="2027-06-30")
    iid = ap_invoice(office, "Example Framing", "AF-3", "2026-10-20",
                     "500.00")
    assert not any("expires" in x for x in ap.warnings(office, iid))
