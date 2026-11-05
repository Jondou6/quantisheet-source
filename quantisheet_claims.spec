# -*- mode: python ; coding: utf-8 -*-
# ClaimIT - a SEPARATE program from QuantiSheet.
# Build with:  pyinstaller --clean --noconfirm quantisheet_claims.spec
# Makes dist/ClaimIT/ClaimIT.exe (one folder), which
# installer/quantisheet_claims.iss installs to a ClaimIT\ folder
# beside QuantiSheet's install folder, where app/claims_hook.launcher()
# looks for it. QuantiSheet's own spec excludes "quantisheet_claims".
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

ROOT = SPECPATH

# the program only - never its tests (r47 review #14)
hidden = [m for m in collect_submodules("quantisheet_claims")
          if ".tests" not in m] + ["openpyxl"]
hidden += ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"]

icon_file = os.path.join(ROOT, "icon.ico")
if sys.platform == "darwin" or not os.path.exists(icon_file):
    icon_file = None

a = Analysis(
    [os.path.join(ROOT, "claimit_launch.py")],   # not __main__.py: see it
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "IPython", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtQuick",
        "app",          # never bundle QuantiSheet's own package
        "quantisheet_claims.tests",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClaimIT",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX breaks Qt libraries and trips antivirus
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ClaimIT",
)
