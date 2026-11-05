"""Read-only: when was QuantiSheet last installed on this PC, and by what
(Nov 4: Jon saw a setup window waiting for him). Prints the install
folder's file times, any setup logs in TEMP and the update download
folder. Changes nothing."""
import datetime
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import branding, updatecheck                    # noqa: E402


def t(p):
    return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime(
        "%Y-%m-%d %H:%M:%S")


exe = branding.installed_exe()
d = os.path.dirname(exe)
print("install folder:", d)
for n in ("QuantiSheet.exe", "unins000.exe", "unins000.dat", "unins000.msg"):
    p = os.path.join(d, n)
    if os.path.exists(p):
        print(f"  {n:16} {t(p)}  {os.path.getsize(p):,} bytes")
tmp = os.environ.get("TEMP", "")
print("TEMP:", tmp)
for p in sorted(glob.glob(os.path.join(tmp, "Setup Log*.txt")) +
                glob.glob(os.path.join(tmp, "is-*")),
                key=os.path.getmtime)[-12:]:
    print(f"  {t(p)}  {os.path.basename(p)}")
try:
    f = updatecheck.download_dir()
except Exception as e:                                    # noqa: BLE001
    f = ""
    print("download folder: ?", e)
if f and os.path.isdir(f):
    print("update downloads:", f)
    for p in sorted(glob.glob(os.path.join(f, "*")), key=os.path.getmtime):
        print(f"  {t(p)}  {os.path.basename(p)}  {os.path.getsize(p):,}")
for p in sorted(glob.glob(os.path.join(tmp, "Setup Log*.txt")),
                key=os.path.getmtime)[-1:]:
    print("== newest setup log:", os.path.basename(p))
    with open(p, encoding="utf-8-sig", errors="replace") as fh:
        lines = fh.readlines()
    for ln in lines[:8] + ["...\n"] + lines[-8:]:
        print("   " + ln.rstrip()[:220])
