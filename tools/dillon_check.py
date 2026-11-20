"""On a copy in memory: OCR the sheets whose words are drawn as outlines
(as shown, rotation kept), then Auto Scale, then AI Takeoff - what comes
out per sheet (read-only on the file): python tools/dillon_check.py <glob>
[--pages 4-12] [--no-run]"""
import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import acrobat, aitakeoff as ait, autoscale
    path = sorted(glob.glob(os.path.join(ROOT, a[0])))[0]
    doc = fitz.open(path)
    pages = None
    if "--pages" in a:
        x, y = a[a.index("--pages") + 1].split("-")
        pages = list(range(int(x) - 1, int(y)))
    t = time.time()
    need = [p for p in ait.ocr_needed(doc) if pages is None or p in pages]
    print("OCR needed:", [p + 1 for p in need])
    n = acrobat.make_searchable(doc, need)
    print(f"OCR'd {n} sheet(s) in {time.time() - t:.0f}s")
    import re
    for p in (pages or [])[:9]:
        tx = doc[p].get_text()
        hits = [tx[max(0, m.start() - 25):m.end() + 40].replace("\n", " | ")
                for m in re.finditer(r"SCALE", tx, re.I)][:4]
        print(f"  p{p + 1} words={len(doc[p].get_text('words'))} SCALE:",
              hits)
    rows = autoscale.detect(doc, pages=pages, use_ocr=True)
    for r in rows:
        print(f"  p{r['page'] + 1} {r['sheet']:8} {r['label'] or '-':10} "
              f"{r['status']:5} {r['source']:10} {r['note'][:80]}")
    autoscale.apply(doc, rows, confirmed=[r["page"] for r in rows
                                          if r["ppu"]])
    if "--no-run" in a:
        return
    prow = ait.plan_set(doc)
    if pages is not None:
        prow = [r for r in prow if r["page"] in pages]
    for r in prow:
        print(f"  p{r['page'] + 1} {r['number']:8} {r['kind']:8} "
              f"{r['engines']} {r['note'][:60]}")
    t = time.time()
    res = ait.run(doc, prow)
    print(f"ran in {time.time() - t:.0f}s")
    for q in res["quantities"]:
        print("  Q", q["engine"], "|", q["name"][:60], "|", q["qty"],
              q["unit"], "|", q["status"])
    cres = res.get("civil") or {}
    for p in cres.get("pipes", []):
        print("  PIPE", p["name"][:50], "existing" if p["existing"] else "new",
              [(rr["page"] + 1, round(rr["length"])) for rr in p["runs"]][:8])
    for st in cres.get("structures", []):
        print("  STRUCT", st["id"], st.get("kind"), "existing" if
              st["existing"] else "new", st.get("depth"),
              str(st.get("text") or st.get("label") or "")[:50])
    for pg in (pages or []):
        from app import civiltakeoff as ct
        labs = ct.pipe_labels(doc[pg])
        print(f"  labels p{pg + 1}:", [str(l.get('text', l))[:40]
                                      for l in labs][:10])
    print("  marks:", len(res.get("marks", [])), "assemblies:",
          list(res.get("assemblies", {}))[:10])
    for p, sh in sorted((res.get("sheets") or {}).items()):
        print("  sheet", p + 1, {k: (v if not isinstance(v, dict) else
                                     {kk: vv for kk, vv in list(v.items())[:6]})
                                 for k, v in sh.items()})
    for x in res.get("problems", [])[:15]:
        print("  problem:", x[:160])
    if "--png" in a:
        # the measured runs drawn on the sheets, for a look (kept in .run)
        for pg in sorted({rr["page"] for p in cres.get("pipes", [])
                          for rr in p["runs"]}):
            page = doc[pg]
            for p in cres["pipes"]:
                for rr in p["runs"]:
                    if rr["page"] != pg:
                        continue
                    raw = [fitz.Point(q) for q in rr["pts"]]
                    page.draw_polyline(raw, color=(1, 0, 0), width=6)
                    page.draw_polyline([q * page.rotation_matrix
                                        for q in raw], color=(0, 0, 1),
                                       width=6)
            pix = page.get_pixmap(dpi=40)
            out = os.path.join(ROOT, ".run", f"dillon_p{pg + 1}.png")
            pix.save(out)
            print("  png", out)


if __name__ == "__main__":
    main(sys.argv[1:])
