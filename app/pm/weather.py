"""Daily-log weather from Open-Meteo: the day's high, low, rain, sky and
wind for the job site's town.

By default the free servers (no account; Open-Meteo's terms allow them for
non-commercial use only). With an Open-Meteo commercial API key in the
settings ("weather_api_key") every request goes to the matching customer
server instead (api.open-meteo.com -> customer-api.open-meteo.com,
archive-api -> customer-archive-api, geocoding-api ->
customer-geocoding-api) with &apikey=... The key never appears in an
error message."""
import json
import urllib.parse
import urllib.error
import urllib.request
from datetime import date, timedelta
from ..dmoney import c2 as _c2

SKY = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
       45: "Fog", 48: "Fog", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
       56: "Freezing drizzle", 57: "Freezing drizzle", 61: "Rain",
       63: "Rain", 65: "Heavy rain", 66: "Freezing rain",
       67: "Freezing rain", 71: "Snow", 73: "Snow", 75: "Heavy snow",
       77: "Snow", 80: "Showers", 81: "Showers", 82: "Heavy showers",
       85: "Snow showers", 86: "Snow showers", 95: "Thunderstorms",
       96: "Thunderstorms", 99: "Thunderstorms"}
_places = {}


def _api_key():
    try:
        # kept DPAPI-protected (threat model T-014); a plain key from an
        # older version is protected the first time it is read
        from .. import secretstore
        return (secretstore.get_secret("weather_api_key") or "").strip()
    except Exception:                       # no settings (scripts)
        return ""


def source_label():
    """Which weather service is in use, for the user."""
    if _api_key():
        return "Open-Meteo commercial API (your API key)"
    return "Open-Meteo free API (non-commercial use only)"


def _url(base, params):
    """base?params - on the customer server with the key when a commercial
    key is set, else the free server unchanged."""
    key = _api_key()
    if key:
        p = urllib.parse.urlsplit(base)
        if not p.netloc.startswith("customer-"):
            p = p._replace(netloc="customer-" + p.netloc)
        base = urllib.parse.urlunsplit(p)
        params = dict(params, apikey=key)
    return base + "?" + urllib.parse.urlencode(params)


