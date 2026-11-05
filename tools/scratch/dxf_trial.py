"""Try DXF import, Trace Length and DXF export on real sample drawings.
python tools/dxf_trial.py  -> .run/dxf_trial/ (PDFs, PNGs, report.json)"""
import json
import os
import sys
import time
import traceback
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz  # noqa: E402
import ezdxf  # noqa: E402
from app import annotate, dxf, snap, vector  # noqa: E402

OUT = os.path.join(ROOT, ".run", "dxf_trial")
SRC = os.path.join(OUT, "src")
os.makedirs(SRC, exist_ok=True)
REPOS = [("gdsestimating/dxf-parser", "samples/data"),
         ("jscad/sample-files", "dxf"),
         ("mozman/ezdxf", "examples_dxf")]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pdfstudio"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def fetch(limit=14):
    files = [f for f in os.listdir(SRC) if f.lower().endswith(".dxf")]
    if files:
        return files
    for repo, folder in REPOS:
        try:
            items = json.loads(get(f"https://api.github.com/repos/{repo}/"
                                   f"contents/{folder}"))
        except Exception as e:
            print("list failed", repo, e)
            continue
        for it in items:
            n = it["name"]
            if n.lower().endswith(".dxf") and 20_000 < it["size"] < 6_000_000:
                try:
                    data = get(it["download_url"])
                    name = repo.split("/")[0] + "__" + n
                    with open(os.path.join(SRC, name), "wb") as f:
                        f.write(data)
                    files.append(name)
                    print("got", name, len(data))
                except Exception as e:
                    print("download failed", n, e)
            if len(files) >= limit:
                return files
    return files


def trial(name):
    rep = {"file": name}
    src = os.path.join(SRC, name)
    pdf = os.path.join(OUT, name[:-4] + ".pdf")
    t = time.time()
    info = dxf.to_pdf(src, pdf)
    rep.update(info, import_s=round(time.time() - t, 2))
    d = fitz.open(pdf)
    page = d[0]
    sc = annotate.read_scales(d)[0]
    rep["ppu"] = sc["ppu"]
    rep["text_chars"] = len(page.get_text())
    t = time.time()
    idx = snap.SnapIndex(snap.page_segments(page))
    rep["segments"] = len(idx.segs)
    # trace from the 8 longest segments' midpoints
    longest = sorted(range(len(idx.segs)), key=lambda i: -vector.length(
        list(idx.segs[i])))[:8]
    traces = []
    for i in longest:
        a, b = idx.segs[i]
        pts, closed = vector.trace(idx, ((a[0] + b[0]) / 2,
                                         (a[1] + b[1]) / 2))
        if not pts:
            continue
        L = vector.length(pts) / sc["ppu"]
        traces.append({"seg_len": round(vector.length([a, b]) / sc["ppu"],
                                        2), "run_len": round(L, 2),
                       "points": len(pts), "closed": closed})
        ppts = [annotate.to_page(page, fitz.Point(p)) for p in pts]
        annotate.apply_op(d, annotate.new_op(
            "add_polyline", 0, pts=[[q.x, q.y] for q in ppts],
            color=[1, 0, 0], width=4,
            measure={"type": "length", "value": round(L, 3),
                     "unit": sc["unit"], "group": "Trace"}))
    rep["trace_s"] = round(time.time() - t, 2)
    rep["traces"] = traces
    pix = page.get_pixmap(dpi=40)
    pix.save(os.path.join(OUT, name[:-4] + ".png"))
    back = os.path.join(OUT, name[:-4] + "_back.dxf")
    e = dxf.from_page(d, 0, back)
    x = ezdxf.readfile(back)
    rep["export_entities"] = e["entities"]
    rep["export_units"] = e["units"]
    rep["export_layers"] = sorted(l.dxf.name for l in x.layers)[:12]
    d.save(os.path.join(OUT, name[:-4] + "_traced.pdf"))
    return rep


def main():
    files = fetch()
    print(len(files), "sample files")
    report = []
    for n in sorted(files):
        try:
            report.append(trial(n))
        except Exception as e:
            report.append({"file": n, "error": f"{type(e).__name__}: {e}",
                           "trace": traceback.format_exc()[-800:]})
        print(json.dumps(report[-1])[:600], flush=True)
    with open(os.path.join(OUT, "report.json"), "w") as f:
        json.dump(report, f, indent=1)


main()
