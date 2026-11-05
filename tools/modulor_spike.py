"""Generate Set Step 0: the Modulor spike on Windows (plan checklist).

    python tools/modulor_spike.py install     isolated venv + reviewed source
    python tools/modulor_spike.py check       the checklist, DXF -> our PDF
    python tools/modulor_spike.py frozen      import + run inside a PyInstaller exe

Everything happens in %LOCALAPPDATA%\\QuantiSheetModulorSpike - a separate
Python environment. QuantiSheet's own .venv and requirements are not
touched. Modulor is installed from .run/modulor_spike/modulor-40f6c2a.zip,
the exact commit reviewed on Oct 19 (checked by SHA-256 first); only its
dependencies (numpy, manifold3d) come from PyPI.
"""
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP = os.path.join(ROOT, ".run", "modulor_spike", "modulor-40f6c2a.zip")
ZIP_SHA = "c234db9221c6037eda35699e3aa52ad1fbaaf862a7a159d630ad68c27effb0c5"
BASE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                    "QuantiSheetModulorSpike")
VENV = os.path.join(BASE, "venv")
PY = os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt" else \
    os.path.join(VENV, "bin", "python")
OUT = os.path.join(ROOT, ".run", "modulor_spike", "out")

CHECK = r'''
import json, sys, time, os
out = sys.argv[1]
res = {}
t0 = time.perf_counter()
import modulor, manifold3d
from modulor import Cad
from modulor.ops import REGISTRY
res["modulor"] = modulor.__version__
res["manifold3d"] = getattr(manifold3d, "__version__", "?")
res["ops"] = len(REGISTRY)
res["has_ops"] = {k: k in REGISTRY for k in
                  ("set_units", "add_wall", "add_opening", "add_room",
                   "project", "slice", "export")}
cad = Cad(units="ft")
r = []
r.append(cad("set_units", units="ft"))
r.append(cad("add_wall", path=[[0, 0], [40, 0], [40, 20], [0, 20], [0, 0]],
             thickness=0.5, height=9, tag="ext"))
r.append(cad("add_room", name="OFFICE",
             points=[[0, 0], [40, 0], [40, 20], [0, 20]]))
res["room_area"] = r[-1].get("area")
wall = r[1]["created"][0]                 # a bare string means an id
res["wall_id"] = wall
r.append(cad("add_opening", wall=wall, along=10, width=3, type="door"))
r.append(cad("add_opening", wall=wall, along=25, width=4, type="window",
             sill=3, head=7))
r.append(cad("project", select={"tags": ["ext"]}, axis="y",
             layer="elevation", tag="elev_s"))
res["project_created"] = r[-1].get("created")
for name in ("plan.dxf", "plan.svg"):
    p = os.path.join(out, name)
    r.append(cad("export", path=p))
    res["export_" + name] = os.path.exists(p) and os.path.getsize(p)
try:
    from modulor.ops import REGISTRY as R
    res["dxf_insunits"] = None
    txt = open(os.path.join(out, "plan.dxf"), encoding="utf-8",
               errors="replace").read()
    i = txt.find("$INSUNITS")
    if i >= 0:
        res["dxf_insunits"] = txt[i:i + 40].split()[2]
    svg = open(os.path.join(out, "plan.svg"), encoding="utf-8",
               errors="replace").read()
    res["m2_in_dxf"] = ("m2" in txt) or ("m²" in txt)
    res["m2_in_svg"] = ("m2" in svg) or ("m²" in svg)
except Exception as e:
    res["read_error"] = repr(e)
res["ok"] = all(x.get("ok", True) for x in r if isinstance(x, dict))
res["seconds"] = round(time.perf_counter() - t0, 2)
print(json.dumps(res))
'''

FROZEN = r'''
import json, os, sys, time
import modulor
from modulor import Cad
out = os.path.dirname(sys.executable)
cad = Cad(units="ft")
cad("add_wall", path=[[0, 0], [40, 0], [40, 20], [0, 20], [0, 0]],
    thickness=0.5, height=9, tag="ext")
a = cad("add_room", name="OFFICE", points=[[0,0],[40,0],[40,20],[0,20]])
cad("project", select={"tags": ["ext"]}, axis="y", layer="elevation")
cad("export", path=os.path.join(out, "frozen_plan.dxf"))
print(json.dumps({"frozen": bool(getattr(sys, "frozen", False)),
                  "modulor": modulor.__version__, "area": a.get("area"),
                  "dxf": os.path.getsize(os.path.join(out,
                                                      "frozen_plan.dxf"))}))
'''


