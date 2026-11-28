"""Zip the browser add-on for a store upload or to hand to someone:
python tools/pack_extension.py  ->  release/browser/open-in-quantisheet-
<version>.zip, to load or hand to someone. With --store: ...-store.zip, the
copy to upload to the Chrome Web Store and Edge Add-ons (no fixed id in
it; see docs/BROWSER_ADDON_STORE.md). Nothing is published by this."""
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "browser_extension")
KEEP = (".json", ".js", ".html", ".png")

if __name__ == "__main__":
    with open(os.path.join(EXT, "manifest.json"), encoding="utf-8") as f:
        v = json.load(f)["version"]
    out_dir = os.path.join(ROOT, "release", "browser")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"open-in-quantisheet-{v}.zip")
    n = 0
    # --store: the copy for a store upload. A store gives the add-on its
    # own id, so the fixed-id "key" is left out of that copy's manifest.
    store = "--store" in sys.argv[1:]
    if store:
        out = out[:-4] + "-store.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _d, files in os.walk(EXT):
            for name in sorted(files):
                # the viewer (Mozilla's PDF.js) goes in whole, with its
                # licence files
                if name.endswith(KEEP) or os.sep + "pdfjs" in base:
                    p = os.path.join(base, name)
                    rel = os.path.relpath(p, EXT).replace("\\", "/")
                    if store and rel == "manifest.json":
                        with open(p, encoding="utf-8") as f:
                            m = json.load(f)
                        m.pop("key", None)
                        z.writestr(rel, json.dumps(m, indent=2) + "\n")
                        n += 1
                        continue
                    z.write(p, rel)
                    n += 1
    print(out, f"({n} files, {os.path.getsize(out) // 1024} KB)")
