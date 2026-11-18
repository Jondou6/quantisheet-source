"""Can MuPDF's own form scripts run here (calculations, number formats)?
Read-only on a copy in memory: python tools/diag_form_js.py FILE.pdf"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import pymupdf
    mu = pymupdf.mupdf
    doc = pymupdf.open(a[0])
    print("pymupdf", pymupdf.VersionBind, "mupdf", pymupdf.VersionFitz)
    pdoc = pymupdf._as_pdf_document(doc)
    print("has pdf_enable_js", hasattr(mu, "pdf_enable_js"),
          "pdf_js_supported", hasattr(mu, "pdf_js_supported"))
    try:
        mu.pdf_enable_js(pdoc)
        print("js enabled:", mu.pdf_js_supported(pdoc))
    except Exception as e:                                # noqa: BLE001
        print("enable failed", e)
    want = {"cost_labor_1": "100", "cost_material_1": "50",
            "overhead_pct": "10", "cost_qty_1": "3"}
    for page in doc:
        for w in page.widgets():
            if w.field_name in want:
                annot = w._annot
                try:
                    pa = mu.pdf_annot_from_fz_annot(annot) \
                        if hasattr(mu, "pdf_annot_from_fz_annot") else annot
                except Exception:                         # noqa: BLE001
                    pa = annot
                try:
                    ok = mu.pdf_set_text_field_value(pa, want[w.field_name])
                    print("set", w.field_name, ok)
                except Exception as e:                    # noqa: BLE001
                    print("set failed", w.field_name, type(e).__name__, e)
    try:
        mu.pdf_calculate_form(pdoc)
        print("calculate_form ran")
    except Exception as e:                                # noqa: BLE001
        print("calculate_form", e)
    for page in doc:
        page = doc.reload_page(page)
    for page in doc:
        for w in page.widgets():
            if w.field_name in ("cost_total_1", "coltot_labor", "subtotal",
                                "overhead_amt", "total_change_amount",
                                "cost_labor_1", "cost_qty_1"):
                print(f"  {w.field_name} = {w.field_value!r}")


if __name__ == "__main__":
    main(sys.argv[1:])
