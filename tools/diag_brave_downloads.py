"""Where Brave saves downloads on this PC and whether that folder can be
written. Reads two settings only (the download folder, and "ask where to
save"), nothing else from the browser."""
import json
import os
import tempfile


def main():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "BraveSoftware",
                        "Brave-Browser", "User Data")
    for prof in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        p = os.path.join(base, prof, "Preferences")
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f).get("download") or {}
        except (OSError, ValueError) as e:
            print(prof, "unreadable", e)
            continue
        folder = d.get("default_directory") or _downloads()
        home = os.path.expanduser("~")
        print(f"profile {prof}: saves to",
              folder.replace(home, "~"), "| ask where to save:",
              d.get("prompt_for_download"))
        if os.path.isabs(folder):
            for sub in ("", "QuantiSheet"):
                t = os.path.join(folder, sub)
                state = "missing"
                if os.path.isdir(t):
                    try:
                        fd, tmp = tempfile.mkstemp(dir=t, suffix=".qs-test")
                        os.close(fd)
                        os.remove(tmp)
                        state = "exists, writable"
                    except OSError as e:
                        state = f"exists, NOT writable ({e.strerror})"
                elif os.path.exists(t):
                    state = "is a FILE, not a folder"
                print("   ", t.replace(home, "~"), "->", state,
                      "| real name:", _real(t))
                if os.path.isdir(t) and sub:
                    import time
                    names = sorted(os.listdir(t), key=lambda n: -os.path.getmtime(
                        os.path.join(t, n)))[:8]
                    for n in names:
                        st = os.stat(os.path.join(t, n))
                        print("       ", n[:60], st.st_size, "bytes,",
                              int((time.time() - st.st_mtime) / 60),
                              "min ago, read-only" if not os.access(
                                  os.path.join(t, n), os.W_OK) else "min ago")


def _downloads():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft"
                        r"\Windows\CurrentVersion\Explorer"
                        r"\User Shell Folders") as k:
        try:
            v = winreg.QueryValueEx(
                k, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
        except OSError:
            v = r"%USERPROFILE%\Downloads"
    return os.path.expandvars(v)


def _real(t):
    try:
        parent, name = os.path.split(t.rstrip("\\/"))
        for n in os.listdir(parent):
            if n.lower() == name.lower():
                return n
    except OSError:
        pass
    return "-"


if __name__ == "__main__":
    main()
