"""Tidy the release folder: keep the newest KEEP versions of each product
and move everything older into release\\_to_delete, for Jon to delete
(Nov 25 optimization list: "Clean up old release files"). Nothing is
deleted here.

    python tools/clean_release.py           what it would move (and size)
    python tools/clean_release.py --move    move it

Covered: the installers and What's New PDFs in release\\, release\\github,
release\\msix and the local copy of the testers' update folder
(release\\r2_upload\\<folder>\\team), plus release\\Old. The newest KEEP
versions of QuantiSheet and of ClaimIT stay where they are, as do the
hash lists, READ ME FIRST, the parts lists and version.json."""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = os.path.join(ROOT, "release")
BIN = "_to_delete"
KEEP = 3
VER = re.compile(r"[- ](\d+)\.(\d+)\.(\d+)(?:\.exe|\.msi|\.msix| - Whats New"
                 r"\.pdf)$")


def product(name):
    return "ClaimIT" if name.startswith("ClaimIT") else "QuantiSheet"


def folders(rel=REL):
    out = [rel, os.path.join(rel, "github"), os.path.join(rel, "msix")]
    up = os.path.join(rel, "r2_upload")
    if os.path.isdir(up):
        out += [os.path.join(up, d, "team") for d in sorted(os.listdir(up))]
    return [d for d in out if os.path.isdir(d)]


def plan(rel=REL, keep=KEEP):
    """[(source path, destination path, bytes)] of what to move."""
    moves = []
    for d in folders(rel):
        groups = {}
        for n in os.listdir(d):
            p = os.path.join(d, n)
            m = VER.search(n)
            if m and os.path.isfile(p):
                v = tuple(int(x) for x in m.groups())
                groups.setdefault(product(n), {}).setdefault(v, []).append(n)
        for vs in groups.values():
            for v in sorted(vs)[:-keep]:
                for n in vs[v]:
                    src = os.path.join(d, n)
                    dst = os.path.join(rel, BIN, os.path.relpath(src, rel))
                    moves.append((src, dst, os.path.getsize(src)))
    old = os.path.join(rel, "Old")
    if os.path.isdir(old):
        size = sum(os.path.getsize(os.path.join(a, f))
                   for a, _d, fs in os.walk(old) for f in fs)
        moves.append((old, os.path.join(rel, BIN, "Old"), size))
    return moves


def kept(rel=REL, keep=KEEP):
    gone = {s for s, _d, _b in plan(rel, keep)}
    out = set()
    for d in folders(rel):
        for n in os.listdir(d):
            m = VER.search(n)
            if m and os.path.join(d, n) not in gone:
                out.add((product(n), ".".join(m.groups())))
    return sorted(out)


def move(moves):
    for src, dst, _b in moves:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            raise SystemExit(f"already in {BIN}: {os.path.relpath(dst, REL)}")
        shutil.move(src, dst)


def main(argv):
    moves = plan()
    gb = sum(b for _s, _d, b in moves) / 2 ** 30
    print("keeping:", ", ".join(f"{p} {v}" for p, v in kept()))
    print(f"{len(moves)} item(s) to move to release\\{BIN}: {gb:.1f} GB")
    if "--move" in argv:
        move(moves)
        print(f"moved. Delete release\\{BIN} when you're happy with it.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
