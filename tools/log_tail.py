"""Show the end of the installed QuantiSheet's log (read-only), optionally
only lines matching a word:  python tools/log_tail.py [WORD] [N]"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import settings                                     # noqa: E402

word = sys.argv[1] if len(sys.argv) > 1 else ""
n = int(sys.argv[2]) if len(sys.argv) > 2 else 80
p = os.path.join(settings.DIR, settings.LOG_NAME)
print("log:", p, os.path.isfile(p))
if os.path.isfile(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    if word:
        idx = [i for i, ln in enumerate(lines) if re.search(word, ln, re.I)]
        keep = sorted({j for i in idx for j in range(i, min(i + 12,
                                                             len(lines)))})
        lines = [lines[j] for j in keep]
    # no addresses or user paths in what we read back
    for ln in lines[-n:]:
        ln = re.sub(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", "<email>", ln)
        print(ln[:400])
