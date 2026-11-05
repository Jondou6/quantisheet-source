"""Aerial takeoff stub: geo-scale math, scaled page, pluggable source."""
import math

import fitz
import pytest

from app import aerial, annotate, takeoff


def test_web_mercator_ground_resolution():
    # zoom 20 at Greenville SC (34.85 N): ~0.1225 m per pixel
    m = aerial.meters_per_pixel(34.85, 20)
    assert m == pytest.approx(156543.03392 * math.cos(math.radians(34.85)) / 2 ** 20)
    assert 0.11 < m < 0.13


class FakeSource(aerial.ImagerySource):
    name = "fake"

    def fetch(self, lat, lon, zoom, width, height):
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
        pix.set_rect(pix.irect, (120, 160, 90))
        return pix.tobytes("png"), aerial.meters_per_pixel(lat, zoom)


def test_page_is_scaled_so_area_tools_read_real_feet():
    d = fitz.open()
    src = FakeSource()
    pno = aerial.add_aerial_page(d, src, 34.85, -82.39, zoom=20, width=800, height=600)
    sc = annotate.read_scales(d)[pno]
    ft_px = aerial.meters_per_pixel(34.85, 20) / 0.3048
    page = d[pno]
    pts_per_px = page.rect.width / 800
    assert sc["ppu"] == pytest.approx(pts_per_px / ft_px, rel=1e-6)
    assert sc["unit"] == "ft"
    # a 100 x 100 pixel square is (100*ft_px)^2 sq ft
    s = 100 * pts_per_px
    a = takeoff.polygon_area([fitz.Point(0, 0), fitz.Point(s, 0), fitz.Point(s, s), fitz.Point(0, s)]) / sc["ppu"] ** 2
    assert a == pytest.approx((100 * ft_px) ** 2, rel=1e-3)
    assert "fake" in page.get_text()          # source + date credit printed


def test_no_source_configured_is_a_clear_error():
    with pytest.raises(aerial.NoImagerySource):
        aerial.get_source("google")


def test_file_source_from_known_resolution(tmp_path):
    p = tmp_path / "ortho.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 300), False)
    pix.set_rect(pix.irect, (90, 90, 90))
    pix.save(str(p))
    src = aerial.FileSource(str(p), feet_per_pixel=0.5)
    d = fitz.open()
    pno = aerial.add_aerial_page(d, src, 0, 0, width=400, height=300)
    assert annotate.read_scales(d)[pno]["ppu"] == pytest.approx((d[pno].rect.width / 400) / 0.5)


def test_pavement_mask_hook():
    import numpy as np
    img = np.zeros((50, 50, 3), np.uint8)
    img[:, :25] = (110, 110, 112)        # gray asphalt
    img[:, 25:] = (60, 140, 50)          # grass
    m = aerial.pavement_mask(img)
    assert m[:, :25].mean() > 0.9 and m[:, 25:].mean() < 0.1


# ---- network limits (Oct 20 review): Cancel, timeouts, an overall deadline
import threading                                       # noqa: E402
import time                                            # noqa: E402
import urllib.error                                    # noqa: E402
import urllib.request                                  # noqa: E402


class _Resp:
    """A fake urlopen answer handing out `chunks`, one per read()."""

    def __init__(self, chunks, ctype="image/png", gap=0.0):
        self.chunks, self.reads, self.gap = list(chunks), 0, gap
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        assert n == aerial.CHUNK               # read in 64 KB pieces
        self.reads += 1
        time.sleep(self.gap)
        return self.chunks.pop(0) if self.chunks else b""


def _silent_server(monkeypatch):
    """urlopen that never answers (until the test lets it go)."""
    gate = threading.Event()

    def urlopen(req, timeout=None):
        gate.wait(5)
        raise OSError("let go")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return gate


