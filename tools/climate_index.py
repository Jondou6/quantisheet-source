"""Build app/data/climate_zones_2021.json - every US county's 2021 IECC
climate zone - from PNNL's "Guide to Determining Climate Zones by County"
(PNNL-33270, US DOE, 2022), page text pulled by tools/fetch_climate.py.

    python tools/climate_index.py [data/energy/pages.json]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "data", "energy", "pages.json")
OUT = os.path.join(HERE, "app", "data", "climate_zones_2021.json")
STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME "
             "MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI "
             "SC SD TN TX UT VT VA WA WV WI WY PR GU VI AS MP".split())
_BA = r"(?:(?:Hot|Mixed)-(?:Humid|Dry)|Very Cold|Cold|Subarctic|Marine)"
_BA_END = re.compile(rf"\s*({_BA})(?:\s*→\s*({_BA}))?\s*$", re.I)
_ZONE = re.compile(r"^(\d)(?:→(\d))?$")
_MOIST = re.compile(r"^(A|B|C|NONE)(?:→(A|B|C|NONE))?$")
_SKIP = re.compile(r"^(State|County|BA Climate|Zone|IECC 2021|Climate|"
                   r"Zone \(1-8\)|Moisture|Regime|Guide to Determining.*|"
                   r"\d{2,3})$")


def _clean(s):
    return re.sub(r"\s+", " ", s.replace("\xa0", " ").replace("‐", "-")
                  .replace("–", "-").replace("\uf0e0", "→")).replace("→ ", "→").strip()


def records(pages):
    lines = []
    for t in pages:
        for ln in t.splitlines():
            ln = _clean(ln)
            if ln and not _SKIP.match(ln):
                lines.append(ln)
    out, cur = [], None
    for ln in lines:
        if ln in STATES:
            if cur:
                out.append(cur)
            cur = [ln]
        elif cur is not None:
            if ln.isupper() and len(ln) > 3 and \
                    ln.replace(" ", "").isalpha() and not _MOIST.match(ln) \
                    and "→" not in ln:
                out.append(cur)                 # "ARIZONA": a state heading
                cur = None
                continue
            cur.append(ln)
    if cur:
        out.append(cur)
    return out


def parse(rec):
    st, rest = rec[0], rec[1:]
    zi = max((i for i, t in enumerate(rest) if _ZONE.match(t)),
             default=None)
    if zi is None:
        return None
    z = _ZONE.match(rest[zi])
    zone = z.group(2) or z.group(1)
    old = z.group(1) if z.group(2) else None
    moist, old_m = "", None
    if zi + 1 < len(rest):
        m = _MOIST.match(rest[zi + 1])
        if m:
            moist = m.group(2) or m.group(1)
            old_m = m.group(1) if m.group(2) else None
    if moist == "NONE":
        moist = ""
    head = re.sub(r"-\s+", "-", " ".join(rest[:zi]))
    m = _BA_END.search(head)
    if not m:
        return None
    county = head[:m.start()].strip()
    county = re.sub(r"\s*\(CA\)$", "", county)
    county = re.sub(r"-\s+", "-", county)
    if not county:
        return None
    ba = (m.group(2) or m.group(1)).title().replace("-H", "-H")
    return {"state": st, "county": county, "zone": zone + moist,
            "ba": ba,
            "was": (f"{old or zone}{(old_m or moist) if (old_m or moist) != 'NONE' else ''}"
                    if (old or old_m) else None)}


def build(src=SRC, out=OUT):
    with open(src, encoding="utf-8") as f:
        pages = json.load(f)
    data, bad = {}, []
    for r in records(pages):
        p = parse(r)
        if p is None:
            bad.append(" | ".join(r)[:120])
            continue
        data.setdefault(p["state"], {})[p["county"]] = {
            k: p[k] for k in ("zone", "ba", "was") if p[k]}
    doc = {"source": "PNNL-33270, Guide to Determining Climate Zones by "
                     "County: Building America and IECC 2021 Updates "
                     "(US Department of Energy, September 2022)",
           "edition": "2021 IECC", "states": data}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=0, sort_keys=True)
    return doc, bad


if __name__ == "__main__":
    doc, bad = build(*(sys.argv[1:2] or [SRC]))
    n = sum(len(v) for v in doc["states"].values())
    print(n, "counties in", len(doc["states"]), "states;", len(bad),
          "unparsed")
    for b in bad[:20]:
        print("  ?", b)
