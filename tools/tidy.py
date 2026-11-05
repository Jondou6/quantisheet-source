"""Tidy the program folder: one-off debugging scripts and batch files go
to tools/scratch (out of the program), and the stale test-results.txt is
removed (run-tests.bat writes a fresh one).

    python tools/tidy.py [--dry-run]
"""
import fnmatch
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
SCRATCH = os.path.join(TOOLS, "scratch")
TOOL_PATTERNS = ["dbg_*", "probe_*", "dxf_trial*", "dxf_view*", "dxf_probe*",
                 "overlay_trial*", "diag_*", "civil_debug.py", "*_trial.py"]
ROOT_FILES = ["autotakeoff-check.bat", "check-autotakeoff.bat",
              "demo-autotakeoff.bat", "diag-gaps.bat", "dump-autotakeoff.bat",
              "trial-run.bat", "autotakeoff-results.txt"]
STALE = ["test-results.txt"]


def plan():
    moves, deletes = [], []
    for name in sorted(os.listdir(TOOLS)):
        full = os.path.join(TOOLS, name)
        if os.path.isfile(full) and any(fnmatch.fnmatch(name, p)
                                        for p in TOOL_PATTERNS):
            moves.append((full, os.path.join(SCRATCH, name)))
    for name in ROOT_FILES:
        full = os.path.join(ROOT, name)
        if os.path.isfile(full):
            moves.append((full, os.path.join(SCRATCH, name)))
    for name in STALE:
        full = os.path.join(ROOT, name)
        if os.path.isfile(full):
            deletes.append(full)
    return moves, deletes


def main(argv):
    dry = "--dry-run" in argv
    moves, deletes = plan()
    if not dry:
        os.makedirs(SCRATCH, exist_ok=True)
        with open(os.path.join(SCRATCH, "README.txt"), "w") as f:
            f.write("One-off debugging and trial scripts kept for reference."
                    "\nNot part of the program; safe to delete.\n")
    for a, b in moves:
        print("move", os.path.relpath(a, ROOT), "->",
              os.path.relpath(b, ROOT))
        if not dry:
            shutil.move(a, b)
    for d in deletes:
        print("delete", os.path.relpath(d, ROOT))
        if not dry:
            os.remove(d)
    print(f"{len(moves)} moved, {len(deletes)} deleted"
          + (" (dry run)" if dry else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
