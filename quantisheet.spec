# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller --clean --noconfirm quantisheet.spec
# Makes a one-folder build, dist/QuantiSheet/QuantiSheet.exe, which the
# installer (installer/quantisheet.iss, tools/build_installer.py) packages.
# One folder starts in a second or two; a one-file exe unpacks ~400 MB to
# a temp folder on every start.
import os
import sys
from PyInstaller.utils.hooks import (collect_data_files,
                                     collect_dynamic_libs,
                                     collect_submodules)

ROOT = SPECPATH            # folder containing this spec file

hidden = []
hidden += collect_submodules("app")             # loaded lazily by menus/CLI
hidden += collect_submodules("pyhanko")
hidden += collect_submodules("pyhanko_certvalidator")
hidden += collect_submodules("asn1crypto")
hidden += collect_submodules("ezdxf")      # DXF import/export
hidden += collect_submodules("pptx")       # PowerPoint export
hidden += collect_submodules("modulor")    # Generate Set drawing kernel
hidden += collect_submodules("shapely")    # envelope / site takeoff geometry
hidden += ["manifold3d"]
hidden += ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
           "PySide6.QtPrintSupport", "PySide6.QtNetwork"]  # one window
hidden += ["websockets", "websockets.asyncio.client",
           "websockets.asyncio.server", "websockets.legacy.server",
           "websockets.legacy.client"]

datas = []
datas += collect_data_files("pyhanko")
datas += collect_data_files("pyhanko_certvalidator")
datas += collect_data_files("pptx")        # its default slide template
# the phone web app served by the relay
datas += [(os.path.join(ROOT, "app", "collab", "web"),
           os.path.join("app", "collab", "web"))]
# the icons and splash are optional: a source snapshot without them still
# builds (the live folder has them)
if os.path.exists(os.path.join(ROOT, "icon.png")):  # window icon
    datas += [(os.path.join(ROOT, "icon.png"), ".")]
if os.path.exists(os.path.join(ROOT, "splash.png")):  # startup splash
    datas += [(os.path.join(ROOT, "splash.png"), ".")]
if os.path.exists(os.path.join(ROOT, "icon.ico")):  # sharp taskbar icon
    datas += [(os.path.join(ROOT, "icon.ico"), ".")]
datas += [(os.path.join(ROOT, "app", "data"), os.path.join("app", "data"))]

# research briefs, reviews, notes for Claude, private/ and Xactimate /
# SageSure / EagleView material must never ship (review 0.12.35 #21):
# stop the build if any is in what this spec packages
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ship_check                                    # noqa: E402
_ship = []
for _src, _dest in datas:
    if not os.path.abspath(_src).startswith(os.path.abspath(ROOT)):
        continue                                     # third-party data
    if os.path.isdir(_src):
        for _base, _dirs, _files in os.walk(_src):
            _ship += [os.path.join(_dest, os.path.relpath(
                os.path.join(_base, _f), _src)) for _f in _files]
    else:
        _ship.append(os.path.join(_dest, os.path.basename(_src)))
for _base, _dirs, _files in os.walk(os.path.join(ROOT, "app")):
    _ship += [os.path.relpath(os.path.join(_base, _f), ROOT) for _f in _files]
ship_check.require_clean(_ship, "quantisheet.spec")
# nor any licensed, local-only price data (Import Your Own Price List)
ship_check.require_no_local_only(os.path.join(ROOT, "app", "data"),
                                 "quantisheet.spec")

icon_file = os.path.join(ROOT, "icon.ico")
if sys.platform == "darwin":
    icon_file = None        # PyInstaller wants .icns on macOS; skip it
elif not os.path.exists(icon_file):
    icon_file = None

a = Analysis(
    [os.path.join(ROOT, "quantisheet.py")],
    pathex=[ROOT],
    # manifold3d's wheel carries its own MSVC runtime DLL (Grok M11)
    binaries=collect_dynamic_libs("manifold3d"),
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "IPython", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtQuick",
        # ClaimIT is a separate program with its own spec
        # (quantisheet_claims.spec); QuantiSheet only starts it as a process
        "quantisheet_claims",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QuantiSheet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX breaks Qt libraries and trips antivirus
    console=False,          # the launcher attaches to a terminal for CLI use
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
    version=os.path.join(ROOT, "installer", "version_info.txt")
    if os.path.exists(os.path.join(ROOT, "installer", "version_info.txt"))
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="QuantiSheet",
)
