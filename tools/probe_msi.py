"""What this PC has for building an MSI (read-only): WiX v3 / v4+,
the .NET SDK, and Inno Setup.

    python tools/probe_msi.py
"""
import glob
import os
import shutil
import subprocess


def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (p.stdout + p.stderr).strip()[:400]
    except (OSError, subprocess.SubprocessError) as e:
        return f"(not found: {e.__class__.__name__})"


def main():
    print("wix on PATH:", shutil.which("wix"))
    print("wix --version:", run(["wix", "--version"]))
    print("candle (WiX 3) on PATH:", shutil.which("candle"))
    pf = [os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
          os.environ.get("ProgramFiles", r"C:\Program Files")]
    for base in pf:
        for hit in glob.glob(os.path.join(base, "WiX Toolset*", "bin",
                                          "candle.exe")):
            print("WiX 3 found:", hit)
    tools = os.path.join(os.environ.get("USERPROFILE", ""), ".dotnet",
                         "tools", "wix.exe")
    print("dotnet global tool wix:", os.path.exists(tools), tools)
    print("dotnet on PATH:", shutil.which("dotnet"))
    print("dotnet --list-sdks:", run(["dotnet", "--list-sdks"]))
    for base in pf:
        for hit in glob.glob(os.path.join(base, "Inno Setup*", "ISCC.exe")):
            print("Inno Setup:", hit)
    print("msiexec:", shutil.which("msiexec"))


if __name__ == "__main__":
    main()
