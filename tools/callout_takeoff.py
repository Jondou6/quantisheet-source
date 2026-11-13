"""Read the work notes of a drawing set into quantities.

    python tools/callout_takeoff.py PDF-GLOB [--out NAME] [--pages A-B]
                                             [--blocks N] [--each]

--full also reads the summary table, the numbered notes and (with
--spec GLOB) the specification's rules. PDF-GLOB is relative to the project folder (wildcards allowed, so a path
with spaces can be given without them). Prints the totals; --each prints
every note; --blocks N prints the raw text blocks of page N (1-based)
for working out a misread note. --out writes NAME.xlsx and NAME.json
into .run/. The drawings stay on this computer.
"""
import glob
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main(argv):
    import fitz
    from app import callouts as co
    args = list(argv)

    def opt(name, default=None):
        if name in args:
            i = args.index(name)
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    out, pages, blocks = opt("--out"), opt("--pages"), opt("--blocks")
    spec = opt("--spec")
    full = "--full" in args
    args = [a for a in args if a != "--full"]
    each = "--each" in args
    args = [a for a in args if a != "--each"]
    hits = sorted(glob.glob(os.path.join(ROOT, args[0])))
    if not hits:
        print("no file matches", args[0])
        return 1
    tmp = tempfile.mkdtemp(prefix="qs-callouts-")
    path = shutil.copy(hits[0], os.path.join(tmp, "set.pdf"))
    with fitz.open(path) as doc:
        n = len(doc)
        if blocks:
            for lines, rect in co.page_blocks(doc[int(blocks) - 1]):
                if sum(map(len, lines)) <= co.MAX_CHARS:
                    print([round(v) for v in rect], " / ".join(lines))
            return 0
    rng = None
    if pages:
        a, _, b = pages.partition("-")
        rng = range(int(a) - 1, min(n, int(b or a)))
    if full:
        from app import callout_scope as cs
        text = ""
        if spec:
            sh = sorted(glob.glob(os.path.join(ROOT, spec)))
            if sh:
                with fitz.open(shutil.copy(sh[0], os.path.join(
                        tmp, "spec.pdf"))) as sd:
                    text = "\n".join(pg.get_text("text") for pg in sd)
        rows, facts = cs.read_set(path, text)
        print("from the specification:", facts or "nothing found")
        by = {}
        for r in rows:
            by[r.get("source", "note")] = by.get(r.get("source", "note"),
                                                  0) + 1
        print("rows by source:", by)
    else:
        rows = co.read_pdf(path, rng)
    print(f"{os.path.basename(hits[0])}: {n} pages, {len(rows)} quantities "
          f"from work notes")
    if each:
        for r in rows:
            print(f"  {r['sheet']:<7}{r['action']:<19}{r['qty']:>7} "
                  f"{r['unit']:<3} {r['what']}"
                  + (f"   [{'; '.join(r['check'])}]" if r["check"] else ""))
    for s in co.summary(rows):
        flag = "  *" if s["check"] else ""
        print(f"{s['action']:<19}{s['qty']:>8} {s['unit']:<3} {s['what']}"
              f"  ({', '.join(s['sheets'])})"
              + (f" [{s['repeats']} repeated on a sheet]" if s["repeats"]
                 else "") + flag)
    if out:
        base = os.path.join(ROOT, ".run", os.path.basename(out))
        co.export_xlsx(rows, base + ".xlsx")
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump({"file": os.path.basename(hits[0]), "rows": rows,
                       "totals": co.summary(rows)}, f, indent=1)
        print("written:", base + ".xlsx")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
