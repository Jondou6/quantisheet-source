"""Fill the district's backflow form with a MADE-UP sample report, to
check the mapping on paper (Nov 5). Uses the mapping saved beside the
form (FORM.pdf.qsmap.json). Writes OUT and OUT's calibration copy; the
form itself is only read.

    python tools/district_sample.py FORM.pdf OUT.pdf"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    form, out = sys.argv[1].strip('"'), sys.argv[2].strip('"')
    from app.service import backflow, district_form as DF
    t = DF.set_form({"fields": {}, "nudge": [0, 0]}, form)
    r = backflow.empty_report()
    r.update(test_date="2026-11-05", acct_name="Sample Customer (made up)",
             acct_address="100 Sample St, Myrtle Beach, SC 29577",
             acct_no="000123", meter_no="M-0000", dev_name="SampleCo RPZ",
             dev_model="SM-909", dev_serial="SN-0000-1", dev_size="1 in",
             dev_application="Irrigation", dev_location="Front yard, left "
             "of the driveway", tester="A Sample Tester",
             c1_before_tight=True, c1_before_psi="5.4",
             c2_before_leaked=True, c2_before_psi="1.1",
             rv_before_psi="2.8", so1_before_tight=True,
             so2_before_tight=True, c2_repair_note="New check 2 rubber kit",
             c1_after_tight=True, c1_after_psi="5.4", c2_after_tight=True,
             c2_after_psi="1.9", rv_after_psi="2.9", so1_after_tight=True,
             so2_after_tight=True, signature="A Sample Tester",
             cert_no="BT-0000", cert_company="Sample Plumbing (made up)",
             cert_phone="843-555-0100", category="General",
             method="Differential", kit="Differential gauge",
             comments="Made-up sample to check the mapping.",
             so1_type="Gate", so2_type="Ball")
    res = DF.fill(r, out, t)
    cal = DF.calibration(os.path.splitext(out)[0] + " calibration.pdf", t)
    print(res, cal)


if __name__ == "__main__":
    main()
