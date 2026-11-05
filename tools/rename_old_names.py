"""One time, on Jon's PC, after the Oct 30 rename. Renames and moves only -
nothing is copied over or deleted:
  * ~/PDF Studio Keys is renamed ~/QuantiSheet Keys (tools/beta_keys.py
    looks there now);
  * the old shipped cost book file and the tools that only served the old
    name are moved into _to_delete\\ in the project folder, for Jon to
    delete by hand.
Run again, it does nothing."""
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
home = os.path.expanduser("~")
old = os.path.join(home, "PDF Studio Keys")
new = os.path.join(home, "QuantiSheet Keys")
if os.path.isdir(new):
    print("keys folder already there:", new)
elif not os.path.isdir(old):
    print("no keys folder to rename:", old)
else:
    os.rename(old, new)
    print("renamed:", old, "->", new)
    print("  files:", sorted(os.listdir(new)))

OUT = os.path.join(ROOT, "_to_delete")
MOVE = [
    ("app", "data", "costbooks", "PDF Studio Starter 2026.json"),
    ("app", "heavy.py.orig"),
    ("tools", "brand_check.py"), ("tools", "brand_files.py"),
    ("tools", "brand_migrate.py"), ("tools", "data_dirs_list.py"),
    ("tools", "upgrade_probe.py"), ("tools", "claims_trial.py"),
    ("tools", "oldname_scan.py"), ("tools", "oldname_scan2.py"),
]
for parts in MOVE:
    src = os.path.join(ROOT, *parts)
    if not os.path.isfile(src):
        continue
    dst = os.path.join(OUT, *parts)
    if os.path.exists(dst):
        print("already in _to_delete, left:", src)
        continue
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    print("moved:", os.path.join(*parts), "-> _to_delete")
print("left in", OUT if os.path.isdir(OUT) else "(nothing moved)")
