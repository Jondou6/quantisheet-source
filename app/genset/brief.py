"""Brief text -> form fields. A regex pass first; then, if the local AI is
up, it may fill project fields and the room program only. Form fields
always win. Nothing here places geometry."""
import json
import logging
import re
import threading
import urllib.request

log = logging.getLogger(__name__)

def _registry():
    from . import types
    return types


TYPES = tuple(_registry().keys())            # the building types (types/)
OCCUPANCIES = tuple(_registry().occupancies())
AI_TIMEOUT = 60


def _host():
    try:
        from .. import policy
        from ..ai import review
        return policy.get("AIHost") or review.HOST
    except Exception:                                     # noqa: BLE001
        import os
        return os.environ.get("QUANTISHEET_OLLAMA_HOST",
                              "http://localhost:11434")


def ai_up(timeout=2):
    """Is the local AI answering? (a 2 s check of /api/tags)"""
    from .. import policy
    if not policy.allowed("ai"):
        return False
    try:
        from ..ai.review import _opener
        with _opener().open(_host().rstrip("/") + "/api/tags",
                            timeout=timeout) as r:
            return r.status == 200
    except Exception:                                     # noqa: BLE001
        return False


def ai_model():
    try:
        from ..ai import review
        return review.MODEL
    except Exception:                                     # noqa: BLE001
        return None


_UNIT = r"(?:sf|s\.f\.|sq\.?\s*ft|square\s*feet|sqft|ft2|ft²)\b"
_NUM = r"(\d[\d,]*(?:\.\d+)?(?:e\d+)?)"
_SF = re.compile(_NUM + r"\s*" + _UNIT, re.I)
_BED = re.compile(r"(\d+)\s*(?:-|\s)?(?:bed(?:room)?s?|br|bd)\b", re.I)
_BATH = re.compile(r"(\d+(?:\.5)?)\s*(?:-|\s)?(?:bath(?:room)?s?|ba)\b",
                   re.I)
_STORY = re.compile(r"\b(one|single|two|three|four|1|2|3|4)[\s-]*"
                    r"(?:stor(?:y|ey|ies|eys)|levels?)\b", re.I)
_TOTAL = re.compile(r"\b(total|gross|overall|about|approx\w*|around|"
                    r"building|footprint|roughly|~)\W*$", re.I)
# "3 bedrooms at 200 sf each", "2 baths 80 sf each"
_EACH = re.compile(r"(\d+)\s+([a-z]+?s?)\s*(?:at|@|of)?\s*" + _NUM +
                   r"\s*" + _UNIT + r"(?:\s*each)?", re.I)
# "living 400 sf", "kitchen: 250 sf", "great room of 500 sf"
_ROOM = re.compile(r"([a-z][a-z ]{1,24}?)\s*(?:at|@|of|:|-|=)?\s*" + _NUM +
                   r"\s*" + _UNIT, re.I)
_HOUSE = r"\b(house|home|ranch|residence|residential|single[\s-]family|" \
         r"cottage|bungalow|cabin|duplex)\b"


def _num(text):
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _room_sizes(t):
    """[(kind, sf, count)] for room sizes written in the brief."""
    from .layout import _kind_of
    out, used = [], []
    for m in _EACH.finditer(t):
        kind = _kind_of(m.group(2))
        sf = _num(m.group(3))
        if kind and sf:
            out.append((kind, sf, int(m.group(1))))
            used.append(m.span())
    for m in _ROOM.finditer(t):
        if any(a <= m.start() < b for a, b in used):
            continue
        words = m.group(1).strip().lower()
        if re.search(r"\b(total|gross|overall|about|approx|around|building|"
                     r"footprint|roughly|house|home|office|store|shop|"
                     r"retail|cottage|ranch)\s*$", words) and \
                not re.search(r"\b(office|bed|bath)\w*\s*$", words.replace(
                    "office building", "")):
            continue
        kind = _kind_of(words.split(",")[-1])
        sf = _num(m.group(2))
        if kind and sf:
            out.append((kind, sf, 1))
    return out


