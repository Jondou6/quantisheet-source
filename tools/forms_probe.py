"""Inventory the blank forms: fields, filled values, permissions."""
import os, sys, json
import fitz
root = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "PDF Attachments")
out = []
for dp, dn, fn in os.walk(root):
    for f in fn:
        if not f.lower().endswith(".pdf"):
            continue
        p = os.path.join(dp, f)
        try:
            d = fitz.open(p)
        except Exception as e:
            print("ERR", p, e); continue
        rec = {"file": os.path.relpath(p, root), "pages": d.page_count, "encrypted": d.is_encrypted,
               "perm": d.permissions, "needs_pass": d.needs_pass, "fields": 0, "filled": [], "names": []}
        for pg in d:
            for w in pg.widgets() or []:
                rec["fields"] += 1
                if len(rec["names"]) < 60:
                    rec["names"].append(w.field_name)
                v = w.field_value
                if v not in (None, "", "Off", False) and len(rec["filled"]) < 15:
                    rec["filled"].append((w.field_name, str(v)[:40]))
        out.append(rec)
for r in out:
    print(json.dumps(r)[:1500])
