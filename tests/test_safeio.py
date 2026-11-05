"""Crash-safe writes (upgrade spec Phase 0.5): a failed save leaves the old
file exactly as it was; a .bak is made once before in-place saves; a relay
reachable from the network needs a token."""
import os

import fitz
import pytest

from app import safeio


def test_failed_save_keeps_the_original(tmp_path, monkeypatch):
    p = tmp_path / "plan.pdf"
    d = fitz.open()
    d.new_page()
    d.save(str(p))
    before = p.read_bytes()
    d2 = fitz.open()
    d2.new_page().insert_text((72, 72), "new")

    def boom(path, **kw):
        with open(path, "wb") as f:
            f.write(b"half")
        raise RuntimeError("disk full")
    monkeypatch.setattr(d2, "save", boom)
    with pytest.raises(RuntimeError):
        safeio.atomic_save(d2, str(p))
    assert p.read_bytes() == before
    assert [x.name for x in tmp_path.iterdir()] == ["plan.pdf"]
    monkeypatch.undo()
    safeio.atomic_save(d2, str(p))
    assert "new" in fitz.open(str(p))[0].get_text()


def test_atomic_write_and_backup_once(tmp_path):
    p = tmp_path / "x.txt"
    safeio.atomic_write(p, "one")
    assert p.read_text() == "one"
    safeio.atomic_write(p, b"two")
    assert p.read_bytes() == b"two"
    bak = safeio.backup_once(str(p))
    assert open(bak).read() == "two"
    p.write_text("three")
    assert safeio.backup_once(str(p)) is None
    assert open(bak).read() == "two"


def test_relay_bind_rules():
    from app.collab.relaycore import check_bind
    with pytest.raises(SystemExit):
        check_bind("0.0.0.0", None)
    check_bind("127.0.0.1", None)                    # loopback: fine
    check_bind("0.0.0.0", "s3cret")                   # token: fine


def test_relay_token_decides_authed(tmp_path):
    import asyncio
    import json
    from app.collab import hub

    class WS:
        def __init__(self):
            self.sent = []

        async def send(self, m):
            self.sent.append(json.loads(m))

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration
    H = hub.Hub(str(tmp_path / "hub"))

    def authed(token, given):
        ws = WS()
        asyncio.run(hub.api_session(H, ws, {"type": "api", "token": given},
                                    {"ip": "10.9.9.9"}, token))
        return ws.sent[0]["authed"]
    assert authed("s3cret", "s3cret") is True
    assert authed("s3cret", "") is False
    assert authed("s3cret", "wrong") is False
    assert authed(None, "") is True
