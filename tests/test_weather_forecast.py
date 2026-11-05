"""Weekly Owner Report weather (app/pm/weather.py forecast() / history()):
Open-Meteo is mocked - canned JSON, no network. Made-up town."""
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import date, timedelta

import pytest

from app import settings
from app.pm import weather


@pytest.fixture(autouse=True)
def _no_user_settings(tmp_path, monkeypatch):
    """No weather API key from the tester's own settings."""
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})

PLACE = "Testville, SC"
GEO = {"results": [
    {"name": "Testville", "latitude": 40.0, "longitude": -100.0,
     "admin1": "Kansas"},
    {"name": "Testville", "latitude": 33.5, "longitude": -81.7,
     "admin1": "South Carolina"}]}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@contextmanager
def open_meteo(handler):
    """Patch urlopen: handler(host, path, query dict) -> JSON-able dict, or
    raises. Yields the list of (host, query) seen."""
    seen = []
    real = urllib.request.urlopen

    def fake(req, timeout=None):
        assert timeout, "every call needs a timeout"
        u = urllib.parse.urlsplit(req.full_url)
        q = dict(urllib.parse.parse_qsl(u.query))
        seen.append((u.hostname, q))
        if u.hostname.startswith("geocoding"):
            return _Resp(json.dumps(GEO).encode())
        return _Resp(json.dumps(handler(u.hostname, u.path, q)).encode())
    urllib.request.urlopen = fake
    weather._places.clear()
    try:
        yield seen
    finally:
        urllib.request.urlopen = real
        weather._places.clear()


def _days(a, b):
    d, out = date.fromisoformat(a), []
    while d <= date.fromisoformat(b):
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def test_forecast_rows_units_and_sky():
    def handler(host, path, q):
        assert host == "api.open-meteo.com" and path == "/v1/forecast"
        n = int(q["forecast_days"])
        days = [(date.today() + timedelta(days=i)).isoformat()
                for i in range(n)]
        return {"daily": {
            "time": days,
            "temperature_2m_max": [78.4, 80.6] + [70.0] * (n - 2),
            "temperature_2m_min": [60.2, 61.5] + [50.0] * (n - 2),
            "precipitation_sum": [0.0, 0.123] + [None] * (n - 2),
            "precipitation_probability_max": [5, 40] + [None] * (n - 2),
            "weather_code": [0, 61, 95, 4] + [3] * (n - 4),
            "wind_speed_10m_max": [9.6, 14.2] + [3.0] * (n - 2)}}
    with open_meteo(handler) as seen:
        rows = weather.forecast(PLACE)
    assert len(rows) == 10
    host, q = seen[-1]
    assert q["forecast_days"] == "10"
    assert (q["temperature_unit"], q["wind_speed_unit"],
            q["precipitation_unit"]) == ("fahrenheit", "mph", "inch")
    assert "precipitation_probability_max" in q["daily"]
    assert (q["latitude"], q["longitude"]) == ("33.5", "-81.7")  # SC hit
    assert rows[0] == {"date": date.today().isoformat(), "sky": "Clear",
                       "high": 78, "low": 60, "rain_chance": 5,
                       "rain_in": 0.0, "wind": 10}
    assert rows[1]["sky"] == "Rain" and rows[1]["rain_in"] == 0.12
    assert rows[1]["rain_chance"] == 40 and rows[1]["high"] == 81
    assert rows[2]["sky"] == "Thunderstorms"
    assert rows[3]["sky"] == ""                     # unknown code
    assert rows[4]["rain_in"] is None and rows[4]["rain_chance"] is None
    assert set(rows[0]) == {"date", "sky", "high", "low", "rain_chance",
                            "rain_in", "wind"}


def test_forecast_days_capped_at_16():
    def handler(host, path, q):
        n = int(q["forecast_days"])
        return {"daily": {"time": _days(date.today().isoformat(),
                                        (date.today() + timedelta(n - 1))
                                        .isoformat()),
                          "weather_code": [1] * n}}
    with open_meteo(handler) as seen:
        rows = weather.forecast(PLACE, days=30)
    assert seen[-1][1]["forecast_days"] == "16" and len(rows) == 16
    assert rows[0]["sky"] == "Mostly clear" and rows[0]["high"] is None


