"""Print where a spec book states the Project Analysis terms (read-only):
python tools/diag_spec_terms.py <glob> [max_hits]"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TERMS_MORE = {
    "caldays": r"calendar\s+days",
    "occurrence": r"each\s+occurrence|per\s+occurrence",
    "paybondpct": r"payment\s+bond[^.]{0,200}?(?:%|percent)",
    "consists": r"work\s+(?:to\s+be\s+done\s+)?consists\s+of",
}
TERMS = {
    "substantial": r"substantial(?:ly)?\s+complet",
    "final": r"final(?:ly)?\s+complet",
    "biddate": r"bids?\s+(?:will|shall)\s+be\s+received|received\s+until|"
               r"bid\s+opening|opened\s+and\s+(?:publicly\s+)?read",
    "prebid": r"pre[\s-]*(?:bid|proposal)",
    "retain": r"retain|retainage",
    "ld": r"liquidated\s+damages",
    "summary": r"summary\s+of\s+(?:the\s+)?work|work\s+covered|project\s+"
               r"description|description\s+of\s+(?:the\s+)?work",
    "paybond": r"payment\s+bond|labor\s+and\s+material",
    "insurance": r"general\s+liability",
    "questions": r"questions|requests?\s+for\s+information|inquir",
    "alternates": r"alternate",
    "unitprice": r"unit\s+price",
    "addendum": r"addendum\s+(?:no|number|#)",
}


def main(a):
    import fitz
    path = sorted(glob.glob(os.path.join(ROOT, a[0])))[0]
    n = int(a[1]) if len(a) > 1 and a[1].isdigit() else 3
    if "--more" in a:
        TERMS.clear()
        TERMS.update(TERMS_MORE)
    sys.stdout.reconfigure(errors="replace")
    doc = fitz.open(path)
    texts = [re.sub(r"\s+", " ", doc[p].get_text() or "")
             for p in range(doc.page_count)]
    for key, rx in TERMS.items():
        print(f"== {key}")
        hits = 0
        for p, t in enumerate(texts):
            for m in re.finditer(rx, t, re.I):
                print(f"  p{p + 1}: ...{t[max(0, m.start() - 60):m.end() + 160]}...")
                hits += 1
                break
            if hits >= n:
                break


if __name__ == "__main__":
    main(sys.argv[1:])
