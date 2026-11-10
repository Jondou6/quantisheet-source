"""Made-up sample files for the Phase 6 review (Nov 6): the load inputs
for the outside designer (PDF + CSV) and a changeout proposal, in OUT (default
.run/phase6_samples). Uses a throwaway data folder, never the real one.

    python tools/phase6_sample.py [OUT]"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(out):
    os.makedirs(out, exist_ok=True)
    home = tempfile.mkdtemp(prefix="qs_p6_")      # never the real data
    for k in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA"):
        os.environ[k] = os.path.join(home, k.lower())
        os.makedirs(os.environ[k], exist_ok=True)
    from app import settings
    settings.DIR = os.path.join(home, "settings")
    settings._cache = {}
    from app.estimating import service
    from app.service import agreements, changeout, gbb, loadcalc, pricebook
    rec = service.blank()
    prop = service.add_property(rec, "Sample house", "1 Test Lane",
                                customer="Sample Customer")
    old = service.add_equipment(rec, prop, "Split AC", make="OldCo",
                                model="OLD-30", serial="SN-OLD",
                                installed="2009-06-01")
    def it(t, v, u, label):
        return {"type": t, "value": v, "unit": u, "label": label}
    jobs = loadcalc.blank()
    rid = loadcalc.add(jobs, "Sample Customer", "Sample house",
                       loadcalc.merge_rooms(
                           [loadcalc.room("Office Suite", ceiling_ft=9)],
                           loadcalc.from_takeoff([
                               it("area", 700, "SF", "Office Suite"),
                               it("area", 250, "SF", "Break Room"),
                               it("area", 60, "SF", "Office Suite window S"),
                               it("length", 94, "LF",
                                  "Office Suite exterior wall")])),
                       property_id=prop)
    job = loadcalc.get(jobs, rid)
    loadcalc.export_pdf(job, os.path.join(out, "load_inputs_sample.pdf"))
    loadcalc.export_csv(job, os.path.join(out, "load_inputs_sample.csv"))
    import fitz
    rep = os.path.join(out, "designer_report_sample.pdf")
    with fitz.open() as d:
        d.new_page().insert_text((72, 72), "Made-up designer report")
        d.save(rep)
    loadcalc.attach_report(jobs, rid, rep, "Sample Designer", "2026-11-10",
                           "61000", "88000", "7.5-ton RTU, gas heat")
    b = pricebook.blank()
    t = [pricebook.add_task(b, n, p, "", tier=tier) for n, p, tier in (
        ("2.5-ton 15 SEER2 system changeout", "8400", "Good"),
        ("2.5-ton 17 SEER2 system changeout", "10200", "Better"),
        ("3-ton variable-speed system changeout", "13900", "Best"))]
    t.append(pricebook.add_task(b, "New thermostat", "350", "", tier="Best"))
    eq = {"Good": dict(brand="Goodman", model="SAMPLE-G25", tons="2.5",
                       efficiency="15 SEER2", warranty="10 yr parts"),
          "Better": dict(brand="Daikin", model="SAMPLE-D25", tons="2.5",
                         efficiency="17 SEER2", warranty="12 yr parts"),
          "Best": dict(brand="Ruud", model="SAMPLE-R30", tons="3.5",
                       efficiency="20 SEER2", warranty="10 yr parts")}
    agr = agreements.blank()
    agreements.add(agr, "Sample Customer", "300", 2, "2027-06-01",
                   site="Sample house")
    quotes = gbb.blank()
    qid = changeout.create(quotes, b, "Sample Customer", "Sample house",
                           {"Good": [t[0]], "Better": [t[1]],
                            "Best": [t[2], t[3]]}, eq, records=rec,
                           equipment_id=old, load_job=job, agreements=agr,
                           permit_fee="450", duct_changes="New supply "
                           "plenum and transition", duct_price="1200",
                           notes="Sample proposal - made-up data.")
    changeout.proposal_pdf(gbb.get(quotes, qid),
                           os.path.join(out, "changeout_sample.pdf"))
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, ".run", "phase6_samples"))
