"""Aerial / satellite takeoff (later phase) - a stub with the imagery
source left pluggable. No paid API keys are bundled.

Flow: pick a source -> fetch an image centered on the site -> it becomes
a PDF page whose takeoff scale is set from the image's ground resolution
-> the ordinary Area / Length / Count tools and the Takeoff List (v5)
measure it in real feet. pavement_mask() is a hook for optional
segmentation (a trained model would replace the color rule).

Ground resolution for Web Mercator tiles (Google, Mapbox, Esri, Bing):
    meters/pixel = 156543.03392 * cos(latitude) / 2**zoom
(at 256-px tiles; a "@2x"/512 tile halves it). Sources that deliver
georeferenced orthophotos (county GIS, NAIP) give feet/pixel directly:
use FileSource(path, feet_per_pixel).

Licensing differs per source (Google's terms forbid storing/deriving
from imagery outside its Maps APIs; Esri/Nearmap/EagleView need a
license; NAIP and most county orthos are public) - see the spec §6.
"""
import math

import fitz

from . import annotate
from .dmoney import c2 as _c2

FT_PER_M = 1 / 0.3048


class NoImagerySource(RuntimeError):
    pass


def meters_per_pixel(lat, zoom, tile=256):
    return 156543.03392 * math.cos(math.radians(lat)) / 2 ** zoom * (256 / tile)


class ImagerySource:
    """Subclass and implement fetch(); register with register()."""
    name = "base"
    credit = ""

    def fetch(self, lat, lon, zoom, width, height):
        """-> (png bytes, meters per pixel)"""
        raise NotImplementedError


class FileSource(ImagerySource):
    """An orthophoto you already have (county GIS export, NAIP clip,
    drone map) with a known ground resolution."""
    name = "file"

    def __init__(self, path, feet_per_pixel):
        self.path, self.fpp = path, float(feet_per_pixel)

    def fetch(self, lat, lon, zoom, width, height):
        with open(self.path, "rb") as f:
            return f.read(), self.fpp / FT_PER_M


_SOURCES = {}


def register(key, source):
    _SOURCES[key] = source


def get_source(key):
    if key not in _SOURCES:
        raise NoImagerySource(
            f"No imagery source '{key}' is set up. Add one in Settings "
            "(your own API key / license) or use an orthophoto file.")
    return _SOURCES[key]


def add_aerial_page(doc, source, lat, lon, zoom=20, width=1600, height=1200,
                    captured="", at=None):
    """Add a page holding the source's image, scaled to real feet. Returns
    its index."""
    png, mpp = source.fetch(lat, lon, zoom, width, height)
    return add_aerial_page_from(doc, png, mpp, lat, lon, source.name,
                                source.credit, captured=captured, at=at,
                                note=getattr(source, "note", ""))


def add_aerial_page_from(doc, png, mpp, lat, lon, name, credit, captured="",
                         at=None, note="", layers=None):
    """Add a page holding an image already in hand (png/jpeg bytes, meters
    per pixel). The page is 0.75 pt per image pixel plus an 18 pt credit
    strip; its scale is set so Length / Area read real feet. `at` inserts
    it at that page index (default: the end). Returns its index."""
    pix = fitz.Pixmap(png)
    w_px, h_px = pix.width, pix.height
    pts_per_px = 0.75
    kw = {} if at is None else {"pno": at}
    layers = [ly for ly in (layers or []) if ly]
    strip = 18 + (14 if layers else 0)
    page = doc.new_page(width=w_px * pts_per_px,
                        height=h_px * pts_per_px + strip, **kw)
    img = fitz.Rect(0, 0, w_px * pts_per_px, h_px * pts_per_px)
    page.insert_image(img, stream=png)
    # site layers on top, each its own PDF layer you can switch off
    legend = []
    for label, data, source in layers:
        if isinstance(data, LayerProblem):
            legend.append(str(data))
        elif data:
            oc = doc.add_ocg(label, on=True)
            page.insert_image(img, stream=data, oc=oc)
            legend.append(f"{label} ({source})")
        else:
            legend.append(f"{label}: not available from {source} - try "
                          "again later")
    if legend:
        page.insert_text((4, h_px * pts_per_px + 27),
                         "Site layers (switch on/off in the Layers panel): "
                         + "; ".join(legend) + ". For review only - "
                         "confirm with the official maps.", fontsize=7)
    ft_per_px = mpp * FT_PER_M
    where = f"  ({lat:.6f}, {lon:.6f})" if (lat or lon) else ""
    page.insert_text((4, h_px * pts_per_px + 13),
                     f"Imagery: {name} {credit} {captured}  "
                     f"{ft_per_px:.3f} ft/px{note}{where}",
                     fontsize=7)
    geo = {"lat": lat, "lon": lon, "cx": img.width / 2,
           "cy": img.height / 2} if (lat or lon) else None
    annotate.apply_op(doc, annotate.new_op(
        "set_scale", page.number, ppu=pts_per_px / ft_per_px, unit="ft",
        name=f"aerial {ft_per_px:.3f} ft/px", geo=geo))
    return page.number


