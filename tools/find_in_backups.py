"""Search the source backup folders for a word (read-only):
python tools/find_in_backups.py WORD [subfolder]"""
import glob
import os
import sys

word = sys.argv[1]
sub = sys.argv[2] if len(sys.argv) > 2 else "app"
home = os.path.expanduser("~")
# quantisheet-backup-* (tools/backup_folder.py), and pdfstudio-backup-*
# made before the rename
for b in sorted(glob.glob(os.path.join(home, "quantisheet-backup-*")) +
                glob.glob(os.path.join(home, "pdfstudio-backup-*"))):
    hits = []
    for f in glob.glob(os.path.join(b, sub, "**", "*.py"), recursive=True):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for i, ln in enumerate(fh, 1):
                    if word in ln:
                        hits.append(f"{os.path.relpath(f, b)}:{i}")
        except OSError:
            pass
    print(os.path.basename(b), len(hits), hits[:6])
