"""Run AI Takeoff on the same plans with two versions of the code - this
folder and an earlier backup - and write the two results side by side.

    python tools/ai_takeoff_compare.py PLANS.pdf OLD_ROOT [--pages 1-12]
    python tools/ai_takeoff_compare.py start PLANS.pdf OLD_ROOT   (background)
    python tools/ai_takeoff_compare.py status

The plan PDF is copied to a temp folder first and opened read-only from
there (tests run on copies only). Each version runs in its own process
with its own code on the path. Output: .run/ai_takeoff_compare.txt
(summary of each, time taken) and .run/ai_takeoff_compare.json."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".run", "ai_takeoff_compare")

CHILD = r'''
import json, sys, time, io, contextlib
root, pdf, pages = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
import fitz
from app import aitakeoff as ait
doc = fitz.open(pdf)
t = time.time()
rows = ait.plan_set(doc, lambda i, n: True)
if pages:
    a, b = (int(x) for x in pages.split("-"))
    for r in rows:
        if not a <= r["page"] + 1 <= b:
            r["engines"] = []
res = ait.run(doc, rows, lambda k, n, text: True)
took = time.time() - t
tot = ait.totals(res) if hasattr(ait, "totals") else {}
def js(v):
    if isinstance(v, dict):
        return {(" | ".join(map(str, k)) if isinstance(k, tuple) else str(k)):
                js(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [js(x) for x in v]
    return v if isinstance(v, (int, float, str, type(None))) else str(v)
print("@@JSON@@" + json.dumps({
    "seconds": round(took, 1), "marks": len(res["marks"]),
    "sheets_taken": sum(1 for r in rows if r["engines"]),
    "totals": js(tot), "problems": js(res.get("problems", []))[:20],
    "summary": ait.summary_text(rows, res)}))
'''


def run(root, pdf, pages):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    py = sys.executable
    p = subprocess.run([py, "-c", CHILD, root, pdf, pages or ""], cwd=root,
                       env=env, capture_output=True, text=True,
                       errors="replace", timeout=3600)
    for line in p.stdout.splitlines():
        if line.startswith("@@JSON@@"):
            return json.loads(line[8:])
    return {"error": (p.stderr or p.stdout)[-3000:]}


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    argv = [a.strip('"') for a in argv]     # the runner keeps quotes
    src, old = argv[0], argv[1]
    pages = argv[argv.index("--pages") + 1] if "--pages" in argv else ""
    if not os.path.isfile(src):
        raise SystemExit(f"no such PDF: {src}")
    if not os.path.isfile(os.path.join(old, "app", "aitakeoff.py")):
        raise SystemExit(f"not a QuantiSheet folder: {old}")
    tmp = tempfile.mkdtemp(prefix="qs_ait_cmp_")
    pdf = os.path.join(tmp, "plans.pdf")
    shutil.copy2(src, pdf)
    os.chmod(pdf, 0o444)
    out = {"pdf": os.path.basename(src), "pages": pages,
           "when": time.strftime("%Y-%m-%d %H:%M")}
    for name, root in (("before", old), ("now", ROOT)):
        out[name] = run(root, pdf, pages)
        print(name, "done", out[name].get("seconds"), "s",
              out[name].get("error", "")[:300], flush=True)
    with open(OUT + ".json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    lines = [f"AI Takeoff, before vs now - {out['pdf']} "
             f"{('pages ' + pages) if pages else 'all pages'}", ""]
    for name in ("before", "now"):
        r = out[name]
        lines += [f"===== {name.upper()} =====",
                  r.get("error") or
                  f"{r['seconds']} s, {r['marks']} marks, "
                  f"{r['sheets_taken']} sheets taken off",
                  r.get("summary", ""), ""]
    txt = "\n".join(lines)
    with open(OUT + ".txt", "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    os.chmod(pdf, 0o666)
    shutil.rmtree(tmp, ignore_errors=True)


def start(argv):
    """Run in the background (the runner stops a request after 15 min;
    a scanned set takes about 10 min per version)."""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT + ".status", "w") as f:
        f.write("running " + time.strftime("%H:%M:%S"))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | \
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    log = open(OUT + ".log", "w", encoding="utf-8")
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "bg"] + argv,
                     cwd=ROOT, creationflags=flags, stdout=log,
                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     close_fds=True)
    print("started; check with: ai_takeoff_compare status")


def bg(argv):
    try:
        main(argv)
        st = "done"
    except BaseException as e:                         # noqa: BLE001
        st = f"failed {e!r}"[:500]
    with open(OUT + ".status", "w") as f:
        f.write(st + " " + time.strftime("%H:%M:%S"))


def status():
    for ext in (".status", ".log"):
        try:
            with open(OUT + ext, encoding="utf-8", errors="replace") as f:
                print(f.read()[-6000:])
        except OSError:
            print("no", ext)
    if os.path.exists(OUT + ".txt"):
        with open(OUT + ".txt", encoding="utf-8") as f:
            print(f.read())


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["start"]:
        start(a[1:])
    elif a[:1] == ["bg"]:
        bg(a[1:])
    elif a[:1] == ["status"]:
        status()
    else:
        main(a)
