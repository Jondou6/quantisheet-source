"""List running QuantiSheet.exe processes (read-only): pid, command line,
and whether each runs elevated."""
import subprocess

ps = (r"Get-CimInstance Win32_Process -Filter \"Name='QuantiSheet.exe'\" | "
      r"ForEach-Object { $o = Invoke-CimMethod -InputObject $_ "
      r"-MethodName GetOwner; '{0} | {1} | {2}' -f $_.ProcessId, "
      r"$o.User, $_.CommandLine }")
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, text=True, timeout=60)
print(r.stdout.strip() or "no QuantiSheet.exe running")
print(r.stderr.strip()[:500])
for image in ("QuantiSheet.exe",):
    r2 = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/V",
                         "/FO", "CSV"], capture_output=True, text=True,
                        timeout=60)
    print(r2.stdout.strip()[:2000])