def pavement_mask(rgb):
    """Rough asphalt/concrete mask (low saturation, mid brightness) from
    an HxWx3 uint8 array -> HxW bool. Placeholder for a real segmentation
    model; results go to a review step like every other auto tool."""
    import numpy as np
    a = rgb.astype(np.int16)
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1)
    return (sat < 0.15) & (mx > 60) & (mx < 230)


# ------------------------------------------------- free USGS imagery
R_EARTH = 6378137.0
NAIP_URL = ("https://imagery.nationalmap.gov/arcgis/rest/services/"
            "USGSNAIPPlus/ImageServer/exportImage")
GEOCODE_URL = ("https://geocoding.geo.census.gov/geocoder/locations/"
               "onelineaddress")
UA = "QuantiSheet aerial takeoff"


# --- Cancel and an overall deadline for a whole job (Oct 20 review) ---
# A job (one Preview download, OK's page) runs inside limits(cancel=Event,
# deadline=monotonic time); every _get below it - in this thread or in the
# tile / layer helper threads - stops when Cancel is clicked or the
# deadline passes. A context variable, so the ImagerySource.fetch and
# geocode signatures (and the tests' fakes of _get) stay as they were.
import contextlib as _contextlib
import contextvars as _contextvars

CHUNK = 64 * 1024
HELPER_JOIN_S = 0.25      # how long Cancel waits for a helper to unwind
_ctl = _contextvars.ContextVar("aerial_limits", default=(None, None))


class Cancelled(RuntimeError):
    def __init__(self, msg="Stopped."):
        super().__init__(msg)


class DeadlineExceeded(RuntimeError):
    """The job's overall deadline passed (not an OSError, so the per-call
    "didn't answer" handlers below leave it alone)."""


@_contextlib.contextmanager
def limits(cancel=None, deadline=None):
    tok = _ctl.set((cancel, deadline))
    try:
        yield
    finally:
        _ctl.reset(tok)


def check():
    """Raise Cancelled / DeadlineExceeded if this job should stop now."""
    import time
    cancel, deadline = _ctl.get()
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if deadline is not None and time.monotonic() >= deadline:
        raise DeadlineExceeded("Out of time.")


def _in_job(fn):
    """fn wrapped to run under this thread's limits in a helper thread."""
    ctl = _ctl.get()

    def run(*a):
        tok = _ctl.set(ctl)
        try:
            return fn(*a)
        finally:
            _ctl.reset(tok)
    return run


class TooLarge(RuntimeError):
    """The server sent more than the request may be (H5)."""


MAX_IMAGE_BYTES = 40 * 1024 * 1024        # NAIP / tiles
MAX_JSON_BYTES = 2 * 1024 * 1024          # geocode and other answers


