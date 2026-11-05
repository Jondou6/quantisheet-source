"""Print the end of QuantiSheet's logs (~/.quantisheet) for a crash
report.

    python tools/show_logs.py [LINES]
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import settings                                     # noqa: E402

DIR = settings.DIR
n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
for name in ("crash.log", settings.LOG_NAME):
    p = os.path.join(DIR, name)
    if not os.path.exists(p):
        print(f"== {name}: none")
        continue
    st = os.stat(p)
    print(f"== {name}: {st.st_size:,} bytes, modified "
          f"{datetime.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}")
    with open(p, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    for line in lines[-n:]:
        print("   " + line.rstrip()[:300])
