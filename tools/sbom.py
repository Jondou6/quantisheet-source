"""Offline SBOM for third-party packages the app bundles.

Reads the requirements files and the PyInstaller specs. Versions and
licenses come from installed package metadata only (importlib.metadata).
Nothing is downloaded.

Writes, next to the build output (default: the release folder from
tools/build_installer.py):

    quantisheet-sbom.cdx.json    CycloneDX 1.5
    quantisheet-sbom.txt          plain-text summary

AGPL, GPL, and an unknown license are flagged in the text file, in the
JSON, and by exit code 2. LGPL alone is not treated as GPL.

    python tools/sbom.py
    python tools/sbom.py --out path\\to\\release
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone

CDX_NAME = "quantisheet-sbom.cdx.json"
TXT_NAME = "quantisheet-sbom.txt"

REQ_FILES = (
    "requirements.txt",
    "quantisheet_backoffice/requirements.txt",
    "quantisheet_claims/requirements.txt",
)
SPEC_FILES = (
    "quantisheet.spec",
    "quantisheet_claims.spec",
)

# Import / spec module -> distribution name. First-party modules are omitted.
_SKIP_TOP = {"app", "quantisheet", "quantisheet_claims"}
_MODULE_DIST = {
    "pyhanko": "pyhanko",
    "pyhanko_certvalidator": "pyhanko-certvalidator",
    "asn1crypto": "asn1crypto",
    "ezdxf": "ezdxf",
    "pptx": "python-pptx",
    "modulor": "modulor",
    "shapely": "shapely",
    "manifold3d": "manifold3d",
    "pyside6": "pyside6",
    "websockets": "websockets",
    "pymupdf": "pymupdf",
    "fitz": "pymupdf",
    "cv2": "opencv-python-headless",
    "pil": "pillow",
    "pillow": "pillow",
    "numpy": "numpy",
    "cryptography": "cryptography",
    "openpyxl": "openpyxl",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "pythoncom": "pywin32",
    "pywintypes": "pywin32",
}

_REQ_LINE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9_.-]*)"
    r"(?:\[[^\]]*\])?"
    r"(?:\s*([^\s;#]+))?"
    r"(?:\s*;\s*(.*))?$"
)
_COLLECT = re.compile(
    r"""collect_(?:submodules|data_files|dynamic_libs)\(\s*["']([^"']+)["']"""
)
_QUOTED = re.compile(r"""["']([A-Za-z_][\w.]*)["']""")
_SPDX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*$")
_VERSION_SRC = re.compile(r"""__version__\s*=\s*["']([^"']+)["']""")


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_out(root=None):
    """The release folder the installer build writes into.

    tools/build_installer.py puts the setup exe in <repo>/release.
    The SBOM sits in that same folder, beside the build output.
    The scratch tree under %LOCALAPPDATA%/QuantiSheetBuild is not used.
    """
    return os.path.join(root or repo_root(), "release")


def norm(name):
    return re.sub(r"[-_.]+", "-", str(name).strip()).lower()


def parse_requirements(text, source):
    found = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "--")):
            continue
        m = _REQ_LINE.match(line)
        if not m:
            continue
        spec = (m.group(2) or "").strip()
        marker = (m.group(3) or "").strip()
        found.append({"name": norm(m.group(1)), "spec": spec,
                      "marker": marker, "source": source})
    return found


def parse_spec(text, source):
    mods = [m.group(1) for m in _COLLECT.finditer(text)]
    lines = text.splitlines()
    capturing = False
    buf = []
    for line in lines:
        if "hidden" in line and "[" in line:
            capturing = True
            buf = [line]
            if line.count("[") <= line.count("]"):
                capturing = False
                mods.extend(_QUOTED.findall("\n".join(buf)))
                buf = []
            continue
        if capturing:
            buf.append(line)
            if "]" in line:
                capturing = False
                mods.extend(_QUOTED.findall("\n".join(buf)))
                buf = []
    found = []
    for mod in mods:
        top = mod.split(".", 1)[0]
        if top in _SKIP_TOP or top.startswith("quantisheet"):
            continue
        dist = _MODULE_DIST.get(top.lower(), norm(top))
        found.append({"name": norm(dist), "spec": "", "marker": "",
                      "source": source})
    return found