def regex_fields(text):
    from . import site
    lot, t = site.read_lot(text or "")     # "10,000 sf lot" is not the
    f = {"lot": lot} if lot else {}        # building's size
    warn = []
    sizes = _room_sizes(t)
    room_sf = {sf for _k, sf, _c in sizes}
    best, fallback = None, []
    for m in _SF.finditer(t):
        v = _num(m.group(1))
        if v is None:
            continue
        before = t[max(0, m.start() - 30):m.start()]
        if before.rstrip().endswith("-") and not re.search(
                r"\d\s*-\s*$", before):
            warn.append("A negative area in the brief was ignored.")
            continue
        if _TOTAL.search(before) and best is None:
            best = v                       # "total about 1,800 sf"
        elif v not in room_sf:
            fallback.append(v)
    if best is None and fallback:
        best = max(fallback)               # the largest, not the first
    if best is None and sizes:
        best = round(sum(sf * c for _k, sf, c in sizes) / 0.9, -1)
        warn.append(f"No total SF in the brief; {best:,.0f} SF worked out "
                    "from the room sizes - confirm.")
    if best is not None:
        f["gross_sf"] = best
    if sizes:
        f["room_sizes"] = sizes
    # "three bedrooms", "two baths" (Fable review N8)
    t = re.sub(r"\b(one|two|three|four|five|six)(?=[\s-]+(?:bed|bath))",
               lambda m_: str(("one", "two", "three", "four", "five",
                               "six").index(m_.group(1).lower()) + 1), t,
               flags=re.I)
    m = _BED.search(t)
    if m:
        f["beds"] = int(m.group(1))
    m = _BATH.search(t)
    if m:
        f["baths"] = int(float(m.group(1)) + 0.5)
    low = t.lower()
    house = re.search(_HOUSE, low) or "beds" in f
    types = _registry()
    hit = types.detect(t)            # the newer types first (warehouse...)
    if hit:
        f["building_type"], f["occupancy"] = hit[0], hit[1]
        f["type_hits"] = hit[2]
        if hit[0] == "warehouse":
            from .types import warehouse
            f.update(warehouse.read(t))
        else:                        # seats, tenants... (types/*.py read)
            f.update(types.get(hit[0]).run("read", t, default=None) or {})
    elif re.search(r"\b(retail|store|shop|showroom|boutique)\b", low):
        f["building_type"], f["occupancy"] = "small_commercial", "M"
    elif house:                            # "studio cottage" is a house
        f["building_type"], f["occupancy"] = "single_family", "R-3"
    elif re.search(r"\b(office|commercial|clinic|studio)\b", low):
        f["building_type"], f["occupancy"] = "small_commercial", "B"
    m = re.search(r"\b(?:occupancy|group)\s*(R-3|R-1|S-1|F-1|A-2|B|M)\b",
                  t, re.I)
    if m:
        occ = m.group(1).upper()
        # only a group the building type can carry (an R-1 "house" is not
        # a hotel); the original three always applied
        bt = f.get("building_type")
        if occ in ("R-3", "B", "M") or (
                bt and occ in types.get(bt).occupancies):
            f["occupancy"] = occ
    if re.search(r"\b(existing|renovat|remodel|addition|alteration)", low):
        f["work"] = "existing"
    elif re.search(r"\bnew\b", low):
        f["work"] = "new"
    from . import garage as garage_mod, outdoor
    cars = garage_mod.read(t)
    if cars:
        f["garage"] = cars
    f.update(outdoor.read(t))
    m = _STORY.search(t)
    if m:
        n = {"one": 1, "single": 1, "two": 2, "three": 3, "four": 4}.get(
            m.group(1).lower()) or int(m.group(1))
        top = max(2, types.limits(f.get("building_type"))["stories"][1])
        f["stories"] = min(n, top)
        if n > top:
            warn.append("v1 draws up to two stories; drawn as two." if
                        top == 2 else f"v1 draws up to {top} stories; "
                        f"drawn as {top}.")
    if warn:
        f["warnings"] = warn
    return f


def _prompt():
    """The AI's form, its choices from the type registry."""
    types = _registry()
    bts = "|".join(f'"{k}"' for k in types.keys())
    occs = "|".join(f'"{o}"' for o in types.occupancies())
    top = max(max(2, types.limits(k)["stories"][1]) for k in types.keys())
    st = "|".join(str(i) for i in range(1, top + 1))
    return ("Read this building brief and return JSON only, with these "
            "keys (leave out what the brief doesn't say): "
            '{"name": str, "address": str, "building_type": ' + bts +
            ', "occupancy": ' + occs + ', '
            '"work": "new"|"existing", "gross_sf": number, "beds": int, '
            '"baths": int, "stories": ' + st + '}. Brief: ')


PROMPT = _prompt()


_inflight = []           # AI threads that timed out but are still running


def ai_busy():
    """Is an earlier AI call still running? (A timed-out call can't be
    stopped; don't pile another one on top - Venice M-6.)"""
    _inflight[:] = [t for t in _inflight if t.is_alive()]
    return bool(_inflight)


