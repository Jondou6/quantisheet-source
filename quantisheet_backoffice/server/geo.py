"""Geofence distance (P2-08). Not money: plain floats are fine here."""
from __future__ import annotations

import math

EARTH_M = 6_371_000


def distance_m(lat1, lon1, lat2, lon2) -> int:
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = p2 - p1
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * \
        math.sin(dl / 2) ** 2
    return int(round(2 * EARTH_M * math.asin(math.sqrt(a))))


def check(fence, lat, lon) -> tuple[int | None, bool | None]:
    """(distance in m, inside?) or (None, None) without a fence or fix."""
    if not fence or fence.get("lat") in (None, "") or lat in (None, ""):
        return None, None
    d = distance_m(fence["lat"], fence["lon"], lat, lon)
    return d, d <= int(fence["radius_m"])