def test_get_reads_the_whole_answer(monkeypatch):
    r = _Resp([b"ab", b"cd", b"ef"], "image/jpeg")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: r)
    assert aerial._get("https://x.test/a", {"q": 1}) == (b"abcdef",
                                                         "image/jpeg")


def test_cancel_frees_the_caller_while_the_server_says_nothing(monkeypatch):
    gate = _silent_server(monkeypatch)
    ev = threading.Event()
    threading.Timer(0.2, ev.set).start()
    t = time.monotonic()
    try:
        with aerial.limits(cancel=ev):
            with pytest.raises(aerial.Cancelled):
                aerial._get("https://x.test/a", {}, timeout=120)
        assert time.monotonic() - t < 1.0
    finally:
        gate.set()


def test_cancel_is_checked_before_connecting(monkeypatch):
    called = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: called.append(1))
    ev = threading.Event()
    ev.set()
    with aerial.limits(cancel=ev):
        with pytest.raises(aerial.Cancelled):
            aerial._get("https://x.test/a", {})
    assert not called


def test_cancel_stops_reading_between_chunks(monkeypatch):
    r = _Resp([b"x" * 10] * 1000, gap=0.02)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: r)
    ev = threading.Event()
    threading.Timer(0.15, ev.set).start()
    with aerial.limits(cancel=ev):
        with pytest.raises(aerial.Cancelled):
            aerial._get("https://x.test/a", {})
    time.sleep(0.1)
    n = r.reads
    time.sleep(0.1)
    assert r.reads == n and n < 100               # the reader stopped too


def test_timeout_is_for_the_whole_request(monkeypatch):
    # a server trickling a byte at a time used to reset the socket timeout
    # on every read and hold the worker for minutes
    r = _Resp([b"x"] * 1000, gap=0.05)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: r)
    t = time.monotonic()
    with pytest.raises(TimeoutError):
        aerial._get("https://x.test/a", {}, timeout=0.3)
    assert time.monotonic() - t < 0.8


def test_the_jobs_deadline_wins_over_a_longer_timeout(monkeypatch):
    gate = _silent_server(monkeypatch)
    t = time.monotonic()
    try:
        with aerial.limits(deadline=t + 0.3):
            with pytest.raises(aerial.DeadlineExceeded):
                aerial._get("https://x.test/a", {}, timeout=120)
        assert time.monotonic() - t < 0.8
        with aerial.limits(deadline=time.monotonic() - 1):
            with pytest.raises(aerial.DeadlineExceeded):     # already late
                aerial._get("https://x.test/a", {})
    finally:
        gate.set()


def test_limits_reach_the_tile_and_layer_helper_threads(monkeypatch):
    seen = []

    def get(url, params, timeout=60):
        seen.append(aerial._ctl.get())
        raise OSError("no")
    ev = threading.Event()
    with aerial.limits(cancel=ev, deadline=123.0):
        aerial.site_layers(["flood", "wetlands"], 33.6, -79.1, 100, 75,
                           10, 8, get=get)
    assert seen and all(s == (ev, 123.0) for s in seen)


def test_no_network_is_a_clear_quick_geocode_error(monkeypatch):
    def urlopen(req, timeout=None):
        raise urllib.error.URLError("getaddrinfo failed")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    t = time.monotonic()
    with pytest.raises(RuntimeError) as e:
        aerial.geocode("1 Main St, Conway SC")
    assert time.monotonic() - t < 3
    msg = str(e.value)
    assert msg.startswith("Couldn't reach the US Census address service "
                          "(geocoding.geo.census.gov): getaddrinfo failed.")
    assert "internet connection or proxy" in msg


def test_geocode_timeout_is_20_s(monkeypatch):
    seen = {}

    def get(url, params, timeout=60):
        seen["t"] = timeout
        raise TimeoutError("no answer in 20 s")
    monkeypatch.setattr(aerial, "_get", get)
    with pytest.raises(RuntimeError, match="no answer in 20 s"):
        aerial.geocode("1 Main St, Conway SC")
    assert seen["t"] == 20