def _ai_fields(text, ask=None, timeout=AI_TIMEOUT, bt_hint=None):
    """(fields, dropped keys) from the local AI. The gross SF and stories
    are checked against the building type's limits: `bt_hint` (the form's
    or the text rules' type) or else the type the AI names."""
    out = {}
    if ask is None and ai_busy():
        return None, "an earlier AI call is still running"

    def run():
        try:
            if ask is not None:
                out["raw"] = ask(PROMPT + text)
            else:
                from ..ai import review
                out["raw"] = review._ollama(PROMPT + text, json_mode=True)
        except Exception as e:                            # noqa: BLE001
            out["err"] = e
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        _inflight.append(th)
    if th.is_alive() or "raw" not in out:
        return None, out.get("err", "timed out")
    try:
        data = json.loads(out["raw"]) if isinstance(out["raw"], str) \
            else dict(out["raw"])
    except Exception as e:                                # noqa: BLE001
        return None, e
    clean, dropped = {}, []
    types = _registry()
    bt = bt_hint or (data.get("building_type") if data.get(
        "building_type") in TYPES else None)
    lim = types.limits(bt or "single_family")
    lo, hi = lim["sf"]
    top = max(2, lim["stories"][1])
    for k, v in data.items():
        if v is None or v == "" or v == [] or v == 0:
            continue                 # the AI left it blank: not an error
        if k in ("name", "address") and isinstance(v, str) and v.strip():
            clean[k] = v.strip()[:80]
        elif k == "building_type" and v in TYPES:
            clean[k] = v
        elif k == "occupancy" and v in OCCUPANCIES:
            clean[k] = v
        elif k == "work" and v in ("new", "existing"):
            clean[k] = v
        elif k == "gross_sf" and isinstance(v, (int, float)) and \
                not isinstance(v, bool) and lo <= v <= hi:
            clean[k] = float(v)
        elif k == "stories" and v in tuple(range(1, top + 1)):
            clean[k] = int(v)
        elif k in ("beds", "baths") and isinstance(v, (int, float)) and \
                0 < v <= 8:
            clean[k] = int(float(v) + 0.5)      # 2.5 baths -> 3, as the
        else:                                      # text rules do
            dropped.append(k)
    # an occupancy that contradicts the building type is ignored (the AI
    # once called a dental office R-3)
    bt, occ = clean.get("building_type"), clean.get("occupancy")
    if occ and bt and occ not in types.get(bt).occupancies:
        clean.pop("occupancy")
    return clean, dropped


def parse(text, form=None, ask=None, use_ai=True):
    """Fields for layout.make_plan: regex, then the AI (if up), then the
    form, which always wins."""
    form = {k: v for k, v in (form or {}).items() if v not in (None, "")}
    f = regex_fields(text)
    warnings = list(f.pop("warnings", []))
    ai_used = False
    if use_ai and (ask is not None or ai_up()):
        got, info = _ai_fields(text or "", ask,
                               bt_hint=form.get("building_type") or
                               f.get("building_type"))
        if got is None:
            warnings.append(("AI busy with an earlier request" if
                             "still running" in str(info) else
                             "AI unavailable") +
                            " — brief parsed from form fields.")
        else:
            ai_used = True
            lot_sf = (f.get("lot") or {}).get("area") or (
                (f.get("lot") or {}).get("w", 0) *
                (f.get("lot") or {}).get("d", 0))
            if "gross_sf" in got and lot_sf and \
                    abs(got["gross_sf"] - lot_sf) < 1:
                got.pop("gross_sf")          # the AI read the lot's size
            if "gross_sf" in got and "gross_sf" not in f:
                if re.search(r"\b(sf|sq|square|ft)", (text or "").lower()):
                    warnings.append("Gross SF read by the local AI - "
                                    "confirm it.")
                else:            # the AI may not make up a size (Grok M4)
                    got.pop("gross_sf")
            for k, v in got.items():
                f.setdefault(k, v)            # the regex pass wins over AI
            if info:
                warnings.append("AI answer had fields out of range; they "
                                "were left out: " + ", ".join(info))
    elif use_ai:
        warnings.append("AI unavailable — brief parsed from form "
                        "fields.")
    f.update(form)
    if "building_type" in form and "occupancy" not in form:
        tp = _registry().get(form["building_type"])
        if form["building_type"] == "single_family":
            f["occupancy"] = "R-3"
        elif f.get("occupancy") not in tp.occupancies:
            f["occupancy"] = tp.default_occ
    if f.get("building_type") == "warehouse" and not f.get("type_hits"):
        from .types import warehouse   # picked by the form or the AI: the
        for k, v in warehouse.read(text or "").items():   # docks, clear
            f.setdefault(k, v)                            # height...
    elif f.get("building_type") in TYPES and not f.get("type_hits"):
        tp = _registry().get(f["building_type"])  # restaurant, strip...
        if tp.read is not None:
            for k, v in (tp.read(text or "") or {}).items():
                f.setdefault(k, v)
    f["brief"] = text or ""
    f["ai_used"] = ai_used
    f["ai_model"] = ai_model() if ai_used else None
    f["warnings"] = warnings + list(f.get("warnings") or [])
    f.setdefault("building_type", "single_family")
    if f["building_type"] == "single_family":
        f.setdefault("occupancy", "R-3")
    f.setdefault("work", "new")
    return f
