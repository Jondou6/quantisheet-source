"""Back up the source folder (and the price database) before a change.

    python tools/backup_folder.py [LABEL]

Copies the folder - without .venv, caches and build output - to
%USERPROFILE%\\quantisheet-backup-YYYYMMDD-HHMM[-LABEL] and copies the price
database next to it. Prints the backup folder."""
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SKIP = {".venv", "__pycache__", ".pytest_cache", "release", "build", "dist"}


def main():
    label = "-".join(a.strip('"') for a in sys.argv[1:])
    stamp = time.strftime("%Y%m%d-%H%M")
    dest = os.path.join(os.path.expanduser("~"),
                        f"quantisheet-backup-{stamp}" +
                        (f"-{label}" if label else ""))
    n = 0

    def ignore(d, names):
        return [x for x in names if x in SKIP]
    shutil.copytree(ROOT, dest, ignore=ignore, dirs_exist_ok=True)
    for _d, _s, files in os.walk(dest):
        n += len(files)
    try:
        from app import pricedb
        if os.path.exists(pricedb.path()):
            pricedb.backup(os.path.join(dest, "prices-backup.db"))
            print("price database backed up")
    except Exception as e:
        print("price database not backed up:", e)
    print(f"backup: {dest} ({n} files)")


if __name__ == "__main__":
    main()
