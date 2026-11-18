"""Why a made-up calculation didn't run (read-only, made-up form)."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))


def main():
    import fitz
    import test_active_content as t
    from app import annotate
    for js in (True,):
        p = os.path.join(tempfile.mkdtemp(), "f.pdf")
        t._form(p, with_js=js)
        d = fitz.open(p)
        cat = d.pdf_catalog()
        print("CO", d.xref_get_key(cat, "AcroForm/CO"))
        for w in d[0].widgets():
            print(w.field_name, repr(w.script_calc), d.xref_get_key(
                w.xref, "AA"))
        print("set", annotate._set_field(d[0], {"name": "A", "value": "5"}))
        print({w.field_name: w.field_value for w in d[0].widgets()})


if __name__ == "__main__":
    main()
