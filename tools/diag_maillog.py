"""What the log says about PDFs dragged in from email: when, and which
way each one came (with the drag itself, fetched from Outlook, or not at
all). File names are left out - they can name a job.

    python tools/diag_maillog.py [how many lines, default 30]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KEEP = ("mail drop", "mail drag", "dragged PDF not saved",
        "Outlook didn't hand over")


def lines(text, n=30):
    out = []
    for ln in text.splitlines():
        if any(k in ln for k in KEEP):
            # "mail drag not opened (names); it carried: formats"
            ln = re.sub(r"not opened \(.*?\); it carried",
                        "not opened (names left out); it carried", ln)
            out.append(ln[:400])
    return out[-n:]


def main(argv):
    from app import main as app_main, settings
    n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 30
    path = os.path.join(app_main.log_folder(), settings.LOG_NAME)
    found = []
    for p in (path + ".old", path):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        found += lines(text, n)
        rows = text.splitlines()
        stamps = [r[:19] for r in rows if r[:4].isdigit()]
        print(f"{os.path.basename(p)}: {len(rows)} lines, "
              f"{stamps[0] if stamps else '?'} to "
              f"{stamps[-1] if stamps else '?'}, "
              f"{sum('browser takeoff' in r for r in rows)} about browser "
              "takeoff")
    print(f"{len(found[-n:])} line(s) about mail drops")
    for ln in found[-n:]:
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
