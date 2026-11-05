"""Read-only: is QuantiSheet (or ClaimIT) running on this PC right now?
    python tools/is_running.py"""
import subprocess

out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                     text=True, timeout=60).stdout
names = {"quantisheet.exe", "claimit.exe"}
hits = [ln for ln in out.splitlines()
        if ln.split(",")[0].strip('"').lower() in names]
print("running:" if hits else "not running", *hits, sep="\n  ")
