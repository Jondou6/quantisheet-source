"""Read-only: what this PC has for a "QuantiSheet" printer.

    python tools/printer_probe.py

Is this process elevated, is the Microsoft Print To PDF driver installed,
which printers and ports exist, and is Windows protected print mode on.
Changes nothing.
"""
import ctypes
import subprocess


def ps(cmd):
    p = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=120)
    return (p.stdout + p.stderr).strip()


def main():
    try:
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as e:                                # noqa: BLE001
        admin = f"unknown ({e})"
    print("elevated:", admin)
    print("drivers:", ps("Get-PrinterDriver | Select-Object -Expand Name"))
    print("printers:", ps("Get-Printer | ForEach-Object { $_.Name + ' -> ' "
                          "+ $_.DriverName + ' @ ' + $_.PortName }"))
    print("ports:", ps("Get-PrinterPort | Select-Object -Expand Name"))
    print("spooler:", ps("(Get-Service Spooler).Status"))
    print("protected print mode:", ps(
        "Get-ItemProperty 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows NT"
        "\\Printers\\WPP' -ErrorAction SilentlyContinue | Out-String"))
    print("windows:", ps("(Get-CimInstance Win32_OperatingSystem).Caption + "
                         "' ' + (Get-CimInstance Win32_OperatingSystem)"
                         ".BuildNumber"))


if __name__ == "__main__":
    main()
