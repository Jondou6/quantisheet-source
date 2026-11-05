"""Windows' own record of QuantiSheet crashes (Application event log).

    python tools/win_crashes.py [HOURS]
"""
import subprocess
import sys

hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
ps = (
    "$since=(Get-Date).AddHours(-%d);"
    "Get-WinEvent -FilterHashtable @{LogName='Application';StartTime=$since}"
    " -ErrorAction SilentlyContinue |"
    " Where-Object { $_.Message -match 'QuantiSheet' } |"
    " Select-Object -First 12 |"
    " ForEach-Object { '==== ' + $_.TimeCreated + ' ' + $_.ProviderName +"
    " ' id ' + $_.Id; $_.Message }" % hours)
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, text=True, timeout=120)
out = (r.stdout or "").strip()
print(out[:12000] if out else f"no QuantiSheet events in the last {hours} h")
if r.stderr.strip():
    print("stderr:", r.stderr.strip()[:2000])
