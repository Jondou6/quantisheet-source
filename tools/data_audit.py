"""Where QuantiSheet's data lives on this PC (read only; Nov 4 audit for
the shared-library plan). Prints each store's path, size, whether it is
inside a synced folder, and for SQLite files the journal mode and any
-wal / -journal files beside them. Changes nothing.

    python tools/data_audit.py
"""
import glob
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SYNCED = ("onedrive", "dropbox", "google drive", "icloud", "box sync",
          "sharepoint")


def synced(p):
    return any(k in os.path.abspath(p).lower() for k in SYNCED)


def size(p):
    if os.path.isfile(p):
        return os.path.getsize(p)
    t = 0
    for d, _s, fs in os.walk(p):
        for f in fs:
            try:
                t += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return t


def show(label, p):
    if not p:
        print(f"{label}: (not set)")
        return
    ex = os.path.exists(p)
    print(f"{label}: {p}  exists={ex}  "
          f"size={size(p) if ex else 0:,}  SYNCED={synced(p)}")


def dbinfo(p):
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            mode = c.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            c.close()
    except Exception as e:                               # noqa: BLE001
        mode = f"? ({e})"
    side = [s for s in ("-wal", "-shm", "-journal") if os.path.exists(p + s)]
    print(f"   SQLite {p}  journal_mode={mode}  beside={side}  "
          f"SYNCED={synced(p)}")


def main():
    from app import settings, pricedb, databackup
    print("== QuantiSheet per-user data")
    show("settings.DIR", settings.DIR)
    for name in ("toolchest.json", "assemblies.json", "costbooks",
                 "catalogs", "count_library", "packages.json",
                 "timelog.json", "jobdata_backups", "forms"):
        show(f"  {name}", os.path.join(settings.DIR, name))
    try:
        show("price database", pricedb.path())
    except Exception as e:                               # noqa: BLE001
        print("price database: ?", e)
    print("== Service records (equipment & service, pricebook, work orders)")
    try:
        from app.estimating import service
        show("service store", service.default_path())
    except Exception as e:                               # noqa: BLE001
        print("service store: ?", e)
    print("== Back Office")
    bo = databackup.backoffice_home()
    show("Back Office home", bo)
    try:
        import json
        with open(os.path.join(bo, "settings.json"), encoding="utf-8") as f:
            df = json.load(f).get("data_folder")
        show("Back Office company folder (setting)", df)
    except Exception:                                    # noqa: BLE001
        show("Back Office company folder (default)", os.path.join(bo,
                                                                  "data"))
    print("== Every SQLite file in those places")
    seen = set()
    for base in (settings.DIR, bo):
        for p in glob.glob(os.path.join(base, "**", "*"), recursive=True):
            if p in seen or not os.path.isfile(p):
                continue
            try:
                with open(p, "rb") as f:
                    if f.read(16) != b"SQLite format 3\x00":
                        continue
            except OSError:
                continue
            seen.add(p)
            dbinfo(p)
    print("== Live risk: a database inside a synced folder")
    risky = [p for p in seen if synced(p)]
    print("LIVE RISK:" if risky else "none found", *risky, sep="\n  ")


if __name__ == "__main__":
    main()
