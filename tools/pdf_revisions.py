"""List the incremental-save revisions of a PDF (read-only).

    python tools/pdf_revisions.py PDF [restore N]

Prints each revision's end offset and, compared with the one before it,
which pages gained or lost markups. "restore N" first copies the PDF next
to itself as "<name> - before restore <time>.pdf", then cuts the file back
to revision N (the bytes of the file as it was when that revision was
saved; later incremental saves are dropped).
"""
import datetime
import os
import re
import shutil
import sys

import fitz


def revisions(data):
    ends = []
    for m in re.finditer(rb"%%EOF[ \t]*(\r\n|\r|\n)?", data):
        ends.append(m.end())
    return ends


def annots_by_page(blob):
    doc = fitz.open(stream=blob, filetype="pdf")
    out = {}
    try:
        for i, pg in enumerate(doc):
            items = []
            for a in pg.annots() or []:
                items.append((a.type[1], (a.info.get("subject") or
                                          a.info.get("content") or "")[:40]))
            if items:
                out[i + 1] = items
    finally:
        doc.close()
    return out


def main(argv):
    argv = [a.strip('"') for a in argv]     # the runner keeps the quotes
    path = argv[0]
    data = open(path, "rb").read()
    st = os.stat(path)
    print(f"{path}\n  size {len(data):,} bytes, modified "
          f"{datetime.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}")
    ends = revisions(data)
    print(f"  {len(ends)} revision(s)")
    prev = None
    for n, end in enumerate(ends, 1):
        try:
            cur = annots_by_page(data[:end])
        except Exception as e:                       # noqa: BLE001
            print(f"  rev {n}: ends at {end:,} - can't open ({e})")
            continue
        total = sum(len(v) for v in cur.values())
        line = f"  rev {n}: ends at {end:,}  markups {total}"
        if prev is not None:
            changed = []
            for p in sorted(set(cur) | set(prev)):
                a, b = prev.get(p, []), cur.get(p, [])
                if a != b:
                    added = [x for x in b if x not in a]
                    gone = [x for x in a if x not in b]
                    changed.append(f"p{p}: +{added} -{gone}")
            line += ("  changes: " + "; ".join(changed)) if changed else \
                "  (no markup changes)"
        print(line, flush=True)
        prev = cur
    if len(argv) >= 3 and argv[1] == "restore":
        n = int(argv[2])
        if not 1 <= n <= len(ends):
            print("no such revision")
            return 2
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        base, ext = os.path.splitext(path)
        backup = f"{base} - before restore {stamp}{ext}"
        shutil.copy2(path, backup)
        print(f"  backup: {backup}")
        with open(path, "r+b") as f:
            f.truncate(ends[n - 1])
        print(f"  restored to revision {n}: {ends[n - 1]:,} bytes")
        chk = annots_by_page(open(path, "rb").read())
        print(f"  check: opens, {sum(len(v) for v in chk.values())} markups")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
