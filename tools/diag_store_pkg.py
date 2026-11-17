"""How the installed QuantiSheet package was installed (read-only):
version and signature kind (Store = from the Microsoft Store).
python tools/diag_store_pkg.py"""
import os
import subprocess

PS = r"""
$ErrorActionPreference = 'Continue'
Get-AppxPackage | Where-Object { $_.SignatureKind -ne 'System' -and $_.Publisher -notmatch 'Microsoft' -and ((Get-AppxPackageManifest $_).Package.Properties.DisplayName -match 'Quanti') } |
  ForEach-Object { "PKG $($_.Name) $($_.Version) $($_.SignatureKind) $($_.InstallLocation -replace '.*\\','')" }
"count of all packages: $((Get-AppxPackage).Count)"
"user: $env:USERNAME"
Get-StartApps | Where-Object { $_.Name -match 'Quanti' } | ForEach-Object { "START $($_.Name) | $($_.AppID)" }
Get-Process | Where-Object { $_.ProcessName -match 'Quanti' } | ForEach-Object { "PROC $($_.ProcessName) $($_.Path)" }
Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory | Where-Object { $_.Name -match 'Quanti' } | ForEach-Object { "DATA $($_.Name)" }
Get-AppxPackage | Where-Object { $_.Name -match 'Quanti' -or $_.PackageFullName -match 'Quanti' } | ForEach-Object { "PKG2 $($_.PackageFullName) $($_.SignatureKind)" }
"""
exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                   "WindowsPowerShell", "v1.0", "powershell.exe")
r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                    "Bypass", "-Command", PS], capture_output=True, text=True,
                   timeout=120)
print(r.stdout)
print("stderr:", r.stderr[:800])
