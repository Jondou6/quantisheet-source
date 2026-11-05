"""Read-only: who may change HKCU\\Software\\Policies (Venice review M1).

    python tools/acl_probe.py
"""
import subprocess

for key in (r"HKCU:\Software\Policies", r"HKLM:\Software\Policies"):
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"(Get-Acl '{key}').Access | Format-Table "
                        "IdentityReference,RegistryRights,AccessControlType,"
                        "IsInherited -AutoSize | Out-String -Width 200"],
                       capture_output=True, text=True, timeout=60)
    print(key, "\n", (p.stdout + p.stderr).strip())
