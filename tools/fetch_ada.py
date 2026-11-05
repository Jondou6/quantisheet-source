"""Download the 2010 ADA Standards for Accessible Design (US DOJ, public
domain) into data/ada/ and pull out its text page by page.

Only this one address is fetched (approved by Jon 2026-10-20)."""
import hashlib
import json
import os
import sys
import urllib.request

URL = "https://www.ada.gov/assets/pdfs/2010-design-standards.pdf"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "data", "ada")
PDF = os.path.join(OUT, "2010-design-standards.pdf")
MAX = 60 * 1024 * 1024


def download():
    os.makedirs(OUT, exist_ok=True)
    req = urllib.request.Request(URL, headers={"User-Agent": "QuantiSheet"})
    with urllib.request.urlopen(req, timeout=120) as r:
        if urllib.request.urlparse(r.geturl()).hostname not in (
                "www.ada.gov", "ada.gov"):
            raise SystemExit("redirected off ada.gov: " + r.geturl())
        data = r.read(MAX + 1)
    if len(data) > MAX:
        raise SystemExit("too big")
    if not data.startswith(b"%PDF"):
        raise SystemExit("not a PDF")
    tmp = PDF + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, PDF)
    print("saved", PDF, len(data), "bytes sha256",
          hashlib.sha256(data).hexdigest())


def extract():
    import fitz
    doc = fitz.open(PDF)
    pages = [p.get_text("text") for p in doc]
    with open(os.path.join(OUT, "pages.json"), "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False)
    print("pages", len(pages), "chars", sum(map(len, pages)))


if __name__ == "__main__":
    if "--extract-only" not in sys.argv:
        download()
    extract()
