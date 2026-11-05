"""Zip the source for the private GitHub repository (read-only on the
working folder): python tools/zip_source.py OUT.zip

Only the program's own source goes in - never the sign-in module, the
unlock-code tool, the sealed contact list, the company mailbox file, keys,
cost books / spreadsheets, vendor copies, reviews or builds."""
import fnmatch
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = ["app", "tests", "tools", "installer", "server", "docs",
        "quantisheet_claims", "quantisheet_backoffice", "data"]
TOP = ["README.md", "build.bat", "build.sh", "claimit_launch.py",
       "icon.ico", "icon.png", "install.bat", "make-tester-key.bat",
       "make_sample.py", "quantisheet.py", "quantisheet.spec",
       "quantisheet_claims.spec", "pyproject.toml", "requirements.txt",
       "run-claims-tests.bat", "run-tests.bat", "splash.png",
       "start-runner.bat", ".gitignore"]
NEVER = ["app/onboard.py", "tools/unlock_code.py",
         "app/data/company_sender.json", "app/data/company_dropbox.json",
         "app/data/contacts.sealed",
         "app/data/build.json", "*.sealed", "*.pem", "*.key", ".env*",
         "*.xlsx", "*.xls", "*.vcf", "*.pst", "*.msi", "*.exe", "*.log",
         "*.pyc", "*/__pycache__/*", "*.orig", "*.bak",
         # the relay server's own data: its secret is made on first start
         # (review 0.13.9 #8)
         "server/data/*"]


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ship_check                                    # noqa: E402


def wanted(rel):
    rel = rel.replace("\\", "/")
    if ship_check.why(rel):       # research, reviews, private/ (#21)
        return False
    return not any(fnmatch.fnmatch(rel, p) or
                   fnmatch.fnmatch(os.path.basename(rel), p) for p in NEVER)


def main(out):
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in TOP:
            p = os.path.join(ROOT, f)
            if os.path.isfile(p) and wanted(f):
                z.write(p, f)
                n += 1
        for d in DIRS:
            for base, dirs, files in os.walk(os.path.join(ROOT, d)):
                dirs[:] = [x for x in dirs if x not in ("__pycache__",)]
                for f in files:
                    p = os.path.join(base, f)
                    rel = os.path.relpath(p, ROOT).replace("\\", "/")
                    if wanted(rel):
                        z.write(p, rel)
                        n += 1
    with zipfile.ZipFile(out) as z:                    # checked, not trusted
        ship_check.require_clean(z.namelist(), "the source zip")
    print(out, n, "files", f"{os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         os.path.join(ROOT, ".run", "source.zip"))
