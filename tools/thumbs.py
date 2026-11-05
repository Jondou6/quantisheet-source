"""Explorer PDF thumbnails (Nov 4, experimental; Jon's PC only for now).

    python tools/thumbs.py build    compile the add-in (thumbs\\*.cs)
    python tools/thumbs.py test PDF draw a thumbnail of PDF the add-in's way
    python tools/thumbs.py on       turn thumbnails on for this user
    python tools/thumbs.py off      turn them off (same as
                                    thumbs\\turn_off_thumbnails.bat)
    python tools/thumbs.py status

Only this user's registry (HKCU) is changed; nothing needs admin. The DLL
lives in %LOCALAPPDATA%\\QuantiSheet\\thumbs. Windows runs it in its
isolated thumbnail process, not inside Explorer.
"""
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "thumbs")
OUT = os.path.join(os.environ.get("LOCALAPPDATA", ""), "QuantiSheet", "thumbs")
DLL = os.path.join(OUT, "QuantiSheetThumbs.dll")
TEST_EXE = os.path.join(OUT, "thumbtest.exe")
CLSID = "{6E1B2C3A-9D47-4F0B-8A51-2C7D0E4B9F16}"
THUMB_IID = "{e357fccd-a995-4576-b01f-234630154e96}"
CLASS = "QuantiSheet.Thumbs.PdfThumbnail"
ASSEMBLY = "QuantiSheetThumbs, Version=0.0.0.0, Culture=neutral, " \
           "PublicKeyToken=null"
WIN = os.environ.get("WINDIR", r"C:\Windows")
FW = os.path.join(WIN, r"Microsoft.NET\Framework64\v4.0.30319")


def refs():
    out = ["System.Drawing.dll"]
    for n in ("Windows.Foundation", "Windows.Storage", "Windows.Data",
              "Windows.UI"):
        p = os.path.join(WIN, "System32", "WinMetadata", n + ".winmd")
        if os.path.isfile(p):
            out.append(p)
    for n in ("System.Runtime.WindowsRuntime.dll", "System.Runtime.dll",
              "System.Threading.Tasks.dll",
              "System.Runtime.InteropServices.WindowsRuntime.dll"):
        hits = [os.path.join(FW, n)] + sorted(glob.glob(os.path.join(
            r"C:\Program Files (x86)\Reference Assemblies\Microsoft"
            r"\Framework\.NETFramework", "v4.*", "Facades", n)))
        hits += sorted(glob.glob(os.path.join(FW, "WPF", n)))
        hit = next((h for h in hits if os.path.isfile(h)), None)
        if hit:
            out.append(hit)
    return out


def build():
    csc = os.path.join(FW, "csc.exe")
    os.makedirs(OUT, exist_ok=True)
    r = ["/nologo", "/optimize+", "/platform:x64"] + \
        [f"/r:{x}" for x in refs()]
    for args in ([csc, "/target:library", f"/out:{DLL}"] + r +
                 [os.path.join(SRC, "QuantiSheetThumbs.cs")],
                 [csc, "/target:exe", f"/out:{TEST_EXE}", f"/r:{DLL}"] + r +
                 [os.path.join(SRC, "thumbtest.cs")]):
        p = subprocess.run(args, capture_output=True, text=True, timeout=300)
        print(p.stdout[-3000:], p.stderr[-2000:])
        if p.returncode != 0:
            raise SystemExit("build failed")
    print("built", DLL)


def test(pdf, size=256):
    out = os.path.join(ROOT, ".run", "test_thumb.png")
    pdf = pdf.strip("\"")
    p = subprocess.run([TEST_EXE, pdf, str(size), out], capture_output=True,
                       text=True, timeout=120)
    print(p.stdout[-2000:], p.stderr[-1000:])
    return p.returncode


def _set(path, values):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        for name, v in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, v)


def _notify():
    import ctypes
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def on():
    if not os.path.isfile(DLL):
        raise SystemExit("build it first: thumbs.py build")
    base = rf"Software\Classes\CLSID\{CLSID}"
    _set(base, {"": "QuantiSheet PDF Thumbnail"})
    vals = {"": "mscoree.dll", "ThreadingModel": "Both", "Class": CLASS,
            "Assembly": ASSEMBLY, "RuntimeVersion": "v4.0.30319",
            "CodeBase": "file:///" + DLL.replace("\\", "/")}
    _set(base + r"\InprocServer32", vals)
    _set(base + r"\InprocServer32\0.0.0.0", {k: v for k, v in vals.items()
                                            if k not in ("", "ThreadingModel")})
    _set(rf"Software\Classes\.pdf\ShellEx\{THUMB_IID}", {"": CLSID})
    _notify()
    print("thumbnails ON for this user")


def _delete_tree(path):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(path + "\\" + sub)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


def off():
    _delete_tree(rf"Software\Classes\.pdf\ShellEx\{THUMB_IID}")
    _delete_tree(rf"Software\Classes\CLSID\{CLSID}")
    _notify()
    print("thumbnails OFF for this user")


def status():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            rf"Software\Classes\.pdf\ShellEx\{THUMB_IID}") as k:
            v = winreg.QueryValueEx(k, "")[0]
        print("thumbnails:", "ON" if v.upper() == CLSID.upper() else
              f"another handler {v}")
    except OSError:
        print("thumbnails: off")
    print("dll:", DLL, os.path.isfile(DLL))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"build": build, "on": on, "off": off, "status": status,
     "test": lambda: sys.exit(test(sys.argv[2]))}[cmd]()