def discover(root):
    """Distribution names from the requirements files and the specs."""
    rows = []
    for rel in REQ_FILES:
        path = os.path.join(root, rel)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                rows.extend(parse_requirements(fh.read(), rel))
    for rel in SPEC_FILES:
        path = os.path.join(root, rel)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                rows.extend(parse_spec(fh.read(), rel))
    merged = {}
    for row in rows:
        cur = merged.get(row["name"])
        if cur is None:
            merged[row["name"]] = {
                "name": row["name"],
                "specs": [row["spec"]] if row["spec"] else [],
                "markers": [row["marker"]] if row["marker"] else [],
                "sources": [row["source"]],
            }
            continue
        if row["source"] not in cur["sources"]:
            cur["sources"].append(row["source"])
        if row["spec"] and row["spec"] not in cur["specs"]:
            cur["specs"].append(row["spec"])
        if row["marker"] and row["marker"] not in cur["markers"]:
            cur["markers"].append(row["marker"])
    return [merged[k] for k in sorted(merged)]


def _classifiers(dist):
    meta = getattr(dist, "metadata", None)
    if meta is not None and hasattr(meta, "get_all"):
        return list(meta.get_all("Classifier") or [])
    extra = getattr(dist, "classifiers", None)
    return list(extra or [])


def license_text(dist):
    meta = getattr(dist, "metadata", {}) or {}
    expr = str(meta.get("License-Expression") or "").strip()
    if expr:
        return expr
    lic = str(meta.get("License") or "").strip()
    names = []
    for item in _classifiers(dist):
        text = str(item).strip()
        if text.startswith("License ::"):
            names.append(text.split("::")[-1].strip())
    if lic and len(lic) <= 120 and lic.upper() not in {"UNKNOWN", "NONE"}:
        if names and len(lic) > 60:
            return "; ".join(names)
        return lic
    if names:
        return "; ".join(names)
    if lic:
        first = lic.splitlines()[0].strip()
        return (first[:120] if first else "") or "UNKNOWN"
    return "UNKNOWN"


def loud_license(text):
    """'AGPL', 'GPL', 'UNKNOWN', or '' when the license is fine to list.

    LGPL alone is not GPL. A line that names both LGPL and GPL is GPL,
    except an SPDX choice ("LGPL-3.0-only OR GPL-3.0-only"), which is as
    loud as its mildest option.
    """
    raw = (text or "").strip()
    if not raw or raw.upper() == "UNKNOWN":
        return "UNKNOWN"
    upper = raw.upper()
    # an SPDX choice ("LGPL-3.0-only OR GPL-3.0-only") is as loud as its
    # mildest option: the package may be used under that one
    parts = [p for p in re.split(r"\s+OR\s+", raw) if p.strip()]
    if len(parts) > 1 and all(re.fullmatch(r"[A-Za-z0-9.+-]+", p)
                              for p in parts):
        # SPDX ids only (a prose "or Artifex Commercial License" is not a
        # free option and stays loud)
        opts = [loud_license(p) for p in parts]
        rank = {"": 0, "GPL": 1, "AGPL": 2, "UNKNOWN": 3}
        return min(opts, key=lambda o: rank[o])
    if "AFFERO" in upper or re.search(r"(?<![A-Z])AGPL", upper):
        return "AGPL"
    lesser = "LESSER" in upper or re.search(r"(?<![A-Z])LGPL", upper)
    gpl_token = re.search(r"(?<![A-Z])GPL", upper) is not None
    general = "GENERAL PUBLIC LICENSE" in upper and not lesser
    if gpl_token or general:
        return "GPL"
    return ""


def installed_index():
    out = {}
    for dist in importlib.metadata.distributions():
        name = ""
        try:
            name = dist.metadata["Name"] or ""
        except Exception:
            name = ""
        if name:
            out[norm(name)] = dist
    return out


def _license_object(text):
    if _SPDX.match(text) and text.upper() != "UNKNOWN":
        return {"id": text}
    return {"name": text}


def app_version(root):
    path = os.path.join(root, "app", "__init__.py")
    try:
        with open(path, encoding="utf-8") as fh:
            m = _VERSION_SRC.search(fh.read())
    except OSError:
        return "0"
    return m.group(1) if m else "0"


