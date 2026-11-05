"""Stop the QuantiSheet print helper (the windowless 'QuantiSheet.exe
print-helper' process) so an update can replace the program. Leaves any
open QuantiSheet window alone. It starts again with QuantiSheet or at
sign-in.   python tools/stop_helper.py [list]"""
import subprocess
import sys

PS = ("Get-CimInstance Win32_Process -Filter \"Name='QuantiSheet.exe'\" | "
      "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }")
r = subprocess.run(["powershell", "-NoProfile", "-Command", PS],
                   capture_output=True, text=True, timeout=60)
rows = [ln.split("|", 1) for ln in r.stdout.splitlines() if "|" in ln]
print(r.stderr.strip()[:400])
for pid, cmd in rows:
    helper = "print-helper" in cmd
    print(pid, "print helper" if helper else "QuantiSheet window",
          "|", cmd[:160])
    if helper and (len(sys.argv) < 2 or sys.argv[1] != "list"):
        k = subprocess.run(["taskkill", "/PID", pid, "/F"],
                           capture_output=True, text=True, timeout=60)
        print("  stop:", (k.stdout + k.stderr).strip())
if not rows:
    print("no QuantiSheet.exe running")
