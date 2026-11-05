"""Run installer/it/Detect-QuantiSheet.ps1 (read-only) a few ways and show
what Intune would see: exit code and standard output.

    python tools/check_detect.py
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS1 = os.path.join(ROOT, "installer", "it", "Detect-QuantiSheet.ps1")
PS32 = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "SysWOW64",
                    "WindowsPowerShell", "v1.0", "powershell.exe")


def run(args, exe="powershell"):
    p = subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", PS1] + args, capture_output=True,
                       text=True, timeout=60)
    return p.returncode, p.stdout.strip(), p.stderr.strip()[:200]


def main():
    from app import __version__
    cases = [("installed version", [], "powershell"),
             ("this version", ["-MinimumVersion", __version__], "powershell"),
             ("a later version", ["-MinimumVersion", "99.0.0"], "powershell"),
             ("bad version", ["-MinimumVersion", "beta"], "powershell"),
             ("server only", ["-Edition", "Server"], "powershell"),
             ("32-bit PowerShell", ["-MinimumVersion", __version__], PS32)]
    for name, args, exe in cases:
        if exe != "powershell" and not os.path.exists(exe):
            print(f"{name}: (no 32-bit PowerShell here)")
            continue
        code, out, err = run(args, exe)
        print(f"{name}: exit {code}, detected={bool(out)!s:5} {out!r} "
              f"{err!r}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ROOT)
    main()
