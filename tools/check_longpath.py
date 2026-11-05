"""Read-only: is QuantiSheet long-path aware? (PR 17 follow-up, Nov 4)

Looks for longPathAware in the installed PyInstaller (its default
manifest) and in the built QuantiSheet.exe, and prints the machine's
LongPathsEnabled setting. Changes nothing."""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        import PyInstaller
        base = os.path.dirname(PyInstaller.__file__)
        print("PyInstaller", getattr(PyInstaller, "__version__", "?"), base)
        hits = []
        for p in glob.glob(os.path.join(base, "**", "*.py"), recursive=True):
            try:
                if "longPathAware" in open(p, encoding="utf-8",
                                           errors="replace").read():
                    hits.append(os.path.relpath(p, base))
            except OSError:
                pass
        print("PyInstaller files naming longPathAware:", hits or "none")
    except ImportError:
        print("PyInstaller not installed")
    for exe in glob.glob(os.path.join(ROOT, "dist", "**", "QuantiSheet.exe"),
                         recursive=True):
        data = open(exe, "rb").read()
        i = data.find(b"longPathAware")
        j = data.find("longPathAware".encode("utf-16-le"))
        print(exe, "manifest longPathAware:",
              "yes" if i >= 0 or j >= 0 else "no")
        if i >= 0:
            print("  ", data[max(0, i - 60):i + 80])
    if sys.platform.startswith("win"):
        import winreg
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"SYSTEM\CurrentControlSet\Control\FileSystem")
            print("LongPathsEnabled =", winreg.QueryValueEx(
                k, "LongPathsEnabled")[0])
        except OSError as e:
            print("LongPathsEnabled: not readable", e)


if __name__ == "__main__":
    main()