def sh(cmd, timeout=600):
    t = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr), time.perf_counter() - t


def install():
    h = hashlib.sha256(open(ZIP, "rb").read()).hexdigest()
    print("source zip sha256", h, "OK" if h == ZIP_SHA else "MISMATCH")
    if h != ZIP_SHA:
        raise SystemExit("STOP: the Modulor source is not the reviewed one")
    os.makedirs(BASE, exist_ok=True)
    if not os.path.exists(PY):
        code, out, s = sh([sys.executable, "-m", "venv", VENV])
        print(f"venv: exit {code} in {s:.1f}s", out[-400:])
    code, out, s = sh([PY, "-m", "pip", "install", "--disable-pip-version-check",
                       ZIP], timeout=800)
    print(f"pip install: exit {code} in {s:.1f}s")
    print("\n".join(l for l in out.splitlines()
                    if "Successfully" in l or "ERROR" in l or "manifold" in l
                    or "numpy" in l)[-2000:])
    code, out, _ = sh([PY, "-m", "pip", "show", "manifold3d", "numpy",
                       "modulor"])
    print(out[-1500:])
    code, out, _ = sh([PY, "-c", "import sys,platform;print(sys.version);"
                       "print(platform.machine())"])
    print(out)


def check():
    os.makedirs(OUT, exist_ok=True)
    script = os.path.join(BASE, "spike_check.py")
    open(script, "w", encoding="utf-8").write(CHECK)
    code, out, s = sh([PY, script, OUT])
    print(f"checklist run: exit {code} in {s:.1f}s")
    print(out[-3000:])
    try:
        res = json.loads(out.strip().splitlines()[-1])
    except Exception:
        res = {}
    # DXF -> PDF through QuantiSheet's own converter (main .venv)
    sys.path.insert(0, ROOT)
    import app  # noqa: F401
    from app import dxf
    pdf = os.path.join(OUT, "plan.pdf")
    try:
        summary = dxf.to_pdf(os.path.join(OUT, "plan.dxf"), pdf)
        print("dxf.to_pdf:", json.dumps(summary, default=str)[:1200])
    except Exception as e:
        print("dxf.to_pdf FAILED:", repr(e))
    try:
        import fitz
        svg = fitz.open(os.path.join(OUT, "plan.svg"))
        r = svg[0].rect
        print(f"svg page size {r.width:.2f} x {r.height:.2f} pt")
    except Exception as e:
        print("svg open failed:", repr(e))
    print("RESULT", json.dumps(res))


def frozen():
    script = os.path.join(BASE, "frozen_check.py")
    open(script, "w", encoding="utf-8").write(FROZEN)
    code, out, s = sh([PY, "-m", "pip", "install", "-q",
                       "--disable-pip-version-check",
                       "pyinstaller>=6.3,<7"], timeout=600)
    print(f"pyinstaller install: exit {code} in {s:.1f}s", out[-400:])
    dist = os.path.join(BASE, "dist")
    for attempt, extra in (("plain", []),
                           ("collect-all", ["--collect-all", "modulor",
                                            "--collect-all", "manifold3d"])):
        code, out, s = sh([PY, "-m", "PyInstaller", "--noconfirm", "--clean",
                           "--onedir", "--name", f"spike_{attempt}",
                           "--distpath", dist,
                           "--workpath", os.path.join(BASE, "build"),
                           "--specpath", BASE] + extra + [script],
                          timeout=800)
        print(f"build [{attempt}]: exit {code} in {s:.1f}s")
        if code:
            print(out[-1200:])
            continue
        exe = os.path.join(dist, f"spike_{attempt}", f"spike_{attempt}.exe")
        code, out, s = sh([exe], timeout=120)
        print(f"run [{attempt}]: exit {code} in {s:.1f}s :: {out[-800:]}")
        if code == 0:
            print(f"FROZEN OK with {attempt}")
            return
    print("FROZEN FAILED")


if __name__ == "__main__":
    {"install": install, "check": check, "frozen": frozen}[sys.argv[1]]()
