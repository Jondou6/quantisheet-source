"""(Re)create the Desktop "QuantiSheet" shortcut for this folder - e.g.
after the folder has been moved."""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ps = (
    "$d=[Environment]::GetFolderPath('Desktop');"
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
    "(Join-Path $d 'QuantiSheet.lnk'));"
    f"$s.TargetPath='{ROOT}\\.venv\\Scripts\\pythonw.exe';"
    f"$s.Arguments='\"{ROOT}\\quantisheet.py\"';"
    f"$s.WorkingDirectory='{ROOT}';"
    f"$s.IconLocation='{ROOT}\\icon.ico';"
    "$s.Description='QuantiSheet';$s.Save();"
    "Write-Output (Join-Path $d 'QuantiSheet.lnk')")
r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", ps], capture_output=True, text=True)
print(r.stdout, r.stderr, "exit", r.returncode)
