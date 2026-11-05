"""Print the installed versions of the main libraries.
    python tools/versions.py"""
from importlib import metadata

for name in ("PySide6", "shiboken6", "pymupdf", "numpy",
             "opencv-python-headless", "pyhanko", "cryptography", "pillow",
             "ezdxf", "python-pptx", "openpyxl", "pyinstaller", "pytest",
             "pytest-qt"):
    try:
        print(f"{name}=={metadata.version(name)}")
    except metadata.PackageNotFoundError:
        print(f"{name}: not installed")