def test_history_splits_archive_and_recent_and_clips_to_today():
    today = date.today()
    start, end = today - timedelta(days=20), today + timedelta(days=3)

    def handler(host, path, q):
        days = _days(q["start_date"], q["end_date"])
        rain = [0.5 if i % 3 == 0 else 0.0 for i in range(len(days))]
        hi = [80.0] * len(days)
        if host == "api.open-meteo.com":
            hi[-1] = None                       # today: not recorded yet
            rain[-1] = None
        return {"daily": {"time": days, "precipitation_sum": rain,
                          "temperature_2m_max": hi,
                          "temperature_2m_min": [60.0] * len(days)}}
    with open_meteo(handler) as seen:
        rows = weather.history(PLACE, start, end.isoformat())
    calls = [(h, q["start_date"], q["end_date"]) for h, q in seen
             if not h.startswith("geocoding")]
    cut = today - timedelta(days=weather.ARCHIVE_LAG)
    assert calls == [
        ("archive-api.open-meteo.com", start.isoformat(), cut.isoformat()),
        ("api.open-meteo.com", (cut + timedelta(1)).isoformat(),
         today.isoformat())]
    assert seen[-1][1]["precipitation_unit"] == "inch"
    want = _days(start.isoformat(), (today - timedelta(1)).isoformat())
    assert [r["date"] for r in rows] == want            # sorted, no gaps
    assert rows[0] == {"date": start.isoformat(), "rain_in": 0.5,
                       "high": 80, "low": 60}
    assert set(rows[1]) == {"date", "rain_in", "high", "low"}


def test_history_of_an_old_month_is_one_archive_call():
    def handler(host, path, q):
        assert host == "archive-api.open-meteo.com"
        days = _days(q["start_date"], q["end_date"])
        return {"daily": {"time": days, "precipitation_sum":
                          [0.25] * len(days),
                          "temperature_2m_max": [55.5] * len(days),
                          "temperature_2m_min": [33.3] * len(days)}}
    with open_meteo(handler) as seen:
        rows = weather.history(PLACE, "2026-05-01", date(2026, 5, 31))
    assert len([s for s in seen if not s[0].startswith("geo")]) == 1
    assert len(rows) == 31 and rows[-1]["date"] == "2026-05-31"
    assert rows[0]["high"] == 56 and rows[0]["low"] == 33
    assert sum(r["rain_in"] for r in rows) == pytest.approx(7.75)
    with pytest.raises(weather.WeatherError, match="after the end"):
        weather.history(PLACE, "2026-06-02", "2026-06-01")


def test_offline_and_refused_requests_give_clear_errors():
    def offline(*a):
        raise urllib.error.URLError("getaddrinfo failed")
    real = urllib.request.urlopen
    urllib.request.urlopen = lambda req, timeout=None: offline()
    weather._places.clear()
    try:
        with pytest.raises(weather.WeatherError,
                           match="internet connection") as e:
            weather.forecast(PLACE)
        assert "getaddrinfo failed" in str(e.value)
        with pytest.raises(ValueError):          # WeatherError is one
            weather.history(PLACE, "2026-05-01", "2026-05-02")
    finally:
        urllib.request.urlopen = real

    def refused(host, path, q):
        raise urllib.error.HTTPError(
            "https://" + host + path, 400, "Bad Request", {},
            io.BytesIO(b'{"error": true, "reason": "Parameter '
                       b'start_date is out of allowed range"}'))
    with open_meteo(refused):
        with pytest.raises(weather.WeatherError, match="HTTP 400") as e:
            weather.history(PLACE, "1900-01-01", "1900-01-02")
    assert "out of allowed range" in str(e.value)

    def timeout(host, path, q):
        raise TimeoutError("timed out")
    with open_meteo(timeout):
        with pytest.raises(weather.WeatherError, match="Open-Meteo"):
            weather.forecast(PLACE)


def test_daily_still_works():
    day = (date.today() - timedelta(days=1)).isoformat()

    def handler(host, path, q):
        assert host == "api.open-meteo.com"            # yesterday: recent
        return {"daily": {"time": [day], "temperature_2m_max": [71.6],
                          "temperature_2m_min": [52.1],
                          "precipitation_sum": [0.3],
                          "weather_code": [63],
                          "wind_speed_10m_max": [8.4]}}
    with open_meteo(handler):
        w = weather.daily(PLACE, day)
    assert w == {"high": "72", "low": "52", "precip": "0.30", "sky": "Rain",
                 "wind": "8", "source": "Open-Meteo, Testville, "
                                        "South Carolina"}
    assert weather.summary(w) == "72/52°F, Rain, 0.30 in rain, wind 8 mph"


