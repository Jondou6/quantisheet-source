"""Find a PDF by name pattern under the user's folders (read-only; prints
paths only): python tools/find_job_pdf.py PATTERN"""
import fnmatch
import os
import sys

pat = sys.argv[1].lower()
home = os.path.expanduser("~")
roots = [os.path.join(home, d) for d in ("OneDrive", "Desktop", "Documents",
                                         "Downloads")]
skip = ("SlowBooks", "FOR_CLAUDE_BackOffice", "04. Planswift Takeoff",
        "Credit Reports", "AppData", "node_modules", ".git")
n = 0
for r in roots:
    for dp, dns, fns in os.walk(r):
        dns[:] = [d for d in dns if not any(s in d for s in skip)]
        for f in fns:
            if fnmatch.fnmatch(f.lower(), pat):
                print(os.path.join(dp, f))
                n += 1
                if n > 30:
                    sys.exit(0)
