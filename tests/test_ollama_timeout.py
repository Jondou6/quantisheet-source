"""A slow or hung Ollama: clear timeout message, configurable wait."""
import io
import urllib.error

import pytest

from app.ai import review


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _raiser(exc):
    def urlopen(*a, **k):
        raise exc
    return urlopen


def _patch(monkeypatch, urlopen):
    """Requests go through review._opener() (no proxy, no redirects -
    threat model T-009), so the fake goes there; nothing reaches a real
    Ollama on the test PC."""
    class _Op:
        def open(self, req, timeout=None):
            return urlopen(req, timeout=timeout)
    monkeypatch.setattr(review, "_opener", lambda: _Op())


@pytest.mark.parametrize("exc", [
    TimeoutError("timed out"),
    urllib.error.URLError(TimeoutError("timed out")),
])
def test_timeout_says_timed_out_not_install_ollama(monkeypatch, exc):
    _patch(monkeypatch, _raiser(exc))
    with pytest.raises(review.AIError) as ei:
        review.summarize_text("hello")
    msg = str(ei.value)
    assert "didn't answer" in msg and "Install" not in msg


def test_unreachable_still_says_install(monkeypatch):
    _patch(monkeypatch,
           _raiser(urllib.error.URLError(ConnectionRefusedError())))
    with pytest.raises(review.AIError, match="local AI isn't running"):
        review.summarize_text("hello")


def test_timeout_is_configurable(monkeypatch):
    seen = {}

    def urlopen(req, timeout=None):
        seen["t"] = timeout
        return _Resp(b'{"response": "ok"}')
    _patch(monkeypatch, urlopen)
    monkeypatch.setattr(review, "TIMEOUT", 7.5)
    assert review.summarize_text("hello") == "ok"
    assert seen["t"] == 7.5