def test_commercial_api_key_uses_the_customer_servers(monkeypatch):
    """Review 0.12.35 #15: the free servers stay the default; with an
    Open-Meteo commercial key every call goes to customer-... with
    &apikey=, and the source shown to the user says which."""
    def handler(host, path, q):
        if path == "/v1/search":
            return GEO
        days = _days(q.get("start_date") or date.today().isoformat(),
                     q.get("end_date") or date.today().isoformat())
        return {"daily": {"time": days,
                          "temperature_2m_max": [70.0] * len(days),
                          "temperature_2m_min": [50.0] * len(days),
                          "precipitation_sum": [0.1] * len(days)}}
    assert "free" in weather.source_label()
    with open_meteo(handler) as seen:
        weather.history(PLACE, date.today() - timedelta(days=20),
                        date.today())
    assert all(not h.startswith("customer-") and "apikey" not in q
               for h, q in seen)
    monkeypatch.setitem(settings._cache, "weather_api_key", "TEST-KEY-123")
    assert "commercial" in weather.source_label()
    assert "TEST-KEY-123" not in weather.source_label()
    with open_meteo(handler) as seen:
        weather.history(PLACE, date.today() - timedelta(days=20),
                        date.today())
    hosts = {h for h, _q in seen}
    assert hosts == {"customer-geocoding-api.open-meteo.com",
                     "customer-archive-api.open-meteo.com",
                     "customer-api.open-meteo.com"}
    assert all(q.get("apikey") == "TEST-KEY-123" for _h, q in seen)


COLUMBIAS = {"results": [
    {"name": "Columbia", "latitude": 34.0, "longitude": -81.0,
     "admin1": "South Carolina", "country_code": "US"},
    {"name": "Columbia", "latitude": 38.9, "longitude": -92.3,
     "admin1": "Missouri", "country_code": "US"},
    {"name": "Columbia", "latitude": 39.2, "longitude": -76.8,
     "admin1": "Maryland", "country_code": "US"}]}


@pytest.mark.parametrize("place, lat", [
    ("Columbia, MO", 38.9), ("Columbia, MD", 39.2), ("Columbia,SC", 34.0),
    ("Columbia, Missouri", 38.9), ("Columbia, maryland", 39.2),
    ("Columbia MO", 38.9), ("Columbia, MO, USA", 38.9),
    ("Columbia Maryland", 39.2), ("Columbia South Carolina", 34.0),
    ("Columbia Missouri", 38.9), ("Columbia maryland", 39.2),
    ("Columbia", 34.0)])                   # no state: the first hit
def test_locate_matches_the_state_code_or_name(monkeypatch, place, lat):
    """Review: states outside a 12-entry table were cut to their first two
    letters (missouri -> "mi"), so Columbia, MO / MD came back as Columbia,
    South Carolina. Every state + DC now maps code <-> name."""
    weather._places.clear()
    asked = []

    def fake_get(url):
        asked.append(dict(urllib.parse.parse_qsl(
            urllib.parse.urlsplit(url).query)))
        return COLUMBIAS
    monkeypatch.setattr(weather, "_get", fake_get)
    assert weather.locate(place)[0] == lat
    assert asked[0]["name"] == "Columbia"
    weather._places.clear()


def test_state_table_is_complete():
    assert len(weather._STATE_NAMES) == 51            # 50 states + DC
    assert weather._abbr("Missouri") == "mo"
    assert weather._abbr("District of Columbia") == "dc"
    assert weather._abbr("Ontario") == ""
    assert {weather._STATE_CODES[n] for n in weather._STATE_NAMES.values()} \
        == set(weather._STATE_NAMES)


@pytest.mark.parametrize("place, split", [
    ("Columbia Maryland", ("Columbia", "maryland")),
    ("Columbia South Carolina", ("Columbia", "south carolina")),
    ("Wheeling West Virginia", ("Wheeling", "west virginia")),
    ("Albany New York", ("Albany", "new york")),
    ("Columbia MD", ("Columbia", "md")),
    ("New York", ("New York", "")),        # the whole name is not a split
    ("Kansas City", ("Kansas City", "")),
    ("Columbia", ("Columbia", ""))])
def test_split_place_without_a_comma_reads_state_names(place, split):
    assert weather._split_place(place) == split


def test_trailing_state_word_with_no_hit_there_searches_the_whole_name(
        monkeypatch):
    """'Fort Washington' looks like 'Fort' + Washington; when no hit is in
    Washington state, the whole name is searched instead."""
    weather._places.clear()
    asked = []
    fort = {"results": [{"name": "Fort", "latitude": 1.0, "longitude": 1.0,
                         "admin1": "Texas", "country_code": "US"}]}
    fw = {"results": [{"name": "Fort Washington", "latitude": 38.7,
                       "longitude": -77.0, "admin1": "Maryland",
                       "country_code": "US"}]}

    def fake_get(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        asked.append(q["name"])
        return fw if q["name"] == "Fort Washington" else fort
    monkeypatch.setattr(weather, "_get", fake_get)
    assert weather.locate("Fort Washington")[0] == 38.7
    assert asked == ["Fort", "Fort Washington"]
    weather._places.clear()
