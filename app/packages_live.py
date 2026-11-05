"""Live package status (Nov 4, Jon: "do both"): with a carrier's
developer keys, Package Tracker shows each package's status, latest scan
and delivery date in the list - no web page needed.

Keys live only on this computer, in the data folder (carrier_keys.json,
never in the repository). A carrier with no key keeps working as before:
Track opens its own page. Lookups only happen when someone clicks Check
Status, never in the background; nothing but the tracking number is sent,
straight to that carrier.

Carriers and what they need (Package Tracker > Carrier Keys):
  UPS   client_id, client_secret            (Tracking API, OAuth)
  FedEx api_key, secret_key                 (Track API, OAuth)
  USPS  consumer_key, consumer_secret       (Tracking v3, OAuth)
  DHL   api_key                             (Shipment Tracking - Unified)
"""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

TIMEOUT = 20
FIELDS = {"UPS": ("client_id", "client_secret"),
          "FedEx": ("api_key", "secret_key"),
          "USPS": ("consumer_key", "consumer_secret"),
          "DHL": ("api_key",)}
LABELS = {"client_id": "Client ID", "client_secret": "Client Secret",
          "api_key": "API Key", "secret_key": "Secret Key",
          "consumer_key": "Consumer Key", "consumer_secret": "Consumer Secret"}
HOSTS = {"UPS": "https://onlinetools.ups.com",
         "FedEx": "https://apis.fedex.com",
         "USPS": "https://apis.usps.com",
         "DHL": "https://api-eu.dhl.com"}
_tokens = {}                 # carrier -> (token, expires at)


class LiveError(Exception):
    pass


# ---- keys ------------------------------------------------------------------------

def keys_path():
    from . import settings
    return os.path.join(settings.DIR, "carrier_keys.json")


