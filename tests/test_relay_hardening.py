"""Relay hardening (review R7): message size, room squatting, password
lockout, path guards, token required off loopback, big snapshots in
parts, and the server copies kept equal."""
import asyncio
import filecmp
import importlib.util
import json
import os
import socket

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
websockets = pytest.importorskip("websockets")

from app.collab import relaycore as rc                         # noqa: E402
from app.collab import hub as hubmod                           # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location(
        "relay_server", os.path.join(ROOT, "server", "relay_server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_server_copies_match():
    for name in ("relaycore.py", "hub.py"):
        assert filecmp.cmp(os.path.join(ROOT, "app", "collab", name),
                           os.path.join(ROOT, "server", name), shallow=False)


def test_limits():
    assert rc.MAX_MESSAGE == 16 * 1024 * 1024
    with pytest.raises(SystemExit):
        rc.check_bind("0.0.0.0", None)
    rc.check_bind("127.0.0.1", None)
    rc.check_bind("0.0.0.0", "secret")


def test_path_guards(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("x")
    (tmp_path / "webx").mkdir()
    (tmp_path / "webx" / "secret.txt").write_text("s")
    assert rc.safe_join(str(web), "/index.html")
    assert rc.safe_join(str(web), "/../webx/secret.txt") is None
    assert rc.safe_join(str(web), "../../etc/passwd") is None
    rs = _load()
    rs.WEB_DIR = str(web)
    assert rs._http("/../webx/secret.txt")[0] == 404
    assert rs._http("/%2e%2e/webx/secret.txt")[0] == 404
    assert rs._http("/index.html")[0] == 200
    h = hubmod.Hub(str(tmp_path / "data"))
    with pytest.raises(hubmod.HubError):
        h._p("..", "data2", "x.json")


def test_guard_locks_out_after_five():
    t = [0.0]
    g = rc.Guard(clock=lambda: t[0])
    for _ in range(4):
        g.fail("1.2.3.4")
    assert not g.blocked("1.2.3.4")
    g.fail("1.2.3.4")
    assert g.blocked("1.2.3.4") and not g.blocked("5.6.7.8")
    t[0] = 61
    assert not g.blocked("1.2.3.4")


def test_snapshot_parts_round_trip():
    data = "A" * (rc.PART * 2 + 123)
    msgs = rc.split_snapshot(data, "s1")
    assert len(msgs) == 3 and all(m["type"] == "snapshot_part" for m in msgs)
    assert all(len(json.dumps(m)) < rc.MAX_MESSAGE for m in msgs)
    asm = rc.Assembler()
    out = None
    for m in reversed(msgs):                     # any order
        out = asm.add(m) or out
    assert out == data
    assert rc.split_snapshot("small", "s2")[0]["type"] == "snapshot"


class _FakeWS:
    """Enough of a websocket for Rooms.serve."""

    def __init__(self, ip):
        self.remote_address = (ip, 1)
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def test_room_squatting_and_brute_force():
    async def run():
        rooms = rc.Rooms(token=None)
        far = _FakeWS("10.0.0.9")
        await rooms.serve(far, {"type": "hello", "room": "job",
                                "password": "mine"})
        assert "no session" in far.sent[-1]["msg"]        # can't grab it
        # the host on the relay's own computer opens it
        host = _FakeWS("127.0.0.1")
        hold = asyncio.Event()

        class Staying(_FakeWS):
            async def __anext__(self):
                await hold.wait()
                raise StopAsyncIteration
        host = Staying("127.0.0.1")
        task = asyncio.ensure_future(rooms.serve(
            host, {"type": "hello", "room": "job", "password": "pw"}))
        await asyncio.sleep(0.05)
        assert "job" in rooms.rooms
        for _ in range(5):
            w = _FakeWS("10.0.0.9")
            await rooms.serve(w, {"type": "hello", "room": "job",
                                  "password": "guess"})
            assert w.sent[-1]["type"] == "error"
        w = _FakeWS("10.0.0.9")
        await rooms.serve(w, {"type": "hello", "room": "job",
                              "password": "pw"})       # right, but locked
        assert "Too many" in w.sent[-1]["msg"]
        ok = _FakeWS("10.0.0.10")
        await rooms.serve(ok, {"type": "hello", "room": "job",
                               "password": "pw"})
        assert ok.sent and ok.sent[0]["type"] == "peer_join"
        hold.set()
        await task
        # with a token, token holders may open rooms from anywhere
        tr = rc.Rooms(token="t")
        w = _FakeWS("10.0.0.9")
        await tr.serve(w, {"type": "hello", "room": "r", "password": "p",
                           "token": "t"})
        assert w.sent[0]["type"] == "peer_join"
    asyncio.run(run())


def test_oversized_message_is_refused():
    rs = _load()
    port = _port()
    relay = rs.Relay(token="t0k")

    async def run():
        async with rs.serve(relay.handler, "127.0.0.1", port,
                            max_size=rs.MAX_MESSAGE,
                            process_request=rs.process_request):
            url = f"ws://127.0.0.1:{port}/"
            async with websockets.connect(url, max_size=None) as a:
                await a.send(json.dumps({"type": "hello", "room": "j",
                                         "password": "p", "token": "t0k"}))
                await asyncio.wait_for(a.recv(), 5)          # peer_join
                big = json.dumps({"type": "event",
                                  "x": "A" * (rs.MAX_MESSAGE + 10)})
                with pytest.raises(Exception):
                    await a.send(big)
                    await asyncio.wait_for(a.recv(), 5)
    asyncio.run(run())


def test_big_snapshot_reaches_peer_in_parts(monkeypatch):
    from app.collab import client as cl
    monkeypatch.setattr(rc, "PART", 1000)
    c = cl.CollabClient("ws://x")
    pdf = os.urandom(5000)
    c.send_snapshot(pdf)
    parts = list(c._outbox)
    assert len(parts) > 1 and parts[0]["type"] == "snapshot_part"
    got = []
    r = cl.CollabClient("ws://x", on_snapshot=got.append)

    class WS:
        def __init__(self, msgs):
            self.msgs = [json.dumps(m) for m in msgs]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.msgs:
                raise StopAsyncIteration
            return self.msgs.pop(0)
    asyncio.run(r._recv_loop(WS(parts)))
    assert got == [pdf]