def _get(url):
    from .. import policy
    policy.check("weather", url)
    req = urllib.request.Request(url, headers={"User-Agent": "QuantiSheet"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _split_place(place):
    """'Columbia, MO' / 'Columbia,MO, USA' / 'Columbia MO' /
    'Columbia Maryland' / 'Columbia South Carolina' -> ('Columbia', 'mo')
    etc.; the second part lowercased, "" when none. Without a comma the
    trailing two words, then the trailing word, are tried against US state
    names and postal codes (two first, so 'West Virginia' isn't read as
    'Virginia')."""
    parts = [p.strip() for p in place.split(",")]
    if len(parts) > 1:
        return parts[0], parts[1].lower()
    words = place.split()
    for n in (2, 1):
        if len(words) > n:
            tail = " ".join(words[-n:]).lower()
            if tail in _STATE_CODES or (n == 1 and tail in _STATE_NAMES):
                return " ".join(words[:-n]), tail
    return place.strip(), ""


def _matches(hit, want):
    """Does a geocoding hit fit the state / region the user typed? A US
    postal code or state name matches admin1 exactly (Open-Meteo gives the
    full state name, plus country_code); anything else (a province, a
    country) by admin1 / country prefix."""
    admin = (hit.get("admin1") or "").strip().lower()
    cc = (hit.get("country_code") or "").strip().lower()
    state = _STATE_NAMES.get(want) or (want if want in _STATE_CODES else "")
    if state:
        return admin == state and cc in ("", "us")
    country = (hit.get("country") or "").strip().lower()
    return bool(want) and (admin.startswith(want) or cc == want or
                           country.startswith(want))


def locate(place):
    """'Aiken, SC' -> (lat, lon, label)."""
    if place in _places:
        return _places[place]
    name, want = _split_place(place)
    res = _get(_url("https://geocoding-api.open-meteo.com/v1/search",
                    {"name": name, "count": 10, "language": "en",
                     "format": "json"}))
    hits = res.get("results") or []
    best = next((h for h in hits if want and _matches(h, want)), None)
    if best is None and "," not in place and name != place.strip():
        # 'Fort Washington' / 'Lake Michigan': the trailing word looked
        # like a state but no hit is in it -> search the whole name.
        res = _get(_url("https://geocoding-api.open-meteo.com/v1/search",
                        {"name": place.strip(), "count": 10,
                         "language": "en", "format": "json"}))
        hits = res.get("results") or hits
    if not hits:
        raise ValueError(f"Couldn't find '{place}'. Try 'Town, ST'.")
    if best is None:
        best = hits[0]
    out = (best["latitude"], best["longitude"],
           f"{best['name']}, {best.get('admin1', '')}")
    _places[place] = out
    return out


# US states + DC: postal code -> name, and back
_STATE_NAMES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas",
    "ca": "california", "co": "colorado", "ct": "connecticut",
    "de": "delaware", "dc": "district of columbia", "fl": "florida",
    "ga": "georgia", "hi": "hawaii", "id": "idaho", "il": "illinois",
    "in": "indiana", "ia": "iowa", "ks": "kansas", "ky": "kentucky",
    "la": "louisiana", "me": "maine", "md": "maryland",
    "ma": "massachusetts", "mi": "michigan", "mn": "minnesota",
    "ms": "mississippi", "mo": "missouri", "mt": "montana",
    "ne": "nebraska", "nv": "nevada", "nh": "new hampshire",
    "nj": "new jersey", "nm": "new mexico", "ny": "new york",
    "nc": "north carolina", "nd": "north dakota", "oh": "ohio",
    "ok": "oklahoma", "or": "oregon", "pa": "pennsylvania",
    "ri": "rhode island", "sc": "south carolina", "sd": "south dakota",
    "tn": "tennessee", "tx": "texas", "ut": "utah", "vt": "vermont",
    "va": "virginia", "wa": "washington", "wv": "west virginia",
    "wi": "wisconsin", "wy": "wyoming"}
_STATE_CODES = {v: k for k, v in _STATE_NAMES.items()}
_STATES = _STATE_CODES                   # name -> code (older name)


def _abbr(state):
    """'missouri' -> 'mo'; '' for anything that isn't a US state or DC."""
    return _STATE_CODES.get((state or "").strip().lower(), "")


def daily(place, day=None):
    day = day or date.today().isoformat()
    lat, lon, label = locate(place)
    past = day < date.today().isoformat()
    base = ("https://archive-api.open-meteo.com/v1/archive" if
            past and (date.today() - date.fromisoformat(day)).days > 5
            else "https://api.open-meteo.com/v1/forecast")
    q = {"latitude": lat, "longitude": lon, "start_date": day,
         "end_date": day, "timezone": "auto",
         "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                  "weather_code,wind_speed_10m_max",
         "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
         "precipitation_unit": "inch"}
    d = _get(_url(base, q)).get("daily") or {}

    def first(k):
        v = (d.get(k) or [None])[0]
        return v
    hi, lo = first("temperature_2m_max"), first("temperature_2m_min")
    if hi is None:
        raise ValueError(f"No weather for {day} yet.")
    return {"high": f"{hi:.0f}", "low": f"{lo:.0f}",
            "precip": f"{_c2(first('precipitation_sum') or 0):.2f}",
            "sky": SKY.get(first("weather_code"), ""),
            "wind": f"{first('wind_speed_10m_max') or 0:.0f}",
            "source": f"Open-Meteo, {label}"}


def summary(w):
    if not w:
        return ""
    if isinstance(w, str):
        return w
    parts = []
    if w.get("high") or w.get("low"):
        parts.append(f"{w.get('high', '?')}/{w.get('low', '?')}°F")
    if w.get("sky"):
        parts.append(w["sky"])
    try:
        if float(w.get("precip") or 0) > 0:
            parts.append(f"{w['precip']} in rain")
    except ValueError:
        pass
    if w.get("wind"):
        parts.append(f"wind {w['wind']} mph")
    return ", ".join(parts)


# ---- Weekly Owner Report: 10-day forecast and rainfall history ----------

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ARCHIVE_LAG = 5          # the archive runs ~5 days behind; newer -> forecast
_UNITS = {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
          "precipitation_unit": "inch", "timezone": "auto"}


class WeatherError(ValueError):
    """Weather couldn't be fetched; the text says why, for the user."""


def _iso(d):
    return d if isinstance(d, str) else d.isoformat()


def _fetch(base, params):
    """_get() with errors a user can act on (the IT-policy block passes
    through as is - its text already says what to do)."""
    url = _url(base, params)
    try:
        return _get(url)
    except urllib.error.HTTPError as e:
        try:
            why = json.loads(e.read().decode("utf-8")).get("reason") or ""
        except Exception:
            why = ""
        raise WeatherError(f"Open-Meteo refused the weather request "
                           f"(HTTP {e.code}){': ' + why if why else ''}."
                           ) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        why = getattr(e, "reason", e)
        raise WeatherError("Couldn't reach the weather service "
                           "(Open-Meteo) - check the internet connection "
                           f"and try again. ({why})") from e
    except ValueError as e:                     # not JSON
        raise WeatherError("The weather service sent back something "
                           "unreadable - try again later.") from e


def _where(place):
    try:
        return locate(place)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise WeatherError("Couldn't reach the weather service "
                           "(Open-Meteo) to find "
                           f"'{place}' - check the internet connection. "
                           f"({getattr(e, 'reason', e)})") from e


def _num(v, nd=0):
    if v is None:
        return None
    return round(float(v), nd) if nd else int(round(float(v)))


def _rows(d, keys):
    days = d.get("time") or []
    cols = {k: (d.get(k) or []) for k in keys}
    out = []
    for i, day in enumerate(days):
        out.append((day, {k: (c[i] if i < len(c) else None)
                          for k, c in cols.items()}))
    return out


def forecast(place, days=10):
    """Daily forecast from today: [{"date": "YYYY-MM-DD", "sky": "Rain",
    "high": 78, "low": 60 (F, int), "rain_chance": 40 (%, int),
    "rain_in": 0.12 (inches, 2 dp), "wind": 9 (max mph, int)}].
    A value Open-Meteo doesn't give is None. Raises WeatherError."""
    days = max(1, min(int(days), 16))           # Open-Meteo's limit
    lat, lon, _label = _where(place)
    keys = ("temperature_2m_max", "temperature_2m_min", "precipitation_sum",
            "precipitation_probability_max", "weather_code",
            "wind_speed_10m_max")
    d = _fetch(FORECAST_URL, dict(latitude=lat, longitude=lon,
                                  forecast_days=days, daily=",".join(keys),
                                  **_UNITS)).get("daily") or {}
    out = []
    for day, v in _rows(d, keys)[:days]:
        out.append({"date": day,
                    "sky": SKY.get(v["weather_code"], ""),
                    "high": _num(v["temperature_2m_max"]),
                    "low": _num(v["temperature_2m_min"]),
                    "rain_chance": _num(v["precipitation_probability_max"]),
                    "rain_in": _num(v["precipitation_sum"], 2),
                    "wind": _num(v["wind_speed_10m_max"])})
    if not out:
        raise WeatherError(f"No forecast for '{place}' right now - "
                           "try again later.")
    return out


def history(place, start, end):
    """Recorded daily weather, start..end inclusive (dates or ISO strings;
    end is clipped to today): [{"date": "YYYY-MM-DD", "rain_in": 0.45,
    "high": 81, "low": 66}]. Days older than ~5 days come from the
    Open-Meteo archive, the last few from the forecast service's recent
    past. Days without data yet are left out. Raises WeatherError."""
    s, e = date.fromisoformat(_iso(start)), date.fromisoformat(_iso(end))
    today = date.today()
    e = min(e, today)
    if s > e:
        raise WeatherError(f"No weather history for {_iso(start)} to "
                           f"{_iso(end)} - the start is after the end (or "
                           "in the future).")
    lat, lon, _label = _where(place)
    keys = ("temperature_2m_max", "temperature_2m_min", "precipitation_sum")
    cut = today - timedelta(days=ARCHIVE_LAG)   # archive covers <= cut
    spans = []
    if s <= cut:
        spans.append((ARCHIVE_URL, s, min(e, cut)))
    if e > cut:
        spans.append((FORECAST_URL, max(s, cut + timedelta(days=1)), e))
    found = {}
    for base, a, b in spans:
        d = _fetch(base, dict(latitude=lat, longitude=lon,
                              start_date=a.isoformat(),
                              end_date=b.isoformat(),
                              daily=",".join(keys), **_UNITS)
                   ).get("daily") or {}
        for day, v in _rows(d, keys):
            if v["temperature_2m_max"] is None and \
                    v["precipitation_sum"] is None:
                continue                         # not recorded yet
            found[day] = {"date": day,
                          "rain_in": _num(v["precipitation_sum"], 2),
                          "high": _num(v["temperature_2m_max"]),
                          "low": _num(v["temperature_2m_min"])}
    return [found[k] for k in sorted(found)]
