"""What a fillable form looks like to the program (read-only):
python tools/diag_form.py FILE.pdf [OUT.png]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    doc = fitz.open(a[0])
    print("is_form_pdf", doc.is_form_pdf, "xfa", bool(doc.xref_get_key(
        doc.pdf_catalog(), "AcroForm/XFA")[1] not in ("null", "")))
    for i, p in enumerate(doc):
        ws = list(p.widgets() or [])
        no_ap = sum(1 for w in ws
                    if doc.xref_get_key(w.xref, "AP")[0] == "null")
        print(f"page {i + 1}: {len(ws)} widgets, {no_ap} with no appearance;"
              f" first: {[(w.field_name, w.field_type_string) for w in ws[:3]]}")
    if len(a) > 1:
        doc[0].get_pixmap(dpi=60).save(a[1])
        print("wrote", a[1])


def fill_check(path):
    """Fill the first text field and tick the first check box the way the
    window does, on a copy in memory; print what comes back."""
    import fitz
    from app import annotate
    doc = fitz.open(path)
    for p in doc:
        for w in p.widgets():
            if w.field_type == fitz.PDF_WIDGET_TYPE_TEXT:
                annotate._set_field(p, {"name": w.field_name,
                                        "value": "Made Up Builders"})
                break
        for w in p.widgets():
            if w.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                print("check box on-state", w.on_state())
                annotate._set_field(p, {"name": w.field_name, "value": True})
                break
    back = fitz.open("pdf", doc.tobytes())
    for p in back:
        got = [(w.field_name, w.field_value) for w in p.widgets()
               if w.field_value not in ("", "Off", None, False)]
        print("page", p.number + 1, "filled:", got[:3])


def calc_check(path):
    """Fill a line of the change order the way the window does and print
    the totals the form works out, and how they show on the page."""
    import fitz
    from app import annotate
    doc = fitz.open(path)
    want = {"cost_labor_1": "100", "cost_material_1": "50",
            "overhead_pct": "10", "profit_pct": "5"}
    for p in doc:
        for w in list(p.widgets()):
            if w.field_name in want:
                print("fill", w.field_name, annotate._set_field(
                    p, {"name": w.field_name, "value": want[w.field_name]}))
    back = fitz.open("pdf", doc.tobytes())
    for p in back:
        for w in p.widgets():
            if w.field_name in ("cost_total_1", "subtotal", "overhead_amt",
                                "profit_amt", "total_change_amount",
                                "cost_labor_1"):
                print(f"  {w.field_name} = {w.field_value!r}")
        if p.number == 1 and len(sys.argv) > 3:
            doc[1].get_pixmap(dpi=100).save(sys.argv[3])   # the same doc
            print("wrote", sys.argv[3])


if __name__ == "__main__":
    if "--calc" in sys.argv:
        calc_check(sys.argv[1])
    elif "--fill" in sys.argv:
        fill_check(sys.argv[1])
    else:
        main(sys.argv[1:])