def _get(url, params, timeout=60, max_bytes=None):
    """GET -> (bytes, content type). `timeout` is the whole request's
    wall-clock limit (connecting, waiting and reading), not per socket
    call: a server trickling bytes or never answering used to hold a
    worker for minutes. The socket work runs in a helper thread, so Cancel
    and the job's deadline free the caller within ~0.1 s even while the
    server hasn't sent a byte (checking only between 64 KB chunks can't:
    USGS sends nothing for 20-80 s); the helper stops at its next chunk or
    its own socket timeout."""
    import threading
    import time
    import urllib.parse
    import urllib.request
    from . import policy
    policy.check("aerial", url)
    check()                                       # before connecting
    cancel, deadline = _ctl.get()
    now = time.monotonic()
    limit = float(timeout)
    by_deadline = deadline is not None and deadline - now < limit
    if by_deadline:
        limit = deadline - now
    if max_bytes is None:      # answers that are only text are small
        max_bytes = MAX_JSON_BYTES if url == GEOCODE_URL else \
            MAX_IMAGE_BYTES
    sep = "&" if "?" in url else "?"                  # L4
    req = urllib.request.Request(
        url + sep + urllib.parse.urlencode(params),
        headers={"User-Agent": UA})
    out, stop, finished = {}, threading.Event(), threading.Event()

    def pull():
        try:
            with _open(req, limit + 2, out) as r:
                out["resp"] = r            # so Cancel can close the socket
                ctype = r.headers.get("Content-Type", "")
                # never more than max_bytes: a server (or something in
                # between) sending 120 MB for a geocode was accepted
                # (outside review via Chief, Nov 7 - H5)
                try:
                    said = int(r.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    said = 0
                if max_bytes and said > max_bytes:
                    raise TooLarge(f"The server's answer is too large "
                                   f"({said:,} bytes).")
                parts, got = [], 0
                while True:
                    if stop.is_set() or (cancel is not None and
                                         cancel.is_set()):
                        return
                    b = r.read(CHUNK)
                    if not b:
                        break
                    got += len(b)
                    if max_bytes and got > max_bytes:
                        raise TooLarge(f"The server's answer is too large "
                                       f"(over {max_bytes:,} bytes).")
                    parts.append(b)
                out["v"] = (b"".join(parts), ctype)
        except BaseException as e:                        # noqa: BLE001
            out["e"] = e
        finally:
            finished.set()
    helper = threading.Thread(target=pull, name="aerial-get", daemon=True)
    helper.start()
    end = now + limit
    def hang_up():
        # drop the connection now (review 0.12.30 A3, 0.12.32 #8): shut the
        # raw socket down from this side - that never waits, and it wakes
        # the helper thread blocked in connect/read. Closing the response
        # here instead waited for the helper's read (30 s on a stalled
        # body) and did nothing before the server had answered.
        stop.set()
        sock = out.get("sock")
        if sock is not None:
            import socket as _socket
            try:
                sock.shutdown(_socket.SHUT_RDWR)
            except OSError:
                pass
        # the shutdown wakes the helper at once, but it still needs a
        # moment to unwind; wait briefly so it has ended when Cancel
        # returns (review 0.12.35 #19 - one was still alive right after
        # Cancel with a server that never sent headers). It is a daemon
        # thread, so one stuck in connect() can't hold the app open.
        helper.join(HELPER_JOIN_S)
    while not finished.wait(0.05):
        if cancel is not None and cancel.is_set():
            hang_up()
            raise Cancelled()
        if time.monotonic() >= end:
            hang_up()
            if by_deadline:
                raise DeadlineExceeded("Out of time.")
            raise TimeoutError(f"no answer in {timeout:g} s")
    if "e" in out:
        raise out["e"]
    if "v" not in out:                            # stopped mid-read
        check()
        raise Cancelled()
    return out["v"]


import urllib.request as _urlreq                    # noqa: E402

_STOCK_URLOPEN = _urlreq.urlopen               # the real one, at import


def _open(req, timeout, out):
    """urlopen, keeping the connection's raw socket in out["sock"] as soon
    as it is connected, so Cancel can shut it down. (When a test has
    replaced urllib.request.urlopen, that fake is used as is.)"""
    import http.client
    import urllib.request
    if urllib.request.urlopen is not _STOCK_URLOPEN:
        return urllib.request.urlopen(req, timeout=timeout)

    def keep(cls):
        class Conn(cls):
            def connect(self):
                super().connect()
                out["sock"] = self.sock
        return Conn

    class Http(urllib.request.HTTPHandler):
        def http_open(self, r):
            return self.do_open(keep(http.client.HTTPConnection), r)

    class Https(urllib.request.HTTPSHandler):
        def https_open(self, r):
            return self.do_open(keep(http.client.HTTPSConnection), r,
                                context=self._context)
    return urllib.request.build_opener(Http, Https).open(req,
                                                        timeout=timeout)


def busy_message(service, e):
    """A 502 / 503 / 504 is the service having trouble, not the PC's
    network (review 0.12.30 A2)."""
    return (f"The {service} is having trouble right now ({e.code}). Try "
            "again in a few minutes.")


def _server_busy(e):
    return getattr(e, "code", None) in (502, 503, 504)


def _get_retry(url, params, timeout):
    """_get, once more after ~2.5 s when the server answers 502/503/504
    quickly and the job's deadline leaves room."""
    import time
    t = time.monotonic()
    try:
        return _get(url, params, timeout=timeout)
    except OSError as e:
        if not _server_busy(e) or time.monotonic() - t > 15:
            raise
        _cancel, deadline = _ctl.get()
        if deadline is not None and deadline - time.monotonic() < 10:
            raise
        time.sleep(2.5)
        check()
        return _get(url, params, timeout=timeout)


def too_large_message(service):
    """The service, what happened, what to do (outside review N2/N3)."""
    return (f"The {service} sent more than QuantiSheet accepts for one "
            "picture. Make the area smaller (fewer feet across) and try "
            "again.")


def timeout_message(seconds):
    return (f"The USGS imagery service didn't answer in {seconds:g} s. It "
            "is often slow; try again in a few minutes.")


def _reason(e):
    r = getattr(e, "reason", None)
    if getattr(e, "code", None):                      # HTTPError
        return f"{e.code} {r or ''}".strip()
    return str(r or e) or e.__class__.__name__


def web_mercator(lat, lon):
    """(x, y) in EPSG:3857 meters."""
    x = R_EARTH * math.radians(lon)
    y = R_EARTH * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def naip_bbox(lat, lon, width_ft, height_ft):
    """EPSG:3857 bbox covering width x height of real ground around the
    point (Web Mercator stretches by 1/cos(latitude))."""
    k = 1.0 / math.cos(math.radians(lat))
    hw = width_ft * 0.3048 / 2 * k
    hh = height_ft * 0.3048 / 2 * k
    x, y = web_mercator(lat, lon)
    return (x - hw, y - hh, x + hw, y + hh)


class NAIPSource(ImagerySource):
    """USGS NAIP Plus orthoimagery from The National Map (public domain,
    free, no key): about 2 ft per pixel statewide, finer where the state
    or county flew high-resolution imagery. Needs internet."""
    name = "USGS NAIP Plus"
    credit = "(public domain, imagery.nationalmap.gov)"

    # the photo itself is ~2 ft per pixel (60 cm NAIP) at most sites; the
    # page is stored at 1 ft per pixel, smoothly enlarged by the server
    # (Jon, Oct 19: "Enlarge to 1 ft/px"), and says so in its credit line
    note = " (enlarged; the USGS photo is about 2 ft/px)"

    @staticmethod
    def note_for(ft_per_px):
        """The credit-line note for a page at this resolution (Venice N5:
        big views are coarser than the photo, not enlarged)."""
        if ft_per_px <= 1.5:
            return NAIPSource.note
        return " (the USGS photo is about 2 ft/px)"
    MAX_PX = 4000                    # the service's largest image side
    TIMEOUT = 120                    # one try, whole request (Oct 20)

    def __init__(self, width_ft=1000, ft_per_px=None, max_px=None,
                 height_ft=None, cache=True):
        self.width_ft = float(width_ft)
        self.height_ft = float(height_ft) if height_ft else \
            self.width_ft * 0.75
        self.max_px = int(max_px or self.MAX_PX)
        self.ft_per_px = float(ft_per_px) if ft_per_px else \
            max(1.0, self.width_ft / self.max_px)
        self.cache = cache

    def params(self, lat, lon):
        w_px = max(200, min(self.max_px,
                            int(round(self.width_ft / self.ft_per_px))))
        h_px = max(150, int(round(w_px * self.height_ft / self.width_ft)))
        bbox = naip_bbox(lat, lon, self.width_ft, self.height_ft)
        return {"bbox": ",".join(f"{_c2(v):.2f}" for v in bbox),
                "bboxSR": 3857, "imageSR": 3857,
                "size": f"{w_px},{h_px}", "format": "jpgpng",
                "interpolation": "RSP_BilinearInterpolation",
                "f": "image"}, w_px

    def fetch(self, lat, lon, zoom, width, height):
        params, w_px = self.params(lat, lon)
        mpp = self.width_ft * 0.3048 / w_px          # meters per pixel
        if self.cache:
            hit = cache_get(params)
            if hit is not None:
                return hit, mpp
        import urllib.error
        try:
            data, ctype = _get_retry(NAIP_URL, params, self.TIMEOUT)
        except urllib.error.HTTPError as e:            # Venice N7
            if _server_busy(e):
                raise RuntimeError(busy_message("USGS imagery service",
                                                e)) from e
            raise RuntimeError(f"The USGS imagery service refused the "
                               f"request ({e.code} {e.reason}).") from e
        except TimeoutError as e:
            raise RuntimeError(timeout_message(self.TIMEOUT)) from e
        except TooLarge as e:                    # outside review N3
            raise RuntimeError(too_large_message("USGS imagery service")) \
                from e
        except OSError as e:
            raise RuntimeError(
                "Couldn't reach the USGS imagery service "
                f"(imagery.nationalmap.gov): {_reason(e)}. Check the "
                "internet connection or proxy.") from e
        if "image" not in ctype or not (data.startswith(b"\x89PNG") or
                                        data.startswith(b"\xff\xd8")):
            raise RuntimeError("USGS imagery service didn't return a photo: "
                               + data[:200].decode("utf-8", "replace"))
        if self.cache:
            cache_put(params, data)
        return data, mpp


# ------------------------------------------------- photo cache on disk
CACHE_MB = 200


def _cache_dir():
    import os
    from . import settings
    return os.path.join(settings.DIR, "aerial_cache")


def _cache_key(params):
    import hashlib
    import json
    return hashlib.sha1(json.dumps(params, sort_keys=True).encode()
                        ).hexdigest()


def cache_get(params):
    """The photo for these exact request parameters, if it was downloaded
    before (any session), else None."""
    import os
    p = os.path.join(_cache_dir(), _cache_key(params) + ".img")
    try:
        with open(p, "rb") as f:
            data = f.read()
        os.utime(p)                                   # recently used
        return data or None
    except OSError:
        return None


def cache_put(params, data):
    """Keep a downloaded photo; the oldest go once the folder passes
    CACHE_MB."""
    import os
    d = _cache_dir()
    try:
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, _cache_key(params) + ".img")
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        files = [os.path.join(d, n) for n in os.listdir(d)
                 if n.endswith(".img")]
        files.sort(key=lambda f: os.path.getmtime(f))
        total = sum(os.path.getsize(f) for f in files)
        while files and total > CACHE_MB * 1024 * 1024:
            f = files.pop(0)
            total -= os.path.getsize(f)
            os.remove(f)
    except OSError:
        pass                                          # a cache, not data