def test_usgs_timeout_message(monkeypatch, tmp_path):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path))
    seen = {}

    def get(url, params, timeout=60):
        seen["t"] = timeout
        raise TimeoutError("no answer")
    monkeypatch.setattr(aerial, "_get", get)
    with pytest.raises(RuntimeError) as e:
        aerial.NAIPSource().fetch(33.6, -79.1, 0, 0, 0)
    assert seen["t"] == aerial.NAIPSource.TIMEOUT == 120
    assert str(e.value) == ("The USGS imagery service didn't answer in 120 "
                            "s. It is often slow; try again in a few "
                            "minutes.")


def _stalling_server(answer):
    """A local server that takes the request and then stalls: with
    answer=True it sends headers and 3 bytes of a 1 MB body, else nothing.
    Returns (port, seen) where seen["closed"] is when it saw our close."""
    import socket
    import threading
    import time
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    seen = {}

    def serve():
        c, _ = srv.accept()
        c.recv(2000)
        if answer:
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\n\r\nabc")
        while True:
            try:
                d = c.recv(10)
            except OSError:
                d = b""
            if not d:
                seen["closed"] = time.time()
                break
        c.close()
        srv.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1], seen


@pytest.mark.parametrize("answer", [False, True])
def test_cancel_drops_a_real_connection_at_once(monkeypatch, answer):
    """Review 0.12.32 #8: Cancel frees the caller and the server sees the
    connection close within a second - before any answer, and while the
    body is stalling."""
    import threading
    import time
    from app import policy
    monkeypatch.setattr(policy, "check", lambda *a, **k: None)
    port, seen = _stalling_server(answer)
    ev = threading.Event()
    marks = {}

    def cancel_soon():
        time.sleep(0.5)
        marks["cancel"] = time.time()
        ev.set()
    threading.Thread(target=cancel_soon, daemon=True).start()
    t = time.time()
    with pytest.raises(aerial.Cancelled):
        with aerial.limits(cancel=ev):
            aerial._get(f"http://127.0.0.1:{port}/x", {}, timeout=60)
    assert time.time() - t < 2.0
    for _ in range(40):
        if "closed" in seen:
            break
        time.sleep(0.05)
    assert seen.get("closed", 9e9) - marks["cancel"] < 1.0


@pytest.mark.parametrize("answer", [False, True])
def test_cancel_leaves_no_fetch_thread_alive(monkeypatch, answer):
    """Review 0.12.35 #19: in 'no headers' mode a fetch thread was still
    alive right after Cancel. Every helper is a daemon and has ended
    within 1 s of Cancel (already when _get returns, normally)."""
    import threading
    import time
    from app import policy
    monkeypatch.setattr(policy, "check", lambda *a, **k: None)
    port, _seen = _stalling_server(answer)
    before = set(threading.enumerate())
    started = []
    real_start = threading.Thread.start

    def spy(self):
        if self.name == "aerial-get":
            started.append(self)
        return real_start(self)
    monkeypatch.setattr(threading.Thread, "start", spy)
    ev = threading.Event()
    threading.Timer(0.4, ev.set).start()
    with pytest.raises(aerial.Cancelled):
        with aerial.limits(cancel=ev):
            aerial._get(f"http://127.0.0.1:{port}/x", {}, timeout=60)
    t_cancel = time.monotonic()
    assert started and all(t.daemon for t in started)
    # _get waits briefly for its helper, so it has already ended here
    # (without that wait it was usually still unwinding)
    assert not any(t.is_alive() for t in started)
    while any(t.is_alive() for t in started) and \
            time.monotonic() - t_cancel < 1.0:
        time.sleep(0.01)
    assert not any(t.is_alive() for t in started)
    new = [t for t in threading.enumerate()
           if t not in before and t.name == "aerial-get"]
    assert new == []