def build(root, index=None, when=None, serial=None):
    """A CycloneDX document plus the loud-license lines.

    `index` maps a normalized distribution name to an object with
    `.version` and `.metadata` (and optional classifiers). When it is
    omitted, installed distributions are read locally.
    """
    if index is None:
        index = installed_index()
    when = when or datetime.now(timezone.utc).replace(microsecond=0)
    stamp = when.isoformat()
    components = []
    loud = []
    for pkg in discover(root):
        dist = index.get(pkg["name"]) if hasattr(index, "get") else None
        if dist is None:
            version, lic = "UNKNOWN", "UNKNOWN"
        else:
            version = str(getattr(dist, "version", "") or "").strip() or "UNKNOWN"
            lic = license_text(dist) or "UNKNOWN"
        flag = loud_license(lic)
        props = [{"name": "quantisheet:sources",
                  "value": ", ".join(pkg["sources"])}]
        if pkg["specs"]:
            props.append({"name": "quantisheet:requirement",
                          "value": " | ".join(pkg["specs"])})
        if pkg["markers"]:
            props.append({"name": "quantisheet:marker",
                          "value": " | ".join(pkg["markers"])})
        if flag:
            props.append({"name": "quantisheet:license_flag", "value": flag})
            loud.append((flag, pkg["name"], version, lic))
        components.append({
            "type": "library",
            "bom-ref": pkg["name"],
            "name": pkg["name"],
            "version": version,
            "licenses": [{"license": _license_object(lic)}],
            "properties": props,
        })
    loud.sort()
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": serial or f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": stamp,
            "component": {
                "type": "application",
                "name": "quantisheet",
                "version": app_version(root),
            },
            "properties": [
                {"name": "quantisheet:offline",
                 "value": "installed-metadata-only"},
                {"name": "quantisheet:loud_count", "value": str(len(loud))},
            ],
        },
        "components": components,
    }
    return {"document": document, "loud": loud, "components": components}


def summary_text(result):
    lines = [
        "QuantiSheet third-party SBOM",
        "Offline: versions and licenses were read from installed package "
        "metadata only.",
        f"Packages: {len(result['components'])}",
        "",
    ]
    if result["loud"]:
        lines.append("!!! LICENSE WARNING: AGPL/GPL or unknown license.")
        for flag, name, version, lic in result["loud"]:
            lines.append(f"!!! {flag}  {name}  {version}  {lic}")
        lines.append("")
    else:
        lines.append("No AGPL/GPL or unknown licenses.")
        lines.append("")
    lines.append(f"{'':4}{'name':<28} {'version':<16} license  sources")
    for comp in result["components"]:
        lic = comp["licenses"][0]["license"]
        lic_s = lic.get("id") or lic.get("name") or "UNKNOWN"
        sources = ""
        for prop in comp["properties"]:
            if prop["name"] == "quantisheet:sources":
                sources = prop["value"]
        flag = ""
        for prop in comp["properties"]:
            if prop["name"] == "quantisheet:license_flag":
                flag = "!!! "
        lines.append(
            f"{flag:<4}{comp['name']:<28} {comp['version']:<16} {lic_s}  {sources}"
        )
    lines.append("")
    return "\n".join(lines)


def write(out_dir, result):
    os.makedirs(out_dir, exist_ok=True)
    cdx = os.path.join(out_dir, CDX_NAME)
    txt = os.path.join(out_dir, TXT_NAME)
    with open(cdx, "w", encoding="utf-8") as fh:
        json.dump(result["document"], fh, indent=2)
        fh.write("\n")
    with open(txt, "w", encoding="utf-8") as fh:
        fh.write(summary_text(result))
    return cdx, txt


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="repository root (default: this file's repo)")
    ap.add_argument("--out", default=None,
                    help="folder for the SBOM (default: <root>/release, "
                         "beside the installer build output)")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root or repo_root())
    out = os.path.abspath(args.out or default_out(root))
    result = build(root)
    cdx, txt = write(out, result)
    text = summary_text(result)
    sys.stdout.write(text)
    print(cdx)
    print(txt)
    return 2 if result["loud"] else 0


if __name__ == "__main__":
    sys.exit(main())
