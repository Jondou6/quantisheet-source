import sys, os, glob
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root); sys.path.insert(0, os.path.join(root, "tests"))
out = open(sys.argv[2], "w", encoding="utf-8")
try:
    import fitz
    from app import proposal, assemblies
    assemblies.LIBRARY_PATH = os.path.join(root, "trial", "_lib.json")
    import test_planswift as t
    d = t._job()
    trial = os.path.join(root, "trial")
    for f in glob.glob(os.path.join(trial, "proposal_*")) + glob.glob(os.path.join(trial, "_w*.png")):
        os.remove(f)
    logo = os.path.join(trial, "_logo.png")
    comp = {"name": "Acme Builders, LLC", "address": "1930 University Pkwy\nAiken, SC 29801",
            "phone": "803-555-0100", "email": "bids@acme.test", "website": "acme.test",
            "license": "G-12345", "logo": logo, "signer": "Pat Morgan", "title": "Estimator"}
    for detail in ("trade", "assembly", "parts"):
        data = proposal.defaults(d)
        data.update(client="Aiken County Government", attention="Procurement",
                    client_address="1930 University Pkwy\nAiken, SC 29801",
                    project="Spay & Neuter Clinic", project_address="641 May Royal Dr, Aiken, SC",
                    tax=7, overhead=10, profit=10, detail=detail,
                    show_breakdown=(detail != "trade"),
                    inclusions="Daily cleanup\nDumpster")
        pdf = proposal.make_pdf(d, data, comp)
        pdf.save(os.path.join(trial, f"proposal_{detail}.pdf"))
        for i, pg in enumerate(pdf):
            pg.get_pixmap(dpi=80).save(os.path.join(trial, f"proposal_{detail}_{i+1}.png"))
        out.write(f"{detail}: {pdf.page_count} pages\n")
except Exception:
    import traceback; out.write(traceback.format_exc())
out.close()
