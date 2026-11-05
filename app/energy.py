"""Energy code helpers (0.12.27): the climate zone of a US county, and
where to read the energy code.

The county list (app/data/climate_zones_2021.json, tools/climate_index.py)
comes from PNNL-33270, "Guide to Determining Climate Zones by County:
Building America and IECC 2021 Updates" (US Department of Energy, 2022):
3,134 counties with the 2021 IECC zone, the Building America zone and the
zone before 2021 where it changed. The IECC itself is ICC's and isn't
included - read it free on ICC's site, or add your own copy to the Code
Library (app/codelib.py).
"""
import json
import os
import re
import threading

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                    "climate_zones_2021.json")
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida",
    "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming"}
# where to read the code (ICC's free read-only site) and check adoption
LINKS = {
    "IECC 2021 (read free at ICC)":
        "https://codes.iccsafe.org/content/IECC2021V1.0",
    "All I-Codes, every edition (ICC)": "https://codes.iccsafe.org/codes/i-codes",
    "What each state has adopted (US DOE)": "https://www.energycodes.gov/state-portal",
}
MOISTURE = {"A": "Moist", "B": "Dry", "C": "Marine"}
_data = None
_lock = threading.Lock()


def data():
    global _data
    with _lock:
        if _data is None:
            with open(FILE, encoding="utf-8") as f:
                _data = json.load(f)
        return _data


def states():
    return sorted(data()["states"])


def counties(state):
    return sorted(data()["states"].get(_state(state), {}))


def _state(s):
    s = (s or "").strip()
    if s.upper() in STATE_NAMES:
        return s.upper()
    for k, v in STATE_NAMES.items():
        if v.lower() == s.lower():
            return k
    return s.upper()


def _norm(c):
    c = (c or "").lower().replace("saint ", "st. ").replace("st ", "st. ")
    c = re.sub(r"\b(county|parish|borough|census area|city and borough|"
               r"municipality)\b", "", c)
    return re.sub(r"[^a-z0-9]", "", c)


def zone(state, county):
    """{"state", "county", "zone", "ba", "was", "note"} or None."""
    st = _state(state)
    rows = data()["states"].get(st) or {}
    want = _norm(county)
    hit = next((c for c in rows if _norm(c) == want), None)
    if hit is None:
        starts = [c for c in rows if _norm(c).startswith(want)] if want \
            else []
        hit = starts[0] if len(starts) == 1 else None
    if hit is None:
        return None
    r = rows[hit]
    z = r["zone"]
    note = ""
    if z[-1:].isdigit() and z not in ("7", "8"):
        note = ("The guide doesn't print this county's moisture regime "
                "(A, B or C) - check the IECC climate zone map.")
    return {"state": st, "county": hit, "zone": z, "ba": r.get("ba", ""),
            "was": r.get("was"), "note": note,
            "moisture": MOISTURE.get(z[-1:], "")}


def describe(z):
    """'Climate zone 4A (moist) - Building America: Mixed-Humid'."""
    if not z:
        return ""
    s = f"Climate zone {z['zone']}"
    if z["moisture"]:
        s += f" ({z['moisture'].lower()})"
    if z["ba"]:
        s += f" - Building America: {z['ba']}"
    if z["was"] and z["was"] != z["zone"]:
        s += f" - was {z['was']} before the 2021 IECC"
    return s