def load_keys():
    try:
        with open(keys_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_keys(keys):
    from . import safeio
    clean = {}
    for c, fields in FIELDS.items():
        k = {f: str((keys.get(c) or {}).get(f, "")).strip() for f in fields}
        if all(k.values()):
            clean[c] = k
    os.makedirs(os.path.dirname(keys_path()), exist_ok=True)
    safeio.atomic_write(keys_path(), json.dumps(clean, indent=1))
    _tokens.clear()
    return clean


def has_keys(carrier, keys=None):
    k = (load_keys() if keys is None else keys).get(carrier) or {}
    return all(k.get(f) for f in FIELDS.get(carrier, ("x",)))


def allowed():
    """Off when IT turns the program's internet use off."""
    try:
        from . import policy
        return not (policy.get("OfflineMode") or
                    policy.get("DisablePackageStatus"))
    except Exception:                                     # noqa: BLE001
        return True


# ---- http ------------------------------------------------------------------------

def _http(method, url, headers=None, data=None, opener=None):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:                                 # noqa: BLE001
            body = ""
        if e.code in (401, 403):
            raise LiveError("the carrier refused the keys - check them in "
                            "Carrier Keys")
        if e.code == 404:
            raise LiveError("the carrier has no record of this number yet")
        if e.code == 429:
            raise LiveError("too many lookups today - try again later")
        raise LiveError(f"the carrier answered {e.code} {body}".strip())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LiveError(f"couldn't reach the carrier ({e})")
    except ValueError:
        raise LiveError("the carrier's answer couldn't be read")


def _token(carrier, k, http):
    tok = _tokens.get(carrier)
    if tok and tok[1] > time.time() + 60:
        return tok[0]
    host = HOSTS[carrier]
    if carrier == "UPS":
        auth = base64.b64encode(f"{k['client_id']}:{k['client_secret']}"
                                .encode()).decode()
        d = http("POST", host + "/security/v1/oauth/token",
                 {"Authorization": "Basic " + auth,
                  "Content-Type": "application/x-www-form-urlencoded"},
                 b"grant_type=client_credentials")
    elif carrier == "FedEx":
        d = http("POST", host + "/oauth/token",
                 {"Content-Type": "application/x-www-form-urlencoded"},
                 urllib.parse.urlencode({
                     "grant_type": "client_credentials",
                     "client_id": k["api_key"],
                     "client_secret": k["secret_key"]}).encode())
    elif carrier == "USPS":
        d = http("POST", host + "/oauth2/v3/token",
                 {"Content-Type": "application/json"},
                 json.dumps({"grant_type": "client_credentials",
                             "client_id": k["consumer_key"],
                             "client_secret": k["consumer_secret"]}).encode())
    else:
        return None
    t = d.get("access_token")
    if not t:
        raise LiveError("the carrier didn't give a sign-in token - check "
                        "the keys")
    _tokens[carrier] = (t, time.time() + float(d.get("expires_in") or 1800))
    return t


# ---- reading each carrier's answer ---------------------------------------------------------

def _first(*vals):
    return next((v for v in vals if v), "")


def _ups(d):
    pk = (((d.get("trackResponse") or {}).get("shipment") or [{}])[0]
          .get("package") or [{}])[0]
    st = (pk.get("currentStatus") or {}).get("description", "")
    acts = pk.get("activity") or [{}]
    a = acts[0] if acts else {}
    loc = ((a.get("location") or {}).get("address") or {})
    dd = (pk.get("deliveryDate") or [{}])
    eta = dd[0].get("date", "") if dd else ""
    return {"status": _first(st, (a.get("status") or {}).get(
                "description")),
            "last_event": ((a.get("status") or {}).get("description", "") +
                           (f", {loc.get('city', '')} "
                            f"{loc.get('stateProvince', '')}"
                            if loc.get("city") else "")).strip(", "),
            "when": f"{a.get('date', '')} {a.get('time', '')}".strip(),
            "eta": eta,
            "delivered": "deliver" in st.lower()}


def _fedex(d):
    r = (((d.get("output") or {}).get("completeTrackResults") or [{}])[0]
         .get("trackResults") or [{}])[0]
    ls = r.get("latestStatusDetail") or {}
    dates = {x.get("type"): x.get("dateTime") for x in
             r.get("dateAndTimes") or []}
    sc = (r.get("scanEvents") or [{}])[0]
    loc = sc.get("scanLocation") or {}
    st = ls.get("description", "")
    return {"status": st,
            "last_event": (sc.get("eventDescription", "") +
                           (f", {loc.get('city', '')} "
                            f"{loc.get('stateOrProvinceCode', '')}"
                            if loc.get("city") else "")).strip(", "),
            "when": sc.get("date", ""),
            "eta": _first(dates.get("ESTIMATED_DELIVERY"),
                          dates.get("ACTUAL_DELIVERY"),
                          ((r.get("estimatedDeliveryTimeWindow") or {})
                           .get("window") or {}).get("ends")),
            "delivered": ls.get("code") == "DL" or
            "deliver" in st.lower() and "out for" not in st.lower()}


def _usps(d):
    ev = (d.get("trackingEvents") or [{}])
    e = ev[0] if ev else {}
    st = _first(d.get("statusSummary"), d.get("status"))
    return {"status": st,
            "last_event": (e.get("eventType", "") +
                           (f", {e.get('eventCity', '')} "
                            f"{e.get('eventState', '')}"
                            if e.get("eventCity") else "")).strip(", "),
            "when": e.get("eventTimestamp", ""),
            "eta": _first(d.get("expectedDeliveryDate"),
                          d.get("expectedDeliveryTimeStamp")),
            "delivered": "deliver" in str(d.get("status", "")).lower() and
            "out for" not in str(d.get("status", "")).lower()}


def _dhl(d):
    s = (d.get("shipments") or [{}])[0]
    cur = s.get("status") or {}
    loc = ((cur.get("location") or {}).get("address") or {})
    return {"status": _first(cur.get("description"), cur.get("status")),
            "last_event": (cur.get("description", "") +
                           (f", {loc.get('addressLocality', '')}"
                            if loc.get("addressLocality") else "")).strip(
                               ", "),
            "when": cur.get("timestamp", ""),
            "eta": s.get("estimatedTimeOfDelivery", ""),
            "delivered": cur.get("statusCode") == "delivered"}


def status(carrier, number, keys=None, http=None):
    """{"status", "last_event", "when", "eta", "delivered"} for one
    package, or None when that carrier has no keys. Raises LiveError."""
    keys = load_keys() if keys is None else keys
    if not has_keys(carrier, keys) or not allowed():
        return None
    k = keys[carrier]
    http = http or _http
    host = HOSTS[carrier]
    n = urllib.parse.quote(str(number))
    if carrier == "DHL":
        d = http("GET", host + f"/track/shipments?trackingNumber={n}",
                 {"DHL-API-Key": k["api_key"], "Accept": "application/json"})
        return _dhl(d)
    tok = _token(carrier, k, http)
    auth = {"Authorization": "Bearer " + tok, "Accept": "application/json"}
    if carrier == "UPS":
        d = http("GET", host + f"/api/track/v1/details/{n}",
                 dict(auth, transId=uuid.uuid4().hex[:32],
                      transactionSrc="QuantiSheet"))
        return _ups(d)
    if carrier == "FedEx":
        d = http("POST", host + "/track/v1/trackingnumbers",
                 dict(auth, **{"Content-Type": "application/json"}),
                 json.dumps({"includeDetailedScans": True, "trackingInfo": [
                     {"trackingNumberInfo": {"trackingNumber": str(number)}}
                 ]}).encode())
        return _fedex(d)
    d = http("GET", host + f"/tracking/v3/tracking/{n}?expand=DETAIL", auth)
    return _usps(d)


def check(items, keys=None, http=None, today=None):
    """Look up every not-delivered package whose carrier has keys. Updates
    each entry in place ("live": {...}, "checked"), marks delivered ones,
    and returns (looked up, errors {number: message})."""
    import datetime
    keys = load_keys() if keys is None else keys
    n, errors = 0, {}
    for p in items:
        if p.get("delivered") or not has_keys(p.get("carrier"), keys):
            continue
        try:
            s = status(p["carrier"], p["number"], keys, http)
        except LiveError as e:
            errors[p["number"]] = str(e)
            continue
        if s is None:
            continue
        n += 1
        p["live"] = s
        p["checked"] = (today or datetime.datetime.now()).strftime(
            "%Y-%m-%d %H:%M")
        if s.get("delivered"):
            p["delivered"] = True
    return n, errors
