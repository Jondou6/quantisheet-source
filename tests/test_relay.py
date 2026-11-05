"""Live relay test over real websockets (no PyMuPDF or Qt needed)."""
import socket
import time

import pytest

pytest.importorskip("websockets")

from app.collab import relay                     # noqa: E402
from app.collab.client import CollabClient       # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_relay_password_burst_and_big_snapshot():
    ws_port, http_port = _free_port(), _free_port()
    relay.start_background("127.0.0.1", ws_port, http_port)
    url = f"ws://127.0.0.1:{ws_port}"
    got = {"b": [], "c": []}
    a = CollabClient(url, room="t", password="pw")
    b = CollabClient(url, room="t", password="pw",
                     on_event=lambda m: got["b"].append(m),
                     on_snapshot=lambda d: got["b"].append(d))
    c = CollabClient(url, room="t", password="nope",
                     on_error=lambda e: got["c"].append(e))
    for x in (a, b, c):
        x.start()
        time.sleep(0.2)
    try:
        assert _wait(lambda: a.connected and b.connected)
        assert _wait(lambda: got["c"]) and "password" in got["c"][0].lower()
        for i in range(600):
            a.send_event("op", {"n": i})
        pdf = bytes(range(256)) * 8000                 # ~2 MB
        a.send_snapshot(pdf)
        assert _wait(lambda: pdf in got["b"], 20)
        events = [m for m in got["b"] if isinstance(m, dict)]
        assert len(events) == 600
        assert events[0]["client_id"] == a.client_id
    finally:
        for x in (a, b, c):
            x.stop()
