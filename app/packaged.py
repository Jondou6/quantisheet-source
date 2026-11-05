"""Running as the Microsoft Store (MSIX) package (0.13.12, the Store
route)?

    is_packaged()      True inside an MSIX package
    old_install()      the uninstaller of a setup.exe / MSI copy also on
                       this PC (two copies side by side), or None
    offer_remove_old(window)
                       once: ask whether to remove that old copy
    open_startup_settings()
                       Settings > Apps > Startup (the Store version's
                       print helper is a startup task the person turns on
                       there - a packaged app's Run-key entry is
                       virtualized and never runs at sign-in)

Nothing here changes anything unless the program runs packaged."""
import os
import sys

APPMODEL_ERROR_NO_PACKAGE = 15700
_CACHE = []


def is_packaged():
    if _CACHE:
        return _CACHE[0]
    out = False
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            n = wintypes.UINT(0)
            rc = ctypes.windll.kernel32.GetCurrentPackageFullName(
                ctypes.byref(n), None)
            out = rc != APPMODEL_ERROR_NO_PACKAGE
        except (AttributeError, OSError):
            out = False
    _CACHE.append(out)
    return out


def old_install():
    """The uninstaller of a standalone (setup / MSI) install, if there is
    one besides this packaged copy."""
    from . import branding
    exe = branding.installed_exe()
    folder = os.path.dirname(exe)
    if not os.path.isfile(exe):
        return None
    for name in ("unins000.exe", "unins001.exe"):
        p = os.path.join(folder, name)
        if os.path.isfile(p):
            return p
    return None


def offer_remove_old(window, ask=None, run=None):
    """Asked once (setting "msix_old_install_asked"): the Store version
    is installed and so is the old one - remove the old copy? Settings
    and data are shared, so nothing is lost. Returns "removed",
    "kept" or None (not packaged / nothing to remove / asked before)."""
    from . import settings
    if not is_packaged() or settings.get("msix_old_install_asked"):
        return None
    unins = old_install()
    if not unins:
        return None
    settings.set("msix_old_install_asked", True)
    if ask is None:
        from PySide6.QtWidgets import QMessageBox
        ask = lambda: QMessageBox.question(  # noqa: E731
            window, "QuantiSheet",
            "An older copy of QuantiSheet (installed with the setup "
            "program) is also on this PC.\n\nRemove it now? Your settings, "
            "jobs and price database are kept - this Store version uses "
            "them.") == QMessageBox.Yes
    if not ask():
        return "kept"
    if run is None:
        import subprocess
        run = lambda p: subprocess.Popen([p])  # noqa: E731
    run(unins)
    return "removed"


def open_startup_settings():
    try:
        os.startfile("ms-settings:startupapps")        # noqa: S606
        return True
    except (AttributeError, OSError):
        return False
