"""Fetch Mozilla's PDF.js (the browser add-on's viewer is built from it).

    python tools/fetch_pdfjs.py

Downloads one file, pdfjs-<VERSION>-dist.zip, from Mozilla's own GitHub
releases into .work\\pdfjs\\ and prints its size and SHA-256. Nothing is
run. Apache-2.0 licence."""
import hashlib
import os
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "4.10.38"
URL = (f"https://github.com/mozilla/pdf.js/releases/download/v{VERSION}/"
       f"pdfjs-{VERSION}-dist.zip")


def main():
    out = os.path.join(ROOT, ".work", "pdfjs")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, os.path.basename(URL))
    if not os.path.isfile(path):
        req = urllib.request.Request(URL, headers={"User-Agent": "QuantiSheet"})
        with urllib.request.urlopen(req, timeout=120) as r:
            if r.geturl().split("/")[2] not in (
                    "github.com", "objects.githubusercontent.com",
                    "release-assets.githubusercontent.com"):
                raise SystemExit("unexpected host " + r.geturl().split("/")[2])
            data = r.read()
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
    with open(path, "rb") as f:
        data = f.read()
    print(os.path.basename(path), len(data), "bytes, sha256",
          hashlib.sha256(data).hexdigest())
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        tops = sorted({n.split("/")[0] for n in names})
        print(len(names), "files; top level:", tops)
        print("viewer:", [n for n in names if n in (
            "web/viewer.html", "web/viewer.mjs", "build/pdf.mjs",
            "build/pdf.worker.mjs", "LICENSE")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
