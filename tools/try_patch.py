"""Try a proposed autotakeoff.py change in a throwaway copy (Nov 2, Jon:
OK to test Chief's room 109 patch on a separate copy). The live program
folder is not touched: app\\ and tests\\ are copied to a temp folder, the
proposed file replaces app\\autotakeoff.py there, and:

  1. HMB sheet A101's rooms are measured with the live code and the
     copy, side by side against the truth areas;
  2. the room tests run in the copy (with the HMB plan set for the new
     test).

    python tools/try_patch.py PATCH_DIR PLAN.pdf [PAGE]

PATCH_DIR holds app\\autotakeoff.py and optional tests\\*.py to drop in.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUTH = {"109": 129.8, "104": 135.3, "103": 170.6, "108": 153.1,
         "105": 159.7, "106": 139.5, "110": 145.4, "111": 199.1,
         "112": 248.0}
TESTS = ["tests/test_room_bench_passage.py", "tests/test_resolve_overlaps.py",
         "tests/test_autotakeoff.py", "tests/test_rooms_real.py",
         "tests/test_autotakeoff_sideways_rooms.py",
         "tests/test_rooms_walls_phase2.py",
         "tests/test_autotakeoff_hidden_ink.py",
         "tests/test_patent_design_rules.py"]

MEASURE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import fitz
from app import autotakeoff as at
prev = fitz.TOOLS.set_small_glyph_heights()
fitz.TOOLS.set_small_glyph_heights(False)
doc = fitz.open(sys.argv[2])
found, _m = at.all_rooms(at.cached_page(doc[int(sys.argv[3])]),
                         {"ppu": 18.0, "unit": "ft"})
fitz.TOOLS.set_small_glyph_heights(prev)
print(json.dumps({str(f.get("number")): round(f["sqft"], 1) for f in found}))
"""


def measure(root, plan, page):
    r = subprocess.run([sys.executable, "-c", MEASURE, root, plan, str(page)],
                       capture_output=True, text=True, timeout=400)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(r.stderr[-2000:])
        return {}


def main(argv):
    argv = [a.strip('"') for a in argv]
    pdir, plan = argv[0], argv[1]
    page = int(argv[2]) if len(argv) > 2 else 4
    tmp = tempfile.mkdtemp(prefix="qs_trypatch_")
    try:
        for d in ("app", "tests"):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(tmp, d),
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(ROOT, "tools"),
                        os.path.join(tmp, "tools"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        for f in os.listdir(ROOT):           # make_sample.py, pyproject...
            if f.endswith((".py", ".toml", ".cfg", ".ini")) and \
                    os.path.isfile(os.path.join(ROOT, f)):
                shutil.copy2(os.path.join(ROOT, f), tmp)
        for sub in ("app", "tests"):
            src = os.path.join(pdir, sub)
            if os.path.isdir(src):
                for n in os.listdir(src):
                    shutil.copy2(os.path.join(src, n),
                                 os.path.join(tmp, sub, n))
                    print("copy uses proposed", sub + "\\" + n)
        before = measure(ROOT, plan, page)
        after = measure(tmp, plan, page)
        print("\nroom   truth   live    patched   (off by, live -> patched)")
        ok_b = ok_a = 0
        for num, t in TRUTH.items():
            b, a = before.get(num), after.get(num)

            def pct(v):
                return None if v is None else (v - t) / t * 100
            pb, pa = pct(b), pct(a)
            ok_b += pb is not None and abs(pb) <= 8
            ok_a += pa is not None and abs(pa) <= 8
            print(f"{num:5} {t:7.1f} {b!s:>7} {a!s:>9}   "
                  f"{'-' if pb is None else f'{pb:+.1f}%'} -> "
                  f"{'-' if pa is None else f'{pa:+.1f}%'}")
        others = sorted(set(before) | set(after))
        print(f"\nwithin 8%: live {ok_b}/{len(TRUTH)}, patched "
              f"{ok_a}/{len(TRUTH)}")
        print("other rooms (live -> patched):",
              {k: (before.get(k), after.get(k)) for k in others
               if k not in TRUTH})
        env = dict(os.environ, QS_HMB_PLAN=plan)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rf",
                            "-p", "no:cacheprovider"] +
                           [t for t in TESTS
                            if os.path.exists(os.path.join(tmp, t))],
                           cwd=tmp, env=env, capture_output=True, text=True,
                           timeout=700)
        print("\ntests in the copy:")
        print("\n".join(r.stdout.strip().splitlines()[-15:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
