"""Why would a browser be refused when it saves a file on this PC?
Read-only: Windows' Controlled folder access setting, what it blocked in
the last two hours (program and folder only), and free disk space."""
import re
import shutil
import subprocess
import winreg


def main():
    try:
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows Defender\Windows Defender "
                r"Exploit Guard\Controlled Folder Access") as k:
            v = winreg.QueryValueEx(k, "EnableControlledFolderAccess")[0]
        print("Controlled folder access:", {0: "off", 1: "ON (blocks)",
                                            2: "audit only"}.get(v, v))
    except OSError as e:
        print("Controlled folder access: not set / unreadable", e.winerror)
    q = ("*[System[(EventID=1123 or EventID=1124 or EventID=1127) and "
         "TimeCreated[timediff(@SystemTime) <= 7200000]]]")
    r = subprocess.run(
        ["wevtutil", "qe", "Microsoft-Windows-Windows Defender/Operational",
         "/q:" + q, "/f:text", "/c:12", "/rd:true"],
        capture_output=True, text=True, errors="replace")
    text = r.stdout or r.stderr
    n = 0
    for ln in text.splitlines():
        ln = ln.strip()
        if re.match(r"(Date|Process Name|Path|Event ID)\b", ln, re.I):
            ln = re.sub(r"\\Users\\[^\\]+", r"\\Users\\<user>", ln)
            print("  ", ln[:200])
            n += 1
    print("blocked-write events in the last 2 hours:",
          text.count("Event[") if n else 0, "| wevtutil exit", r.returncode,
          (r.stderr or "").strip()[:120])
    free = shutil.disk_usage("C:\\").free / 2 ** 30
    print(f"free on C: {free:.1f} GB")


if __name__ == "__main__":
    main()
