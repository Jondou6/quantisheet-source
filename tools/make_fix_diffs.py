"""Unified diffs of the live source against a backup folder, one section
per fix, for a FROM_CLAUDE reply.

    python tools/make_fix_diffs.py BACKUP_DIR OUT_FILE FIX=path,path ...

Each FIX=... argument names a fix and the files (relative to the source
root) that belong to it; a file new since the backup diffs against
nothing."""
import difflib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p):
    try:
        with open(p, encoding="utf-8", newline="") as f:
            return f.read().splitlines(keepends=True)
    except FileNotFoundError:
        return []


def main():
    backup, out = sys.argv[1], sys.argv[2]
    parts = []
    for arg in sys.argv[3:]:
        fix, _, files = arg.partition("=")
        parts.append(f"===== {fix} =====\n")
        for rel in [x for x in files.split(",") if x]:
            a = read(os.path.join(backup, rel))
            b = read(os.path.join(ROOT, rel))
            d = list(difflib.unified_diff(
                a, b, fromfile=f"a/{rel}" if a else "/dev/null",
                tofile=f"b/{rel}"))
            parts.extend(d if d else [f"(no change in {rel})\n"])
            if d and not d[-1].endswith("\n"):
                parts.append("\n")
        parts.append("\n")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(parts)
    print(out, sum(1 for p in parts if p.startswith("+++")), "file diffs")


main()