# ------------------------------------------------- quick overview tiles
TILE_URL = ("https://basemap.nationalmap.gov/arcgis/rest/services/"
            "USGSImageryOnly/MapServer/tile/{z}/{y}/{x}")


def _tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.log(math.tan(math.radians(lat)) +
                      1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def _tile_latlon(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


TILE_TIMEOUT = 8                     # one tile (was 10 s per socket call)
OVERVIEW_S = 12                      # all of them: it's only a finder


def overview(lat, lon, across_ft, get=None, workers=8):
    """A quick, coarse picture of the area from USGS cached map tiles (a
    second or two, vs 20-80 s for a NAIP photo): (jpeg bytes, lat and lon
    of its top-left corner, ft per pixel). For finding the site only -
    never used for the page or its scale. None if no tiles came back."""
    import concurrent.futures
    import io
    from PIL import Image
    get = get or _get
    m_per_px = 156543.03392 * math.cos(math.radians(lat))
    # the finest level (<= 16, which these tiles have) that covers the
    # area with about 7 x 5 tiles
    z = 16
    while z > 8 and 7 * 256 * m_per_px / 2 ** z * FT_PER_M < across_ft:
        z -= 1
    cx, cy = _tile_xy(lat, lon, z)
    xs = range(int(cx) - 3, int(cx) + 4)
    ys = range(int(cy) - 2, int(cy) + 3)

    import time
    end = time.monotonic() + OVERVIEW_S

    def one(xy):
        x, y = xy
        left = end - time.monotonic()
        if left <= 0.2:
            return xy, None                  # a stalled server: stop asking
        try:
            data, ctype = get(TILE_URL.format(z=z, y=y, x=x), {},
                              timeout=min(TILE_TIMEOUT, left))
            if "image" in ctype:
                return xy, Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:                                 # noqa: BLE001
            pass                                     # missing tile: skip
        return xy, None
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        tiles = list(ex.map(_in_job(one), [(x, y) for y in ys for x in xs]))
    if not any(im for _xy, im in tiles):
        return None
    img = Image.new("RGB", (len(xs) * 256, len(ys) * 256), (40, 40, 40))
    for (x, y), im in tiles:
        if im is not None:
            img.paste(im.resize((256, 256)), ((x - xs[0]) * 256,
                                             (y - ys[0]) * 256))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    top_lat, left_lon = _tile_latlon(xs[0], ys[0], z)
    return out.getvalue(), top_lat, left_lon, m_per_px / 2 ** z * FT_PER_M


def crop(data, ft_per_px, center_px, width_ft, height_ft):
    """The part of a photo `width_ft` x `height_ft` around pixel
    `center_px`, as JPEG bytes. Clipped to the photo."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = width_ft / ft_per_px, height_ft / ft_per_px
    x0 = int(round(max(0, center_px[0] - w / 2)))
    y0 = int(round(max(0, center_px[1] - h / 2)))
    x1 = int(round(min(im.width, center_px[0] + w / 2)))
    y1 = int(round(min(im.height, center_px[1] + h / 2)))
    if x1 - x0 < 10 or y1 - y0 < 10:
        raise ValueError("The chosen area is outside the photo.")
    out = io.BytesIO()
    im.crop((x0, y0, x1, y1)).save(out, "JPEG", quality=88)
    return out.getvalue()


GEOCODE_TIMEOUT = 20


def geocode(address):
    """(lat, lon, matched address) from the US Census Bureau geocoder (free,
    no key). Also takes "lat, lon" typed directly."""
    import json
    import re
    m = re.match(r"^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$",
                 address or "")
    if m:
        return float(m.group(1)), float(m.group(2)), address.strip()
    import urllib.error
    try:
        data, _ = _get_retry(GEOCODE_URL, {"address": address,
                                           "benchmark": "Public_AR_Current",
                                           "format": "json"},
                             GEOCODE_TIMEOUT)
    except urllib.error.HTTPError as e:
        if _server_busy(e):
            raise RuntimeError(busy_message("US Census address service",
                                            e)) from e
        raise RuntimeError(
            f"The US Census address service refused the request ({e.code} "
            f"{e.reason}).") from e
    except OSError as e:          # URLError, TimeoutError
        raise RuntimeError(
            "Couldn't reach the US Census address service "
            f"(geocoding.geo.census.gov): {_reason(e)}. Check the internet "
            "connection or proxy.") from e
    try:
        reply = json.loads(data.decode("utf-8"))
        hits = (reply.get("result") or {}).get("addressMatches") or []
    except (ValueError, AttributeError, UnicodeDecodeError) as e:
        # not "Expecting value: line 1 column 1" (outside review, Nov 7)
        raise RuntimeError("The US Census address service sent back "
                           "something unexpected. Try again in a few "
                           "minutes, or type the site's latitude, "
                           "longitude.") from e
    if not hits:
        raise LookupError(f"No match for \"{address}\". Check the address, "
                          "or type the site's latitude, longitude.")
    c = hits[0]["coordinates"]
    return float(c["y"]), float(c["x"]), hits[0].get("matchedAddress", "")


def world_file_info(path):
    """(pixel size, reason): the pixel size from an image's world file
    (photo.pgw / .jgw / .tfw / .wld beside it), in the file's own units,
    or (None, why not). All six lines are read: a rotated photo (B or D
    not zero), unequal x and y pixels, or a short file is refused - its
    first line alone isn't the scale (outside review via Chief, Nov 7 -
    M14)."""
    import os
    base, ext = os.path.splitext(path)
    cands = [base + w for w in (ext[:2] + ext[-1:] + "w", ext + "w",
                                ".wld", ".pgw", ".jgw", ".tfw")]
    for c in cands:
        for name in (c, c.upper()):
            if not os.path.isfile(name):
                continue
            try:
                with open(name) as f:
                    vals = [float(x) for x in f.read().split()[:6]]
            except (OSError, ValueError):
                return None, "The world file can't be read."
            if len(vals) < 6:
                return None, "The world file is incomplete (fewer than " \
                    "6 lines)."
            a, d, b, e = vals[0], vals[1], vals[2], vals[3]
            tol = 1e-9 + 1e-6 * max(abs(a), abs(e))
            if abs(b) > tol or abs(d) > tol:
                return None, "The photo is rotated in its world file; " \
                    "enter the scale yourself."
            if not a or abs(abs(a) - abs(e)) > 1e-6 * max(abs(a), abs(e)):
                return None, "The world file's pixels aren't square; " \
                    "enter the scale yourself."
            return abs(a), ""
    return None, ""


def world_file_pixel(path):
    """Pixel size from the world file, or None (see world_file_info)."""
    return world_file_info(path)[0]


def aerial_document(source, lat, lon, captured=""):
    """A new one-page PDF holding the scaled photo."""
    doc = fitz.open()
    add_aerial_page(doc, source, lat, lon, captured=captured)
    return doc


def aerial_document_from(png, mpp, lat, lon, name, credit, note="",
                         layers=None):
    """A new one-page PDF from a photo already downloaded."""
    doc = fitz.open()
    add_aerial_page_from(doc, png, mpp, lat, lon, name, credit, note=note,
                         layers=layers)
    return doc


# ------------------------------------------------- site layers
# Free public map services drawn over the photo for a quick site check
# (Venice, Oct 19). Each is an ArcGIS "export" of exactly the photo's
# Web Mercator box at the photo's pixel size, so it lines up exactly.
SITE_LAYERS = {
    "flood": ("Flood zones", "FEMA NFHL",
              "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/"
              "MapServer/export", "show:28"),
    "wetlands": ("Wetlands", "USFWS NWI",
                 "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/"
                 "rest/services/Wetlands/MapServer/export", None),
    "contours": ("Contours", "USGS",
                 "https://carto.nationalmap.gov/arcgis/rest/services/"
                 "contours/MapServer/export", None),
}
LAYER_TIMEOUT = 60


def site_layer(key, lat, lon, width_ft, height_ft, w_px, h_px, get=None):
    """One site layer as a transparent PNG for the box width x height ft
    around lat/lon, or None if the service didn't give one."""
    label, source, url, show = SITE_LAYERS[key]
    get = get or _get
    params = {"bbox": ",".join(f"{_c2(v):.2f}" for v in naip_bbox(
        lat, lon, width_ft, height_ft)), "bboxSR": 3857, "imageSR": 3857,
        "size": f"{w_px},{h_px}", "format": "png32", "transparent": "true",
        "dpi": 96, "f": "image"}
    if show:
        params["layers"] = show
    try:
        data, ctype = get(url, params, timeout=LAYER_TIMEOUT)
    except TooLarge:
        # the real reason in the legend, not "try again later" (N2)
        return LayerProblem(f"{label}: the {source} answer was too large - "
                            "make the area smaller")
    except Exception:                                     # noqa: BLE001
        return None
    if "image" not in ctype or not data.startswith(b"\x89PNG"):
        return None
    return data


class LayerProblem(str):
    """Why a site layer is missing, said on the page's legend."""


def site_layers(keys, lat, lon, width_ft, height_ft, w_px, h_px, get=None):
    """[(label, png or None, source)] for the chosen layers, fetched at
    the same time."""
    import concurrent.futures
    keys = [k for k in keys if k in SITE_LAYERS]
    if not keys:
        return []
    with concurrent.futures.ThreadPoolExecutor(len(keys)) as ex:
        got = list(ex.map(_in_job(lambda k: site_layer(
            k, lat, lon, width_ft, height_ft, w_px, h_px, get)), keys))
    return [(SITE_LAYERS[k][0], data, SITE_LAYERS[k][1])
            for k, data in zip(keys, got)]


# ------------------------------------------------- site from the plans
import re as _re

_SUFFIX = (r"ROAD|RD|STREET|ST|AVENUE|AVE|HIGHWAY|HWY|BOULEVARD|BLVD|DRIVE|"
           r"DR|LANE|LN|WAY|PARKWAY|PKWY|PIKE|COURT|CT|CIRCLE|CIR|PLACE|PL|"
           r"TRAIL|TRL|LOOP|TERRACE|TER|BYPASS|BYP|EXPRESSWAY|ROUTE|RT")
_STREET = _re.compile(
    r"^\s*(\d{1,6}(?:-\d{1,6})?\s+(?:[NSEW]\.?\s+)?[A-Z0-9][A-Z0-9 .'&-]{1,40}?"
    r"\s(?:" + _SUFFIX + r")\.?(?:\s+(?:[NSEW]|NORTH|SOUTH|EAST|WEST|"
    r"EXT(?:ENSION)?)\b)?)(?:\s*,?\s*(?:SUITE|STE|UNIT|#).*)?$", _re.I)
_CITY = _re.compile(r"^\s*([A-Z][A-Z .'-]{1,40}),\s*([A-Z]{2}|[A-Z][a-z]+"
                    r"(?:\s[A-Z][a-z]+)?)\.?\s*(\d{5}(?:-\d{4})?)?\s*$", _re.I)
_SITE_LABEL = _re.compile(r"\b(PROJECT\s+(?:LOCATION|ADDRESS|SITE)|SITE\s+"
                          r"(?:ADDRESS|LOCATION)|LOCATION\s+MAP|VICINITY)",
                          _re.I)
_DEC = _re.compile(
    r"(?:LAT(?:ITUDE)?\.?\s*[:=]?\s*)?(?P<ns>[NS])?\s*(?P<lat>\d{2}\.\d{3,})"
    r"\s*°?\s*(?P<ns2>[NS])?\s*[,/ ]\s*(?:LONG?(?:ITUDE)?\.?\s*[:=]?\s*)?"
    r"(?P<ew>[EW])?\s*(?P<lon>-?\d{2,3}\.\d{3,})\s*°?\s*(?P<ew2>[EW])?",
    _re.I)
_DMS_NUM = (r"(\d{1,3})\s*°\s*(\d{1,2})\s*['’′]\s*(\d{1,2}(?:\.\d+)?)"
            r"\s*(?:\"|”|″|'')?")
_DMS_LEAD = _re.compile(r"\b([NSEW])\s*" + _DMS_NUM, _re.I)
_DMS_TRAIL = _re.compile(_DMS_NUM + r"\s*([NSEW])\b", _re.I)


def _lat_lon_in(text):
    """(lat, lon) printed in the text, or None (US-only sanity range)."""
    dms = [(h, d, m, s) for h, d, m, s in _DMS_LEAD.findall(text)]
    if len(dms) < 2:
        dms = [(h, d, m, s) for d, m, s, h in _DMS_TRAIL.findall(text)]
    if len(dms) >= 2:
        vals = {}
        for h, d, m, s in dms:
            h = h.upper()
            v = int(d) + int(m) / 60 + float(s) / 3600
            vals["lat" if h in "NS" else "lon"] = -v if h in "SW" else v
        if "lat" in vals and "lon" in vals:
            lat, lon = vals["lat"], vals["lon"]
            if 17 < lat < 72 and -180 < lon < -60:
                return lat, lon
    for m in _DEC.finditer(text):
        lat, lon = float(m.group("lat")), float(m.group("lon"))
        said = m.group(0).upper()
        if not ("LAT" in said or m.group("ns") or m.group("ns2") or
                m.group("ew") or m.group("ew2") or lon < 0):
            continue                  # two numbers that only look like it
        if (m.group("ns") or m.group("ns2") or "N").upper() == "S":
            lat = -lat
        ew = (m.group("ew") or m.group("ew2") or "").upper()
        if ew == "W" or (not ew and lon > 0 and 60 < lon < 180):
            lon = -abs(lon)
        if 17 < lat < 72 and -180 < lon < -60:
            return lat, lon
    return None


def _text_lines(page):
    """[(text, rect)] for each printed line on the page."""
    out = []
    for b in page.get_text("dict").get("blocks", []):
        for ln in b.get("lines", []):
            s = "".join(sp.get("text", "") for sp in ln.get("spans", []))
            if s.strip():
                out.append((s.strip(), fitz.Rect(ln["bbox"])))
    return out


def _addresses(page, lines=None):
    """[(street, city line, rect)] on a page: a street line, with the
    "CITY, ST 12345" line printed just under it (same block or not)."""
    lines = _text_lines(page) if lines is None else lines
    out = []
    for text, r in lines:
        m = _STREET.match(text)
        if not m:
            continue
        h = max(r.height, 4.0)
        city = ""
        below = sorted((c for c in lines
                        if 0 <= c[1].y0 - r.y0 <= 3.5 * h and
                        c[1].x0 < r.x1 and c[1].x1 > r.x0 and
                        _CITY.match(c[0])), key=lambda c: c[1].y0)
        if below:
            city = below[0][0].strip()
        out.append((m.group(1).strip(), city, r))
    return out


def find_site(doc, pages=6):
    """Where the project is, read from the plans: {"query", "found",
    "page", "kind"} or None. Printed latitude/longitude wins; otherwise
    the street address on the first sheets that isn't in every title
    block (that's the engineer's office), best near "PROJECT LOCATION",
    "SITE" or the vicinity map."""
    n = min(doc.page_count, pages)
    for pno in range(n):
        ll = _lat_lon_in(doc[pno].get_text())
        if ll:
            return {"query": f"{ll[0]:.6f}, {ll[1]:.6f}",
                    "found": f"latitude/longitude on page {pno + 1}",
                    "page": pno, "kind": "latlon"}
    seen, cands = {}, []
    for pno in range(n):
        page = doc[pno]
        lines = _text_lines(page)
        labels = [r for s, r in lines if _SITE_LABEL.search(s)]
        for street, city, rect in _addresses(page, lines):
            key = street.upper()
            seen[key] = seen.get(key, 0) + 1
            near = min((abs(rect.y0 - r.y1) + abs(rect.x0 - r.x0)
                        for r in labels), default=1e9)
            cands.append((street, city, pno, near))
    if not cands:
        return None
    best = None
    for street, city, pno, near in cands:
        repeats = seen[street.upper()] >= max(2, n // 2)   # a title block
        score = (0 if repeats else 2) + (2 if near < 300 else 0) + \
            (1 if city else 0) - pno * 0.1
        if best is None or score > best[0]:
            best = (score, street, city, pno, repeats)
    score, street, city, pno, repeats = best
    if repeats and score < 2:
        return None
    q = f"{street}, {city}" if city else street
    return {"query": q, "found": f"page {pno + 1}", "page": pno,
            "kind": "address"}
