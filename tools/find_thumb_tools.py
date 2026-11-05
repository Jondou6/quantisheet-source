"""Read-only: what this PC has for building the Explorer thumbnail
add-in (Nov 4): the C# compiler, the Windows metadata for the PDF
renderer, dotnet, and which program draws PDF thumbnails today."""
import glob
import os
import shutil
import subprocess
import winreg

win = os.environ.get("WINDIR", r"C:\Windows")
for p in (os.path.join(win, r"Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
          os.path.join(win, r"Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe")):
    print(os.path.basename(p), "->", os.path.isfile(p))
print("dotnet ->", shutil.which("dotnet"))
if shutil.which("dotnet"):
    out = subprocess.run(["dotnet", "--list-sdks"], capture_output=True,
                         text=True, timeout=60).stdout.strip()
    print("  sdks:", out or "none")
w = glob.glob(os.path.join(win, "System32", "WinMetadata", "Windows.Data.winmd"))
print("Windows.Data.winmd ->", w)
ref = glob.glob(r"C:\Program Files (x86)\Reference Assemblies\Microsoft"
                r"\Framework\.NETFramework\v4.*\Facades\System.Runtime.dll")
print("facades ->", ref[:2])
rt = glob.glob(os.path.join(win, r"Microsoft.NET\Framework64\v4.0.30319",
                            "System.Runtime.WindowsRuntime.dll"))
print("System.Runtime.WindowsRuntime.dll ->", rt)
for root, name in ((winreg.HKEY_CLASSES_ROOT,
                    r".pdf\ShellEx\{e357fccd-a995-4576-b01f-234630154e96}"),
                   (winreg.HKEY_CURRENT_USER, r"Software\Classes\.pdf\ShellEx"
                    r"\{e357fccd-a995-4576-b01f-234630154e96}")):
    try:
        with winreg.OpenKey(root, name) as k:
            print("thumbnail handler now:", name.split("\\")[0],
                  winreg.QueryValueEx(k, "")[0])
    except OSError:
        print("thumbnail handler now:", name[:40], "none")
