"""What takes the room in the built program folder, read-only:
python tools/diag_dist_size.py [N]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(os.environ.get("LOCALAPPDATA") or "", "QuantiSheetBuild",
                    "dist", "QuantiSheet")


def main(a):
    n = int(a[0]) if a else 40
    files, dirs = [], {}
    for base, _d, fs in os.walk(DIST):
        for f in fs:
            p = os.path.join(base, f)
            s = os.path.getsize(p)
            rel = os.path.relpath(p, DIST)
            files.append((s, rel))
            parts = rel.split(os.sep)
            for k in range(1, min(4, len(parts))):
                key = os.sep.join(parts[:k])
                dirs[key] = dirs.get(key, 0) + s
    total = sum(s for s, _ in files)
    print(f"{DIST}: {total / 2**20:.0f} MB in {len(files)} files")
    print("largest folders:")
    for k, s in sorted(dirs.items(), key=lambda x: -x[1])[:n]:
        print(f"  {s / 2**20:7.1f} MB  {k}")
    print("largest files:")
    for s, rel in sorted(files, reverse=True)[:n]:
        print(f"  {s / 2**20:7.1f} MB  {rel}")


if __name__ == "__main__":
    main(sys.argv[1:])
