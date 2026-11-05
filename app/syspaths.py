"""Windows' own programs by full path (threat model T-017): a helper
found on PATH or in the current folder could be someone else's program.
"""
import os


def system32(*parts):
    """%SystemRoot%\\System32\\<parts> - SystemRoot from the Windows
    API when it can be read, else the environment, else C:\\Windows."""
    root = None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.kernel32.GetSystemWindowsDirectoryW(buf, 260):
            root = buf.value
    except Exception:                                     # noqa: BLE001
        pass
    root = root or os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(root, "System32", *parts)


def powershell():
    p = system32("WindowsPowerShell", "v1.0", "powershell.exe")
    return p if os.path.exists(p) else "powershell"


def icacls():
    p = system32("icacls.exe")
    return p if os.path.exists(p) else "icacls"
