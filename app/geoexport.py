"""Markups on an aerial photo page -> Google Earth (KML) or GIS (GeoJSON).

An aerial page remembers where it is (its scale entry's "geo": the photo
centre's latitude/longitude and that point on the page). Page points ->
feet east/north of the centre (the page's scale) -> latitude/longitude.
The same flat-earth step the aerial dialog uses, fine over a site."""
import html
import json
import math

from . import annotate

FT_PER_DEG_LAT = 364609.0


def geo_of(doc, pno):
    """The page's location dict, or None if it isn't an aerial page."""
    sc = annotate.read_scales(doc).get(pno) or {}
    g = sc.get("geo")
    if g and sc.get("ppu", 0) > 0 and sc.get("unit", "ft") == "ft":
        return dict(g, ppu=sc["ppu"])
    return None


def _to_lonlat(g, x, y):
    east = (x - g["cx"]) / g["ppu"]
    north = (g["cy"] - y) / g["ppu"]
    lat = g["lat"] + north / FT_PER_DEG_LAT
    lon = g["lon"] + east / (FT_PER_DEG_LAT * math.cos(math.radians(g["lat"])))
    return round(lon, 8), round(lat, 8)


def features(doc, pno):
    """[GeoJSON Feature] for the markups on an aerial page."""
    g = geo_of(doc, pno)
    if g is None:
        raise ValueError("This page isn't an aerial photo page (no location "
                         "is stored with it).")
    page = doc[pno]
    out = []
    for a in page.annots() or []:
        info = a.info or {}
        name = info.get("subject") or info.get("title") or a.type[1]
        props = {"name": name, "kind": a.type[1],
                 "comment": info.get("content", "")}
        verts = a.vertices
        if verts and isinstance(verts[0], (list, tuple)) and \
                isinstance(verts[0][0], (list, tuple)):
            verts = [p for part in verts for p in part]      # ink strokes
        pts = [_to_lonlat(g, p[0], p[1]) for p in (verts or [])]
        r = a.rect
        kind = a.type[0]
        import fitz
        if kind in (fitz.PDF_ANNOT_POLYGON,) and len(pts) >= 3:
            geom = {"type": "Polygon", "coordinates": [pts + [pts[0]]]}
        elif kind in (fitz.PDF_ANNOT_POLY_LINE, fitz.PDF_ANNOT_LINE,
                      fitz.PDF_ANNOT_INK) and len(pts) >= 2:
            geom = {"type": "LineString", "coordinates": pts}
        elif kind in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE):
            ring = [_to_lonlat(g, x, y) for x, y in
                    ((r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1))]
            geom = {"type": "Polygon", "coordinates": [ring + [ring[0]]]}
        else:
            geom = {"type": "Point", "coordinates": list(
                _to_lonlat(g, (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))}
        out.append({"type": "Feature", "geometry": geom,
                    "properties": props})
    return out


def to_geojson(doc, pno, path):
    fc = {"type": "FeatureCollection", "features": features(doc, pno)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=1)
    return len(fc["features"])


def to_kml(doc, pno, path, title="QuantiSheet markups"):
    feats = features(doc, pno)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             f"<name>{html.escape(title)}</name>"]
    for f in feats:
        geom, p = f["geometry"], f["properties"]
        name = html.escape(str(p["name"]))
        desc = html.escape(str(p.get("comment") or ""))

        def cs(points):
            return " ".join(f"{x},{y},0" for x, y in points)
        if geom["type"] == "Point":
            body = f"<Point><coordinates>{cs([geom['coordinates']])}" \
                   "</coordinates></Point>"
        elif geom["type"] == "LineString":
            body = f"<LineString><coordinates>{cs(geom['coordinates'])}" \
                   "</coordinates></LineString>"
        else:
            body = ("<Polygon><outerBoundaryIs><LinearRing><coordinates>"
                    f"{cs(geom['coordinates'][0])}</coordinates></LinearRing>"
                    "</outerBoundaryIs></Polygon>")
        parts.append(f"<Placemark><name>{name}</name>"
                     f"<description>{desc}</description>{body}</Placemark>")
    parts.append("</Document></kml>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return len(feats)
