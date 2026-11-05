"""Which optional packages this Python can import, and their versions.
    python tools/check_imports.py shapely numpy cv2"""
import importlib
import sys

for name in sys.argv[1:] or ["shapely"]:
    try:
        m = importlib.import_module(name)
        print(name, "OK", getattr(m, "__version__", "?"), getattr(m, "__file__", ""))
    except Exception as e:                                # noqa: BLE001
        print(name, "MISSING", type(e).__name__, e)
