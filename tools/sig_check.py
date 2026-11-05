"""Read-only: the Authenticode signature of installer files, and the
package identity inside an .msix (Nov 2, for the "For IT Department"
folder). Nothing is changed.

    python tools/sig_check.py FILE [FILE ...]
"""
import hashlib
import os
import re
import subprocess
import sys
import zipfile


def ps_sig(path):
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                       "System32", "WindowsPowerShell", "v1.0",
                       "powershell.exe")
    cmd = ("$s = Get-AuthenticodeSignature -LiteralPath $env:QS_SIG_FILE; "
           "'STATUS=' + $s.Status; 'MESSAGE=' + $s.StatusMessage; "
           "'SIGNER=' + $(if ($s.SignerCertificate) "
           "{ $s.SignerCertificate.Subject } else { '' })")
    env = dict(os.environ, QS_SIG_FILE=path)
    r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command",
                        cmd], capture_output=True, text=True, env=env,
                       timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW",
                                             0))
    return (r.stdout or r.stderr).strip()


def main(paths):
    for p in [a.strip('"') for a in paths]:
        print("==", p)
        if not os.path.isfile(p):
            print("   not found")
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        print("   size", os.path.getsize(p), "sha256", h.hexdigest())
        for line in ps_sig(p).splitlines():
            print("  ", line)
        if p.lower().endswith(".msix"):
            with zipfile.ZipFile(p) as z:
                names = set(z.namelist())
                print("   has AppxSignature.p7x:", "AppxSignature.p7x" in names)
                m = z.read("AppxManifest.xml").decode("utf-8", "replace")
                ident = re.search(r"<Identity[^>]*>", m)
                print("  ", ident.group(0) if ident else "no Identity")


if __name__ == "__main__":
    main(sys.argv[1:])
