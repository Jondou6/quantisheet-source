"""Download PNNL's "Guide to Determining Climate Zone by County: Building
America and IECC 2021 Updates" (US DOE / OSTI) into data/energy/ and pull
out its page text. Only this address is fetched (approved by Jon
2026-10-20)."""
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

URL = "https://www.osti.gov/servlets/purl/1893981/"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "data", "energy")
PDF = os.path.join(OUT, "climate-zone-by-county-2021.pdf")
MAX = 60 * 1024 * 1024


def main():
    os.makedirs(OUT, exist_ok=True)
    if "--extract-only" not in sys.argv:
        req = urllib.request.Request(URL, headers={"User-Agent":
                                                   "QuantiSheet"})
        with urllib.request.urlopen(req, timeout=120) as r:
            host = urllib.parse.urlparse(r.geturl()).hostname or ""
            if not (host == "osti.gov" or host.endswith(".osti.gov")):
                raise SystemExit("redirected off osti.gov: " + r.geturl())
            data = r.read(MAX + 1)
        if len(data) > MAX or not data.startswith(b"%PDF"):
            raise SystemExit(f"not a PDF ({len(data)} bytes): "
                             f"{data[:80]!r}")
        with open(PDF + ".part", "wb") as f:
            f.write(data)
        os.replace(PDF + ".part", PDF)
        print("saved", PDF, len(data), "bytes sha256",
              hashlib.sha256(data).hexdigest())
    import fitz
    with fitz.open(PDF) as d:
        pages = [p.get_text("text") for p in d]
    with open(os.path.join(OUT, "pages.json"), "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False)
    print("pages", len(pages), "chars", sum(map(len, pages)))


if __name__ == "__main__":
    main()
