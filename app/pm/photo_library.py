"""Project photos: albums, tags, pins on a sheet and a timeline (P1:
"photos grouped by date/area/tag; pin on A-102; filter by tag; no GPS
sent anywhere").

Every photo already attached to a Daily Log, Punch item, Observation or
Inspection is in the library - nothing is copied or moved. Tags and pins
are kept in the job's settings ("photo_meta"), keyed by the photo's
SHA-256, so they follow the photo to every record that shows it. Albums
are views: by date taken, by area (the record's location / area, else
"No area"), by tag. A photo's GPS stays inside the file: it is never
read out, shown or sent."""
import os

SOURCES = ("daily", "punch", "observation", "inspection")
SETTING = "photo_meta"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff",
             ".webp", ".bmp")


def _key(ref):
    if isinstance(ref, dict):
        return ref.get("sha256") or ref.get("name") or ""
    return str(ref or "")


def _is_image(ref):
    ext = (ref.get("ext") or os.path.splitext(ref.get("name") or "")[1]
           or "").lower()
    return ext in IMAGE_EXT


def _meta(store):
    m = store.setting(SETTING) or {}
    return m if isinstance(m, dict) else {}


def _area(rec):
    for k in ("location", "area", "room", "level"):
        v = str(rec.get(k) or "").strip()
        if v:
            return v
    return ""


def photos(store):
    """[{key, ref, coll, record, no, date, area, tags, pin, caption}] -
    one row per photo (a photo shown on two records is listed once, with
    the first record)."""
    meta = _meta(store)
    seen, out = set(), []
    for coll in SOURCES:
        for r in store.list(coll):
            for ref in r.get("photos") or []:
                if not isinstance(ref, dict) or not _is_image(ref):
                    continue
                k = _key(ref)
                if not k or k in seen:
                    continue
                seen.add(k)
                m = meta.get(k) or {}
                out.append({"key": k, "ref": ref, "coll": coll,
                            "record": r.get("_id"), "no": r.get("_no"),
                            "date": str(m.get("taken") or r.get("date") or
                                        r.get("_created") or "")[:10],
                            "area": m.get("area") or _area(r),
                            "tags": list(m.get("tags") or []),
                            "pin": m.get("pin"),
                            "caption": m.get("caption") or
                            ref.get("caption") or ""})
    out.sort(key=lambda p: (p["date"] or "9999", p["no"] or ""))
    return out


def _save(store, key, **values):
    meta = dict(_meta(store))
    m = dict(meta.get(key) or {})
    for k, v in values.items():
        if v in (None, "", []):
            m.pop(k, None)
        else:
            m[k] = v
    if m:
        meta[key] = m
    else:
        meta.pop(key, None)
    store.set_setting(SETTING, meta)


def set_tags(store, key, tags):
    clean = []
    for t in tags or []:
        t = " ".join(str(t).split())[:40]
        if t and t.lower() not in {c.lower() for c in clean}:
            clean.append(t)
    _save(store, key, tags=clean)
    return clean


def set_area(store, key, area):
    _save(store, key, area=" ".join(str(area or "").split())[:80])


def pin(store, key, sheet, page, x, y, looking=""):
    """Pin a photo on a drawing sheet (number, page index, x/y in PDF
    points); `looking` the view direction (N, NE ... NW) if known."""
    _save(store, key, pin={"sheet": str(sheet), "page": int(page),
                           "x": float(x), "y": float(y),
                           "looking": str(looking or "")})


def unpin(store, key):
    _save(store, key, pin=None)


def albums(store, by="date"):
    """{album name: [photos]} - by "date" (taken), "area" or "tag" (a
    photo with two tags is in both)."""
    out = {}
    for p in photos(store):
        if by == "tag":
            for t in p["tags"] or ["No tag"]:
                out.setdefault(t, []).append(p)
        elif by == "area":
            out.setdefault(p["area"] or "No area", []).append(p)
        else:
            out.setdefault(p["date"] or "No date", []).append(p)
    return dict(sorted(out.items()))


def with_tag(store, tag):
    t = str(tag or "").lower()
    return [p for p in photos(store) if t in {x.lower() for x in p["tags"]}]


def on_sheet(store, sheet):
    s = str(sheet or "").upper()
    return [p for p in photos(store)
            if p["pin"] and str(p["pin"].get("sheet", "")).upper() == s]


def timeline(store):
    """[(date, n photos)] oldest first."""
    return [(d, len(ps)) for d, ps in albums(store, "date").items()]
