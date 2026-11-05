"""Print which optional packages and programs this PC has."""
import importlib
import shutil
import sys

print(sys.version)
for m in ("win32com.client", "pyhanko", "websockets", "fitz", "PIL",
          "cv2", "requests"):
    try:
        mod = importlib.import_module(m)
        print(m, getattr(mod, "__version__", getattr(mod, "VersionBind", "ok")))
    except Exception as e:
        print(m, "MISSING", type(e).__name__)
try:
    import winreg
    winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID")
    print("Outlook: registered")
except Exception as e:
    print("Outlook: not registered", e)
for exe in ("gswin64c", "gswin32c", "gs", "tesseract", "ollama"):
    print(exe, shutil.which(exe))
