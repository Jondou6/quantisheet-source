"""The hostable relay (server/relay_server.py): one port for WebSocket and
the web app, token and room passwords."""
import asyncio
import importlib.util
import json
import os
import socket
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
websockets = pytest.importorskip("websockets")


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


def test_hosted_relay_forwards_and_serves_web(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>QuantiSheet</h1>")
    rs = _load()
    monkeypatch.setattr(rs, "WEB_DIR", str(web))
    port = _port()
    relay = rs.Relay(token="t0k")

    async def run():
        async with rs.serve(relay.handler, "127.0.0.1", port,
                            process_request=rs.process_request):
            url = f"ws://127.0.0.1:{port}/"
            loop = asyncio.get_running_loop()
            body = await loop.run_in_executor(None, lambda: urllib.request
                                              .urlopen(url.replace("ws", "http")
                                                       + "healthz").read())
            assert body == b"ok"
            page = await loop.run_in_executor(None, lambda: urllib.request
                                              .urlopen(f"http://127.0.0.1:"
                                                       f"{port}/").read())
            assert b"QuantiSheet" in page
            connect = websockets.connect
            async with connect(url) as a, connect(url) as b, \
                    connect(url) as bad, connect(url) as wrong:
                hello = {"type": "hello", "room": "job", "password": "pw",
                         "token": "t0k"}
                await a.send(json.dumps(dict(hello, client_id="A")))
                await asyncio.sleep(0.1)
                await b.send(json.dumps(dict(hello, client_id="B")))
                await bad.send(json.dumps(dict(hello, token="nope")))
                assert "Bad relay token" in await bad.recv()
                await wrong.send(json.dumps(dict(hello, password="x")))
                assert "Wrong room password" in await wrong.recv()
                # A hears B join, then B gets A's change
                msgs = [json.loads(await a.recv()) for _ in range(2)]
                assert any(m["type"] == "peer_join" and m["count"] == 2
                           for m in msgs)
                await a.send(json.dumps({"type": "event", "op": {"k": 1}}))
                got = None
                for _ in range(3):
                    m = json.loads(await asyncio.wait_for(b.recv(), 5))
                    if m["type"] == "event":
                        got = m
                        break
                assert got and got["client_id"] == "A"

    asyncio.run(run())
